"""Registered DWSIM tools and validated numerical request contracts."""

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys


RESULT_START='\x1eSEPMIND_DWSIM_RESULT_V1\x1e'
RESULT_END='\x1eSEPMIND_DWSIM_RESULT_END\x1e'


def decode_worker_record(stdout):
    """Separate native optimizer stdout from the worker's framed JSON result.

    No search for an arbitrary last JSON object: one complete, unique frame is
    required. Plain JSON remains supported for older workers and unit fixtures.
    """
    diagnostics=''
    if RESULT_START in stdout or RESULT_END in stdout:
        if stdout.count(RESULT_START)!=1 or stdout.count(RESULT_END)!=1:
            raise ValueError('Ambiguous native result framing')
        prefix,_,remaining=stdout.partition(RESULT_START)
        payload,_,suffix=remaining.partition(RESULT_END)
        if RESULT_END in prefix:raise ValueError('Reversed native result framing')
        diagnostics=(prefix+suffix).strip()
    else:payload=stdout
    record=json.loads(payload)
    if not isinstance(record,dict):raise ValueError('Native result must be an object')
    return record,diagnostics


@dataclass(frozen=True)
class BinaryVLERequest:
    # Exact DWSIM database names, in the declared composition order.
    components: tuple[str, str]
    property_package: str
    pressure_pa: float
    liquid_mole_fractions: tuple[float, ...]
    include_enthalpies: bool = False

    def __post_init__(self):
        if type(self.include_enthalpies) is not bool:
            raise ValueError('include_enthalpies must be boolean')
        if (len(self.components) != 2 or
                any(not isinstance(c, str) or not c.strip() for c in self.components) or
                self.components[0] == self.components[1]):
            raise ValueError("Specify two distinct DWSIM compound names.")
        if not isinstance(self.property_package, str) or not self.property_package.strip():
            raise ValueError("An explicit property package is required.")
        if not math.isfinite(self.pressure_pa) or self.pressure_pa <= 0:
            raise ValueError("pressure_pa must be finite and positive (Pa).")
        xs = self.liquid_mole_fractions
        if len(xs) < 2 or any(not math.isfinite(x) or not 0 < x < 1 for x in xs):
            raise ValueError("Supply at least two interior liquid mole fractions in (0, 1).")
        if any(a >= b for a, b in zip(xs, xs[1:])):
            raise ValueError("Liquid mole fractions must be strictly increasing.")


@dataclass(frozen=True)
class ShortcutDistillationRequest:
    """Binary Fenske-Underwood-Gilliland initialization, component 0 = light key."""

    components: tuple[str, str]
    property_package: str
    pressure_pa: float
    feed_molar_flow_mol_s: float
    feed_light_fraction: float
    distillate_light_purity: float
    light_recovery: float
    reflux_ratio: float
    feed_state: str = "saturated_liquid"

    def __post_init__(self):
        BinaryVLERequest(self.components, self.property_package, self.pressure_pa, (0.1, 0.9))
        for name in ("feed_light_fraction", "distillate_light_purity", "light_recovery"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"{name} must be finite and in (0, 1).")
        if self.distillate_light_purity <= self.feed_light_fraction:
            raise ValueError("Distillate purity must exceed the feed light-key fraction.")
        for name in ("feed_molar_flow_mol_s", "reflux_ratio"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if self.feed_state != "saturated_liquid":
            raise ValueError("The current shortcut protocol supports saturated-liquid feed only.")
        if not 0 < self.bottoms_light_fraction < self.feed_light_fraction:
            raise ValueError("Product specifications do not define a valid binary split.")

    @property
    def distillate_flow(self):
        return self.feed_molar_flow_mol_s * self.feed_light_fraction * self.light_recovery / self.distillate_light_purity

    @property
    def bottoms_light_fraction(self):
        f = self.feed_molar_flow_mol_s
        d = self.distillate_flow
        if d >= f:
            raise ValueError("Distillate flow must be smaller than the feed flow.")
        return (f * self.feed_light_fraction - d * self.distillate_light_purity) / (f - d)


@dataclass(frozen=True)
class RigorousColumnRequest:
    """Fixed-design MESH verification. Product compositions are NOT solver specs.

    equilibrium_stages includes the partial reboiler, excludes total condenser.
    feed_stage is numbered from the first equilibrium tray (one based).
    """
    components: tuple[str, str]
    property_package: str
    pressure_pa: float
    feed_molar_flow_mol_s: float
    feed_light_fraction: float
    distillate_flow_mol_s: float
    reflux_ratio: float
    equilibrium_stages: int
    feed_stage: int
    bottom_pressure_pa: float | None = None
    save_path: str | None = None
    solver_preference: str = 'default'
    include_profiles: bool = False
    initial_profile: list[dict[str, float]] | None = None
    initial_estimate_source_evidence_id: str | None = None

    def __post_init__(self):
        if self.solver_preference not in ('default', 'simultaneous_correction', 'modified_bubble_point'):
            raise ValueError('Unknown registered solver preference')
        if type(self.include_profiles) is not bool:
            raise ValueError('include_profiles must be boolean')
        if (self.initial_profile is None) != (self.initial_estimate_source_evidence_id is None):
            raise ValueError('A warm-start profile and its source evidence ID must be supplied together')
        if self.initial_profile is not None:
            fields={'temperature_K','liquid_flow_mol_s','vapor_flow_mol_s','liquid_light_fraction','vapor_light_fraction'}
            if len(self.initial_profile)!=self.equilibrium_stages+1:
                raise ValueError('Warm-start profile must contain every stage including condenser')
            for row in self.initial_profile:
                if set(row)!=fields or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in row.values()):
                    raise ValueError('Invalid finite warm-start profile fields')
                if row['temperature_K']<=0 or min(row['liquid_flow_mol_s'],row['vapor_flow_mol_s'])<0:
                    raise ValueError('Invalid warm-start temperature or flow')
                if not all(0<=row[k]<=1 for k in ('liquid_light_fraction','vapor_light_fraction')):
                    raise ValueError('Invalid warm-start composition')
        BinaryVLERequest(self.components, self.property_package, self.pressure_pa, (.1, .9))
        for name in ('feed_molar_flow_mol_s', 'distillate_flow_mol_s', 'reflux_ratio'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.distillate_flow_mol_s >= self.feed_molar_flow_mol_s:
            raise ValueError('Distillate flow must be smaller than feed flow')
        if not math.isfinite(self.feed_light_fraction) or not 0 < self.feed_light_fraction < 1:
            raise ValueError('Invalid feed composition')
        if type(self.equilibrium_stages) is not int or not 3 <= self.equilibrium_stages <= 300:
            raise ValueError('Supply 3..300 equilibrium stages')
        if type(self.feed_stage) is not int or not 1 <= self.feed_stage < self.equilibrium_stages:
            raise ValueError('Feed must enter a tray, indexed from one')
        if self.bottom_pressure_pa is not None and (not math.isfinite(self.bottom_pressure_pa) or self.bottom_pressure_pa < self.pressure_pa):
            raise ValueError('Bottom pressure must be finite and at least top pressure')
        if self.save_path is not None:
            path = Path(self.save_path)
            if not path.is_absolute() or path.suffix.lower() != '.dwxmz':
                raise ValueError('save_path must be an absolute .dwxmz path')


@dataclass(frozen=True)
class UtilityWaterRequest:
    cooling_inlet_K: float
    cooling_outlet_K: float
    steam_pressure_Pa: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.cooling_inlet_K,self.cooling_outlet_K,self.steam_pressure_Pa)):
            raise ValueError('Utility inputs must be finite')
        if not 273.16 <= self.cooling_inlet_K < self.cooling_outlet_K < 370:
            raise ValueError('Cooling water must remain liquid at 101325 Pa within 273.16..370 K')
        if not 1e5 <= self.steam_pressure_Pa <= 1e7:
            raise ValueError('Saturated steam pressure must be within 0.1..10 MPa absolute')


@dataclass(frozen=True)
class LiquidConditionRequest:
    components: tuple[str,str]
    property_package: str
    light_mole_fraction: float
    temperature_K: float
    pressure_Pa: float

    def __post_init__(self):
        BinaryVLERequest(self.components,self.property_package,self.pressure_Pa,(.1,.9))
        if not math.isfinite(self.light_mole_fraction) or not 0<self.light_mole_fraction<1:
            raise ValueError('Cold feed composition must be an interior mole fraction')
        if not math.isfinite(self.temperature_K) or not 273.16<=self.temperature_K<=350:
            raise ValueError('Teaching cold-feed property request supports 273.16..350 K')


class DwsimBackend:
    """Each call runs in a child process with an explicit wall-clock limit.

    This confines DWSIM's process-global cwd/runtime/console changes to its worker.
    Requests contain data only, never model-generated executable code.
    """

    def __init__(self, installation=None, timeout_s=120):
        candidates = [installation, os.environ.get("DWSIM_HOME"), "E:/DWSIM",
                      "C:/Program Files/DWSIM",
                      str(Path.home() / "AppData/Local/DWSIM")]
        if installation or os.environ.get("DWSIM_HOME"):
            candidates = [installation or os.environ["DWSIM_HOME"]]
        self.installation = next(
            (Path(p).resolve() for p in candidates if p and
             (Path(p) / "DWSIM.Automation.dll").is_file()), None
        )
        if self.installation is None:
            raise FileNotFoundError("Set DWSIM_HOME to the folder containing DWSIM.Automation.dll.")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive.")
        self.timeout_s = timeout_s

    def _run(self, action, payload=None):
        worker = Path(__file__).with_name("_dwsim_worker.py")
        request = {"action": action, "installation": str(self.installation),
                   "payload": payload or {}}
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            result = subprocess.run(
                [sys.executable, str(worker)], input=json.dumps(request),
                capture_output=True, text=True, encoding="utf-8",
                env=environment,
                timeout=self.timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            diagnostic = exc.stderr or ''
            if isinstance(diagnostic, bytes):
                diagnostic=diagnostic.decode('utf-8',errors='replace')
            raise TimeoutError(f"DWSIM exceeded {self.timeout_s}s; no result accepted. Last native progress: {diagnostic[-1500:]}") from exc
        if result.returncode != 0:
            raise RuntimeError(f"DWSIM worker failed: {result.stderr.strip() or result.stdout.strip()}")
        try:
            record,native_stdout = decode_worker_record(result.stdout)
        except (json.JSONDecodeError,ValueError) as exc:
            raise RuntimeError("DWSIM returned an invalid result record.") from exc
        if record.get("status") != "ok":
            raise RuntimeError(record.get("error", "DWSIM calculation failed."))
        record["engine_diagnostics"] = result.stderr.strip()
        if native_stdout:record['native_optimizer_stdout']=native_stdout[-10000:]
        return record

    def doctor(self):
        return self._run("doctor")

    def utility_water(self, request: UtilityWaterRequest):
        if not isinstance(request, UtilityWaterRequest):
            raise TypeError('Expected a validated UtilityWaterRequest')
        return self._run('utility_water', asdict(request))

    def liquid_condition(self,request: LiquidConditionRequest):
        if not isinstance(request,LiquidConditionRequest):
            raise TypeError('Expected a validated LiquidConditionRequest')
        return self._run('liquid_condition',asdict(request))

    def rigorous_column(self, request: RigorousColumnRequest):
        if not isinstance(request, RigorousColumnRequest):
            raise TypeError('Expected a validated RigorousColumnRequest')
        return self._run('rigorous_column', asdict(request))

    def binary_vle(self, request: BinaryVLERequest):
        if not isinstance(request, BinaryVLERequest):
            raise TypeError("Expected a validated BinaryVLERequest.")
        return self._run("binary_vle", asdict(request))

    def shortcut_distillation(self, request: ShortcutDistillationRequest):
        if not isinstance(request, ShortcutDistillationRequest):
            raise TypeError("Expected a validated ShortcutDistillationRequest.")
        return self._run("shortcut_distillation", asdict(request))
