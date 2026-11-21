"""General process contracts, alongside the frozen binary DesignBasis schema."""
from typing import Literal
from uuid import uuid4
from pydantic import Field, model_validator
from . import Contract, Component, DesignBasis, GateState, ToolResult, DecisionRecord


class ProcessStream(Contract):
    stream_id: str=Field(min_length=1)
    flow: float | None=Field(default=None,gt=0)
    flow_unit: Literal['kg/h','kmol/h'] | None=None
    composition: dict[str,float]=Field(default_factory=dict)
    composition_basis: Literal['mass_fraction','mole_fraction'] | None=None
    temperature_K: float | None=Field(default=None,gt=0)
    pressure_Pa: float | None=Field(default=None,gt=0)
    source_ids: list[str]=Field(default_factory=list)

    @model_validator(mode='after')
    def complete_composition(self):
        if self.composition and (min(self.composition.values())<0 or max(self.composition.values())>1 or abs(sum(self.composition.values())-1)>1e-8):
            raise ValueError('SOURCE_COMPOSITION_NONCLOSURE: do not silently normalize fractions')
        if self.composition and self.composition_basis is None:
            raise ValueError('COMPOSITION_BASIS_MISSING: fractions require an explicit basis')
        if (self.flow is None)!=(self.flow_unit is None):raise ValueError('FLOW_UNIT_MISSING: flow and unit must be supplied together')
        return self


class ProcessTarget(Contract):
    target_id: str
    location: str
    component_id: str | None=None
    component_ids: list[str]=Field(default_factory=list)
    quantity: Literal['mass_fraction','mole_fraction','recovery','concentration_mg_L','purity_basis_unresolved']
    operator: Literal['>=','<=','>','<']
    value: float=Field(gt=0)
    source_ids: list[str]=Field(default_factory=list)

    @model_validator(mode='after')
    def fractions(self):
        if bool(self.component_id)==bool(self.component_ids):raise ValueError('TARGET_COMPONENTS: specify one component or an explicit species sum')
        if len(self.component_ids)!=len(set(self.component_ids)):raise ValueError('DUPLICATE_TARGET_COMPONENT')
        if self.quantity in ('mass_fraction','mole_fraction','recovery') and self.value>1:
            raise ValueError('FRACTION_OUT_OF_RANGE: fraction/recovery targets are dimensionless, not percent')
        return self


class ExtractionSearch(Contract):
    configuration: Literal['countercurrent','crosscurrent']='countercurrent'
    stage_candidates: list[int]=Field(default_factory=lambda:[2,4,8])
    solvent_feed_mass_ratios: list[float]=Field(default_factory=lambda:[1.,2.,3.])
    maximum_candidates: int=Field(default=9,ge=1,le=36)
    max_iterations: int=Field(default=160,ge=5,le=300)

    @model_validator(mode='after')
    def limits(self):
        if not self.stage_candidates or any(type(n) is not int or not 1<=n<=30 for n in self.stage_candidates):
            raise ValueError('INVALID_STAGE_SEARCH: supply 1..30 contacts')
        if not self.solvent_feed_mass_ratios or any(not 0<s<=20 for s in self.solvent_feed_mass_ratios):
            raise ValueError('INVALID_SOLVENT_SEARCH: supply positive S/F <=20')
        if len(set(self.stage_candidates))!=len(self.stage_candidates) or len(set(self.solvent_feed_mass_ratios))!=len(self.solvent_feed_mass_ratios):
            raise ValueError('DUPLICATE_SEARCH_CANDIDATE')
        return self


class ProcessRedesignPolicy(Contract):
    """Bounds on design choices, never permission to relax product targets."""
    maximum_revisions: int=Field(default=2,ge=0,le=4)
    maximum_stages: int=Field(default=30,ge=1,le=30)
    maximum_solvent_feed_mass_ratio: float=Field(default=20,gt=0,le=20)
    maximum_candidates_per_revision: int=Field(default=9,ge=1,le=36)


class ProcessDesignBasis(Contract):
    design_id: str=Field(default_factory=lambda:str(uuid4()))
    process_family: Literal['binary_distillation','liquid_liquid_extraction','extraction_distillation']
    components: list[Component]=Field(default_factory=list)
    streams: list[ProcessStream]=Field(default_factory=list)
    feed_stream_id: str='feed'
    solvent_component_id: str | None=None
    carrier_component_id: str | None=None
    solute_component_id: str | None=None
    targets: list[ProcessTarget]=Field(default_factory=list)
    thermodynamic_model_id: str | None=None
    extraction_temperature_K: float | None=Field(default=None,gt=0)
    extraction_pressure_Pa: float | None=Field(default=None,gt=0)
    search: ExtractionSearch=Field(default_factory=ExtractionSearch)
    redesign_policy: ProcessRedesignPolicy=Field(default_factory=ProcessRedesignPolicy)
    source_ids: list[str]=Field(default_factory=list)
    assumptions: list[str]=Field(default_factory=list)
    unresolved_source_findings: list[str]=Field(default_factory=list)
    legacy_binary_basis: DesignBasis | None=None

    @model_validator(mode='after')
    def identities(self):
        ids=[c.canonical_id for c in self.components]
        if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_COMPONENT')
        stream_ids=[s.stream_id for s in self.streams]
        if len(stream_ids)!=len(set(stream_ids)):raise ValueError('DUPLICATE_STREAM')
        for s in self.streams:
            if set(s.composition)-set(ids):raise ValueError('UNKNOWN_STREAM_COMPONENT')
        for t in self.targets:
            if set(t.component_ids or [t.component_id])-set(ids):raise ValueError('UNKNOWN_TARGET_COMPONENT')
        for value in (self.solvent_component_id,self.carrier_component_id,self.solute_component_id):
            if value is not None and value not in ids:raise ValueError('UNKNOWN_PROCESS_COMPONENT')
        if self.process_family=='binary_distillation' and self.legacy_binary_basis is None:
            raise ValueError('BINARY_ADAPTER_REQUIRES_FROZEN_LEGACY_BASIS')
        return self


class ProcessDesignState(Contract):
    run_id: str=Field(default_factory=lambda:str(uuid4()))
    basis: ProcessDesignBasis
    status: Literal['running','needs_input','blocked','partial_design','failed']='running'
    gates: dict[str,GateState]=Field(default_factory=lambda:{f'G{i}':GateState(gate=f'G{i}') for i in range(10)})
    artifacts: dict[str,ToolResult]=Field(default_factory=dict)
    decisions: list[DecisionRecord]=Field(default_factory=list)
    provider: str='deterministic'
    llm_calls: int=0
    tool_calls: int=0
    provider_events: list[dict]=Field(default_factory=list)
    expert_records: list[dict]=Field(default_factory=list)
    questions: list[str]=Field(default_factory=list)
    original_message: str=''
    report_markdown: str=''
    revision: int=1
    parent_run_id: str | None=None
    accepted_candidate_id: str | None=None
    design_preferences: dict[str,str]=Field(default_factory=dict)
    active_search: ExtractionSearch | None=None
    revision_history: list[dict]=Field(default_factory=list)
    artifact_history: list[ToolResult]=Field(default_factory=list)


def parse_process_basis(value):
    """Preserve existing binary inputs byte-for-byte in their original model."""
    if isinstance(value,ProcessDesignBasis) or isinstance(value,dict) and 'process_family' in value:
        parsed=ProcessDesignBasis.model_validate(value)
        return parsed.legacy_binary_basis if parsed.process_family=='binary_distillation' else parsed
    return DesignBasis.model_validate(value or {})
