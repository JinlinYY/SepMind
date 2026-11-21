"""Bounded native multicomponent MESH requests for an explicit ideal slice.

No implicit NRTL parameters, HOC equivalence or qualification of the hybrid
acid/phenols systems. This adapter extends the retained DWSIM column engine.
"""
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from .dwsim import DwsimBackend
from pydantic import Field, model_validator
from sepmind.engineering.schemas import Contract


@dataclass(frozen=True)
class MultiColumnRequest:
    components: tuple[str,...]
    feed_mole_fractions: tuple[float,...]
    pressure_pa: float
    feed_molar_flow_mol_s: float
    distillate_flow_mol_s: float
    reflux_ratio: float
    equilibrium_stages: int
    feed_stage: int
    ideality_assumption_source: str
    property_package: str="Raoult's Law"
    bottom_pressure_pa: float | None=None
    save_path: str | None=None
    include_profiles: bool=True
    solver_preference: str='default'
    feed_temperature_K: float | None=None
    feed_specific_enthalpy_kJ_kg: float | None=None
    solver_tolerance: float=1e-5
    solver_iteration_limit: int=300
    strict_flash_tolerances: bool=False

    def __post_init__(self):
        if len(self.components)<3 or len(self.components)>8 or len(set(self.components))!=len(self.components):raise ValueError('Supply 3..8 distinct native compound names')
        allowed={'Benzene','Toluene','Ethylbenzene','n-Heptane','n-Nonane'}
        if not set(self.components)<=allowed or self.property_package!="Raoult's Law" or not self.ideality_assumption_source.strip():
            raise ValueError('PROPERTY_UNQUALIFIED: this adapter admits only the explicitly assumed ideal nonassociating slice; acid/phenols/NRTL require separate qualification')
        if len(self.feed_mole_fractions)!=len(self.components) or any(not math.isfinite(x) or x<0 or x>1 for x in self.feed_mole_fractions) or abs(sum(self.feed_mole_fractions)-1)>1e-9:raise ValueError('Invalid multicomponent feed fractions')
        if sum(x>0 for x in self.feed_mole_fractions)<2:raise ValueError('A separating column requires at least two present components')
        if self.feed_temperature_K is not None and (not math.isfinite(self.feed_temperature_K) or not 273.15<=self.feed_temperature_K<=600):raise ValueError('Invalid specified feed temperature')
        if self.feed_specific_enthalpy_kJ_kg is not None and (not math.isfinite(self.feed_specific_enthalpy_kJ_kg) or abs(self.feed_specific_enthalpy_kJ_kg)>1e6):raise ValueError('Invalid specified feed enthalpy')
        if self.feed_temperature_K is not None and self.feed_specific_enthalpy_kJ_kg is not None:raise ValueError('Supply a TP or PH feed state')
        if not math.isfinite(self.solver_tolerance) or not 1e-12<=self.solver_tolerance<=1e-5:raise ValueError('Invalid native solver tolerance')
        if type(self.solver_iteration_limit) is not int or not 20<=self.solver_iteration_limit<=1000:raise ValueError('Invalid native solver iteration limit')
        if type(self.strict_flash_tolerances) is not bool:raise ValueError('Flash precision flag must be boolean')
        if any(not math.isfinite(x) or x<=0 for x in (self.pressure_pa,self.feed_molar_flow_mol_s,self.distillate_flow_mol_s,self.reflux_ratio)) or self.distillate_flow_mol_s>=self.feed_molar_flow_mol_s:raise ValueError('Invalid fixed design flows/pressure/reflux')
        if type(self.equilibrium_stages) is not int or not 3<=self.equilibrium_stages<=100 or type(self.feed_stage) is not int or not 1<=self.feed_stage<self.equilibrium_stages:raise ValueError('Invalid equilibrium-stage convention')
        if self.bottom_pressure_pa is not None and (not math.isfinite(self.bottom_pressure_pa) or self.bottom_pressure_pa<self.pressure_pa):raise ValueError('Invalid bottom pressure')
        if self.save_path is not None and (not Path(self.save_path).is_absolute() or Path(self.save_path).suffix.lower()!='.dwxmz'):raise ValueError('Supply an absolute .dwxmz save path')
        if self.solver_preference not in ('default','modified_bubble_point','simultaneous_correction'):raise ValueError('Invalid solver preference')

    @property
    def initial_profile(self):return None
    @property
    def initial_estimate_source_evidence_id(self):return None


class MultiComponentDwsimBackend(DwsimBackend):
    def multicomponent_column(self,request):
        if not isinstance(request,MultiColumnRequest):raise TypeError('Expected a validated MultiColumnRequest')
        return self._run('multicomponent_column',asdict(request))

    def ideal_stage_probe(self, request):
        if not isinstance(request, IdealStageProbeRequest):
            raise TypeError('Expected a validated IdealStageProbeRequest')
        return self._run('ideal_stage_probe', request.model_dump())


class IdealStagePoint(Contract):
    point_id: str = Field(min_length=1, max_length=80)
    temperature_K: float = Field(ge=273.15, le=600)
    pressure_Pa: float = Field(ge=95000, le=110000)
    liquid_mole_fractions: list[float] = Field(min_length=3, max_length=5)
    vapor_mole_fractions: list[float] = Field(min_length=3, max_length=5)

    @model_validator(mode='after')
    def compositions(self):
        for values in [self.liquid_mole_fractions, self.vapor_mole_fractions]:
            if any(x<0 or x>1 for x in values) or abs(sum(values)-1)>1e-8:
                raise ValueError('Invalid phase composition')
        return self


class IdealStageProbeRequest(Contract):
    components: list[str] = Field(min_length=3, max_length=5)
    ideality_assumption_source: str = Field(min_length=3)
    points: list[IdealStagePoint] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def coverage(self):
        allowed = {'Benzene','Toluene','Ethylbenzene','n-Heptane','n-Nonane'}
        if len(set(self.components))!=len(self.components) or set(self.components)-allowed:
            raise ValueError('Unsupported ideal-stage components')
        if len({point.point_id for point in self.points}) != len(self.points):
            raise ValueError('Distinct stage point identities required')
        if any(len(point.liquid_mole_fractions)!=len(self.components) or len(point.vapor_mole_fractions)!=len(self.components) for point in self.points):
            raise ValueError('Phase component order differs from the request')
        return self
