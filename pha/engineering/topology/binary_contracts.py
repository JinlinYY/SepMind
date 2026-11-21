"""Binary topology research inputs built from original case requirements."""
from dataclasses import dataclass, asdict, replace
import math
from typing import Literal
from pydantic import Field, model_validator
from separation.tools.dwsim import RigorousColumnRequest, DwsimBackend
from separation.tools.multicomponent import IdealStagePoint, IdealStageProbeRequest
from ..schemas import Contract
from .schemas import ProductRequirement, TopologyDesignBasis, TopologyRunState, ColumnNode, FlowsheetGraph, TopologyProposal


BINARY_IDENTITIES = {'Benzene': '71-43-2', 'Toluene': '108-88-3',
                     'Ethanol': '64-17-5', 'Water': '7732-18-5', 'Methanol': '67-56-1'}
REGISTERED_PAIRS = {('Benzene', 'Toluene'): "Raoult's Law",
                    ('Ethanol', 'Water'): 'NRTL', ('Methanol', 'Water'): 'NRTL'}


class BinaryProduct(ProductRequirement):
    # Zero denotes an explicitly unspecified product purity or recovery bound.
    minimum_mole_fraction: float = Field(ge=0, lt=1)
    minimum_recovery: float = Field(ge=0, le=1)


class BinaryTopologyBasis(TopologyDesignBasis):
    components: list[str] = Field(min_length=2, max_length=2)
    feed_mole_fractions: list[float] = Field(min_length=2, max_length=2)
    property_package: Literal["Raoult's Law", 'NRTL']
    products: list[BinaryProduct] = Field(min_length=2, max_length=2)
    original_requirements: dict
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def scope_and_constraints(self):
        if REGISTERED_PAIRS.get(tuple(self.components)) != self.property_package:
            raise ValueError('BINARY_MODEL_UNSUPPORTED: frozen case pair and model required')
        z = self.feed_mole_fractions
        if any(x <= 0 or x >= 1 for x in z) or abs(sum(z)-1) > 1e-9:
            raise ValueError('FEED_COMPOSITION: explicit normalized mole fractions required')
        ids = [product.product_id for product in self.products]
        if len(set(ids)) != 2 or any(product.component not in self.components for product in self.products):
            raise ValueError('BINARY_PRODUCTS: distinct identified external outlets required')
        if any(name == 'feed' or (name.startswith('C') and name[1:].isdigit()) for name in ids):
            raise ValueError('PRODUCT_ID: product and equipment namespaces must be distinct')
        for component in self.components:
            if sum(product.minimum_recovery for product in self.products if product.component == component) > 1+1e-12:
                raise ValueError('HARD_CONSTRAINT_CONFLICT: recovery inventory exceeded')
        return self


class BinaryColumnNode(ColumnNode):
    initialization: Literal['native', 'native_cmo', 'native_enthalpy'] = 'native'
    solver_tolerance: float = Field(default=1e-9, ge=1e-10, le=1e-7)
    numerical_solver: Literal['native', 'sparse_trust_region'] = 'native'


class BinaryGraph(FlowsheetGraph):
    columns: list[BinaryColumnNode] = Field(min_length=1, max_length=4)


class BinaryProposal(TopologyProposal):
    graph: BinaryGraph


class BinaryTopologyState(TopologyRunState):
    basis: BinaryTopologyBasis
    graph: BinaryGraph | None = None
    scope: str = 'Case-bound binary topology synthesis under the frozen original native property model'


@dataclass(frozen=True)
class BinaryGraphColumnRequest:
    components: tuple[str, str]
    feed_mole_fractions: tuple[float, float]
    pressure_pa: float
    feed_molar_flow_mol_s: float
    distillate_flow_mol_s: float
    reflux_ratio: float
    equilibrium_stages: int
    feed_stage: int
    ideality_assumption_source: str
    property_package: str
    feed_temperature_K: float | None = None
    feed_specific_enthalpy_kJ_kg: float | None = None
    solver_preference: str = 'default'
    solver_tolerance: float = 1e-9
    solver_iteration_limit: int = 500
    strict_flash_tolerances: bool = True
    save_path: str | None = None
    include_profiles: bool = True
    bottom_pressure_pa: float | None = None
    initial_profile: list[dict] | None = None
    initial_estimate_source_evidence_id: str | None = None

    def __post_init__(self):
        if REGISTERED_PAIRS.get(tuple(self.components)) != self.property_package:
            raise ValueError('BINARY_MODEL_UNSUPPORTED')
        z = self.feed_mole_fractions
        if len(z) != 2 or any(not math.isfinite(x) or not 0 < x < 1 for x in z) or abs(sum(z)-1) > 1e-9:
            raise ValueError('Invalid physical binary composition')
        profile = self.initial_profile
        if profile and 'liquid_mole_fractions' in profile[0]:
            profile = [{key: row[key] for key in ['temperature_K', 'liquid_flow_mol_s', 'vapor_flow_mol_s']} |
                {'liquid_light_fraction': row['liquid_mole_fractions'][0],
                 'vapor_light_fraction': row['vapor_mole_fractions'][0]} for row in profile]
        RigorousColumnRequest(self.components, self.property_package, self.pressure_pa,
            self.feed_molar_flow_mol_s, z[0], self.distillate_flow_mol_s, self.reflux_ratio,
            self.equilibrium_stages, self.feed_stage, save_path=self.save_path,
            solver_preference=self.solver_preference, include_profiles=self.include_profiles,
            initial_profile=profile, initial_estimate_source_evidence_id=self.initial_estimate_source_evidence_id)
        if not self.ideality_assumption_source.strip():
            raise ValueError('Explicit model provenance required')
        if self.feed_specific_enthalpy_kJ_kg is not None and not math.isfinite(self.feed_specific_enthalpy_kJ_kg):
            raise ValueError('Finite upstream enthalpy required')
        if self.feed_temperature_K is not None:
            raise ValueError('Binary graph uses saturated source feed and explicit PH connections')
        if not 1e-12 <= self.solver_tolerance <= 1e-5 or not 20 <= self.solver_iteration_limit <= 1000:
            raise ValueError('Invalid numerical precision policy')


class BinaryStagePoint(IdealStagePoint):
    liquid_mole_fractions: list[float] = Field(min_length=2, max_length=2)
    vapor_mole_fractions: list[float] = Field(min_length=2, max_length=2)


class BinaryNativeFeed(Contract):
    feed_id: str
    flow_mol_s: float
    mole_fractions: list[float]
    temperature_K: float | None
    specific_enthalpy_kJ_kg: float | None
    stage_index: int
    source_evidence_id: str


@dataclass(frozen=True)
class BinarySparseColumnRequest(BinaryGraphColumnRequest):
    property_card_id: None = None
    numerical_solver: str = 'sparse_trust_region'
    numerical_jacobian_policy: str = 'balanced_reduced'
    solver_attempt_limit: int = 1
    temperature_guard_K: tuple[float, float] = (273.15, 600.)
    single_feed_graph: bool = True

    @property
    def column_mode(self):
        return 'total_condenser'

    @property
    def feeds(self):
        return [BinaryNativeFeed(feed_id='Feed', flow_mol_s=self.feed_molar_flow_mol_s,
            mole_fractions=list(self.feed_mole_fractions), temperature_K=None,
            specific_enthalpy_kJ_kg=self.feed_specific_enthalpy_kJ_kg,
            stage_index=self.feed_stage, source_evidence_id=self.ideality_assumption_source)]

    def model_copy(self, update):
        return replace(self, **update)

    def model_dump(self):
        return asdict(self)


class BinaryStageProbeRequest(IdealStageProbeRequest):
    components: list[str] = Field(min_length=2, max_length=2)
    points: list[BinaryStagePoint] = Field(min_length=1, max_length=100)
    property_package: Literal["Raoult's Law", 'NRTL']

    @model_validator(mode='after')
    def coverage(self):
        if REGISTERED_PAIRS.get(tuple(self.components)) != self.property_package:
            raise ValueError('BINARY_MODEL_UNSUPPORTED')
        if len({point.point_id for point in self.points}) != len(self.points):
            raise ValueError('Distinct phase-probe point identities required')
        return self


class BinaryTopologyBackend(DwsimBackend):
    def multicomponent_column(self, request):
        from dataclasses import asdict
        if not isinstance(request, BinaryGraphColumnRequest):
            raise TypeError('Binary graph request required')
        return self._run('topology_binary_column', asdict(request))

    def ideal_stage_probe(self, request):
        if not isinstance(request, BinaryStageProbeRequest):
            raise TypeError('Binary stage probe request required')
        return self._run('topology_binary_stage_probe', request.model_dump())
