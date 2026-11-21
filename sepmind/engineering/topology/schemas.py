"""Data-only topology contracts. Model outputs contain design hypotheses only."""
from typing import Literal
from uuid import uuid4
from pydantic import Field, model_validator
from ..schemas import Contract, ToolResult, GateState


IDEAL_COMPONENTS = {
    'Benzene': '71-43-2', 'Toluene': '108-88-3', 'Ethylbenzene': '100-41-4',
    'n-Heptane': '142-82-5', 'n-Nonane': '111-84-2',
}
IDENTIFIER = r'^[A-Za-z][A-Za-z0-9_]{0,31}$'
STREAM_REFERENCE = r'^(feed|C[1-9][0-9]?\.(distillate|bottoms))$'


class ProductRequirement(Contract):
    product_id: str = Field(pattern=IDENTIFIER)
    component: str
    minimum_mole_fraction: float = Field(gt=0, lt=1)
    minimum_recovery: float = Field(gt=0, le=1)


class TopologyBudget(Contract):
    maximum_candidates: int = Field(default=4, ge=1, le=8)
    maximum_columns: int = Field(default=4, ge=1, le=4)
    maximum_llm_calls: int = Field(default=14, ge=3, le=24)
    maximum_native_calls: int = Field(default=16, ge=2, le=32)
    native_timeout_s: float = Field(default=100, ge=5, le=180)
    run_timeout_s: float = Field(default=1200, ge=10, le=3600)
    desired_verified_topologies: int = Field(default=1, ge=1, le=3)


class TopologyDesignBasis(Contract):
    design_id: str = Field(default_factory=lambda: str(uuid4()))
    components: list[str] = Field(min_length=3, max_length=5)
    feed_mole_fractions: list[float] = Field(min_length=3, max_length=5)
    feed_flow_mol_s: float = Field(gt=0, le=10000)
    pressure_Pa: float = Field(ge=95000, le=110000)
    feed_state: Literal['saturated_liquid']
    property_package: Literal["Raoult's Law"]
    ideality_assumption_source: str = Field(min_length=3, max_length=1000)
    products: list[ProductRequirement] = Field(min_length=2, max_length=5)
    budget: TopologyBudget = Field(default_factory=TopologyBudget)

    @model_validator(mode='after')
    def scope_and_constraints(self):
        if len(set(self.components)) != len(self.components) or set(self.components)-set(IDEAL_COMPONENTS):
            raise ValueError('MODEL_UNSUPPORTED: use registered nonassociating hydrocarbon identities')
        z = self.feed_mole_fractions
        if len(z) != len(self.components) or any(x <= 0 or x >= 1 for x in z) or abs(sum(z)-1) > 1e-9:
            raise ValueError('FEED_COMPOSITION: explicit positive mole fractions must sum to one')
        ids = [product.product_id for product in self.products]
        if len(set(ids)) != len(ids) or 'feed' in ids or any(identifier.startswith('C') and identifier[1:].isdigit() for identifier in ids):
            raise ValueError('PRODUCT_ID: provide distinct product identities outside the column namespace')
        if any(product.component not in self.components for product in self.products):
            raise ValueError('UNKNOWN_PRODUCT_COMPONENT')
        for component in self.components:
            if sum(product.minimum_recovery for product in self.products if product.component == component) > 1+1e-12:
                raise ValueError('HARD_CONSTRAINT_CONFLICT: component recovery requirements exceed available input')
        if len(self.products) > self.budget.maximum_columns+1:
            raise ValueError('HARD_CONSTRAINT_CONFLICT: insufficient allowed separating outlets')
        return self


class ColumnNode(Contract):
    column_id: str = Field(pattern=r'^C[1-9][0-9]?$')
    input_stream: str = Field(pattern=STREAM_REFERENCE)
    equilibrium_stages: int = Field(ge=3, le=100, strict=True)
    feed_stage: int = Field(ge=1, le=99, strict=True)
    reflux_ratio: float = Field(ge=0.1, le=20)
    distillate_fraction: float = Field(gt=0.0001, lt=0.9999)
    solver_preference: Literal['default', 'modified_bubble_point', 'simultaneous_correction'] = 'default'

    @model_validator(mode='after')
    def stage_location(self):
        if self.feed_stage >= self.equilibrium_stages:
            raise ValueError('FEED_STAGE: feed must enter an interior stage')
        return self


class ProductOutlet(Contract):
    product_id: str = Field(pattern=IDENTIFIER)
    input_stream: str = Field(pattern=STREAM_REFERENCE)


class FlowsheetGraph(Contract):
    columns: list[ColumnNode] = Field(min_length=1, max_length=4)
    products: list[ProductOutlet] = Field(min_length=2, max_length=5)


class TopologyProposal(Contract):
    graph: FlowsheetGraph
    skill_id: Literal['topology_construction', 'topology_counterevidence']
    evidence_ids: list[str]
    rationale: str = Field(min_length=1, max_length=1800)


class ExpertAssessment(Contract):
    evidence_ids: list[str] = Field(min_length=1)
    observation: str = Field(min_length=1, max_length=1500)
    recommendation: str = Field(min_length=1, max_length=1500)


class TopologyRunState(Contract):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    basis: TopologyDesignBasis
    status: Literal['ready', 'running', 'passed', 'failed', 'blocked'] = 'ready'
    gates: dict[str, GateState] = Field(default_factory=lambda: {
        gate: GateState(gate=gate) for gate in ['G0', 'G1', 'G2', 'G4', 'G8', 'G9']})
    graph: FlowsheetGraph | None = None
    artifacts: dict[str, ToolResult] = Field(default_factory=dict)
    candidates: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    accepted_candidate_id: str | None = None
    llm_calls: int = 0
    native_calls: int = 0
    tool_calls: int = 0
    provider_events: list[dict] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    report_markdown: str = ''
    implementation_sha256: str = ''
    source_integrity_passed: bool | None = None
    scope: str = 'Bounded acyclic multicomponent distillation synthesis under an explicit ideal model assumption'
