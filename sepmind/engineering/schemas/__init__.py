"""Runtime contracts corresponding to engineering/contracts, version 2."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Component(Contract):
    canonical_id: str
    name: str
    cas: str | None = None


class Feed(Contract):
    flow: float | None = Field(default=None, gt=0)
    flow_unit: Literal["kmol/h", "mol/s"] | None = None
    composition: list[float] = Field(default_factory=list)
    composition_basis: Literal["mole_fraction", "mass_fraction"] | None = None
    temperature_K: float | None = Field(default=None, gt=0)
    pressure_kPa: float | None = Field(default=None, gt=0)
    quality_q: float | None = None

    @model_validator(mode="after")
    def fractions(self):
        if self.composition and (any(not 0 <= x <= 1 for x in self.composition)
                                 or abs(sum(self.composition) - 1) > 1e-8):
            raise ValueError("Feed fractions must be in [0,1] and sum to one")
        return self


class Target(Contract):
    distillate_mole_fraction: float | None = Field(default=None, gt=0, lt=1)
    bottoms_mole_fraction: float | None = Field(default=None, gt=0, lt=1)
    key_component_recovery: float | None = Field(default=None, gt=0, lt=1)
    production_rate: float | None = Field(default=None, gt=0)


class Column(Contract):
    reflux_ratio: float | None = Field(default=None, gt=0)
    reflux_multiplier: float | None = Field(default=None, gt=1)
    max_stages: int = Field(default=200, ge=1, le=1000)

    @model_validator(mode='after')
    def independent_reflux_specification(self):
        if self.reflux_ratio is not None and self.reflux_multiplier is not None:
            raise ValueError('Specify operating reflux OR an R/Rmin constraint, not both')
        return self


class WeepingCoefficient(Contract):
    K2: float = Field(gt=0)
    clear_liquid_depth_min_mm: float = Field(gt=0)
    clear_liquid_depth_max_mm: float = Field(gt=0)
    source_id: str = Field(min_length=1)

    @model_validator(mode='after')
    def interval(self):
        if self.clear_liquid_depth_max_mm < self.clear_liquid_depth_min_mm:
            raise ValueError('Weeping coefficient depth interval is reversed')
        return self


class F1ValveBasis(Contract):
    hole_diameter_m: float = Field(default=.039,gt=0)
    valve_mass_g: float = Field(default=34.,gt=0)
    minimum_hole_factor: float = Field(default=5.,gt=0)
    minimum_design_hole_factor: float = Field(default=8.,gt=0)
    maximum_hole_factor: float = Field(default=12.,gt=0)
    aeration_factor: float = Field(default=.5,gt=0,le=1)
    edge_clearance_m: float = Field(default=.05,gt=0)
    disengagement_strip_m: float = Field(default=.075,ge=0)
    minimum_pitch_m: float = Field(default=.075,gt=0)
    maximum_pitch_m: float = Field(default=.15,gt=0)
    minimum_weir_crest_m: float = Field(default=.006,gt=0)
    minimum_downcomer_residence_s: float = Field(default=5.,ge=3)
    francis_E: float = Field(default=1.,gt=0,le=1.2)
    entrainment_capacity_m_s: float | None = Field(default=None,gt=0)
    entrainment_source_id: str | None = None
    entrainment_max_index: float = Field(default=.8,gt=0,le=.8)
    property_factor: float = Field(default=1.,gt=0)

    @model_validator(mode='after')
    def qualified_teaching_geometry(self):
        if abs(self.hole_diameter_m-.039)>1e-9 or abs(self.valve_mass_g-34)>1e-9:
            raise ValueError('The registered F1 teaching fit is limited to 39 mm holes and 34 g heavy valves')
        if self.maximum_pitch_m < self.minimum_pitch_m or self.minimum_pitch_m < self.hole_diameter_m:
            raise ValueError('Invalid F1 valve-center pitch range')
        if (self.entrainment_capacity_m_s is None)!=(self.entrainment_source_id is None):
            raise ValueError('F1 CF and its chart/source identity must be supplied together')
        return self


class PumpCurve(Contract):
    model: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    flow_m3_h: list[float] = Field(min_length=2,max_length=500)
    head_m: list[float] = Field(min_length=2,max_length=500)
    npsh_required_m: list[float] | None = None
    efficiency: list[float] | None = None
    motor_power_kW: float | None = Field(default=None,gt=0)

    @model_validator(mode='after')
    def ordered_curve(self):
        n=len(self.flow_m3_h)
        if len(self.head_m)!=n or any(q<0 for q in self.flow_m3_h) or any(h<=0 for h in self.head_m):
            raise ValueError('Pump curve requires nonnegative flow and positive matched heads')
        if any(a>=b for a,b in zip(self.flow_m3_h,self.flow_m3_h[1:])):
            raise ValueError('Pump-curve flow points must be strictly increasing')
        for values in (self.npsh_required_m,self.efficiency):
            if values is not None and len(values)!=n:raise ValueError('Pump-curve optional arrays must match flow points')
        if self.npsh_required_m is not None and any(x<0 for x in self.npsh_required_m):
            raise ValueError('NPSHr cannot be negative')
        if self.efficiency is not None and any(not 0<x<=1 for x in self.efficiency):
            raise ValueError('Pump efficiencies must be fractions in (0,1]')
        return self


class PumpBasis(Contract):
    storage_temperature_K: float = Field(default=293.15,ge=273.16,le=350)
    storage_pressure_Pa: float = Field(default=101325.,gt=0)
    storage_liquid_level_above_pump_m: float = Field(default=2.)
    suction_length_m: float = Field(default=5.,ge=0)
    discharge_cold_length_m: float = Field(default=20.,ge=0)
    heated_riser_extra_length_m: float = Field(default=0.,ge=0)
    suction_inner_diameter_m: float | None = Field(default=None,gt=0)
    discharge_inner_diameter_m: float | None = Field(default=None,gt=0)
    hot_feed_inner_diameter_m: float | None = Field(default=None,gt=0)
    suction_velocity_limit_m_s: float = Field(default=.8,gt=0)
    discharge_velocity_limit_m_s: float = Field(default=1.5,gt=0)
    roughness_m: float = Field(default=4.5e-5,ge=0)
    suction_minor_K: float = Field(default=2.,ge=0)
    discharge_minor_K: float = Field(default=8.,ge=0)
    hot_riser_minor_K: float = Field(default=2.,ge=0)
    heater_pressure_drop_Pa: float = Field(default=20000.,ge=0)
    efficiency: float = Field(default=.65,gt=0,le=1)
    motor_margin: float = Field(default=1.2,ge=1,le=2)
    npsh_margin_m: float = Field(default=1.,ge=0)
    npsh_required_m: float | None = Field(default=None,ge=0)
    curves: list[PumpCurve] = Field(default_factory=list,max_length=100)


class EquipmentBasis(Contract):
    """Explicit preliminary design assumptions, not measured/vendor properties.

    Values below are a transparent teaching policy when the Agent proposes them.
    Native transport and water/steam properties are calculated, not supplied here.
    """
    tray_spacing_m: float = Field(default=.45, ge=.3, le=1.)
    tray_type: Literal['sieve','F1_valve'] = 'F1_valve'
    f1: F1ValveBasis = Field(default_factory=F1ValveBasis)
    pump: PumpBasis = Field(default_factory=PumpBasis)
    weir_height_m: float = Field(default=.05, gt=0, le=.1)
    downcomer_area_fraction: float = Field(default=.12, ge=.08, le=.2)
    hole_area_fraction: float = Field(default=.1, ge=.05, le=.15)
    hole_diameter_mm: float = Field(default=5., ge=3, le=20)
    weeping_coefficient: WeepingCoefficient | None = None
    minimum_load_fraction: float | None = Field(default=None, gt=0, le=1)
    weir_length_diameter_ratio: float = Field(default=.7, ge=.5, le=.8)
    downcomer_clearance_m: float = Field(default=.04, gt=0, le=.1)
    orifice_coefficient: float = Field(default=.65, gt=.3, lt=1.)
    max_flood_fraction: float = Field(default=.7, ge=.4, le=.8)
    top_disengagement_m: float = Field(default=1.5, gt=0)
    bottom_sump_m: float = Field(default=3., gt=0)
    cooling_inlet_K: float = Field(default=298.15, ge=273.16, lt=370)
    cooling_outlet_K: float = Field(default=308.15, gt=273.16, lt=370)
    steam_pressure_Pa: float = Field(default=400000., ge=100000, le=10000000)
    condenser_U_W_m2_K: float = Field(default=500., gt=0)
    reboiler_U_W_m2_K: float = Field(default=1000., gt=0)
    minimum_approach_K: float = Field(default=10., gt=0)
    area_margin: float = Field(default=1.15, ge=1, le=2)
    liquid_nozzle_velocity_m_s: float = Field(default=1., gt=0, le=5)
    vapor_nozzle_velocity_m_s: float = Field(default=20., gt=0, le=50)
    pump_total_head_m: float = Field(default=30., gt=0)
    pump_efficiency: float = Field(default=.65, gt=0, le=1)
    motor_margin: float = Field(default=1.2, ge=1, le=2)
    assumption_origin: Literal['agent_proposed_estimate','user_provided'] = 'agent_proposed_estimate'

    @model_validator(mode='after')
    def geometry_and_utilities(self):
        if self.cooling_outlet_K <= self.cooling_inlet_K:
            raise ValueError('Cooling water outlet must exceed inlet temperature')
        if self.weir_height_m > .15*self.tray_spacing_m:
            raise ValueError('Current Fair capacity method requires weir height <= 15% tray spacing')
        if self.downcomer_clearance_m >= self.weir_height_m:
            raise ValueError('Downcomer clearance must remain below outlet weir for liquid seal')
        return self


class DesignBasis(Contract):
    design_id: str = Field(default_factory=lambda: str(uuid4()))
    process_goal: str = "preliminary_binary_distillation"
    components: list[Component] = Field(default_factory=list)
    feed: Feed = Field(default_factory=Feed)
    target: Target = Field(default_factory=Target)
    design_level: Literal["feasibility", "preliminary_process", "preliminary_equipment"] = "preliminary_process"
    design_mode: Literal["autonomous", "specified"] = "autonomous"
    origin_tags: dict[str, Literal["provided", "source_reported", "retrieved_verified", "calculated",
                                 "estimated", "assumed", "unresolved"]] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    thermodynamic_model: str | None = None
    column: Column = Field(default_factory=Column)
    equipment: EquipmentBasis | None = None


class Reason(Contract):
    code: str
    explanation: str


class DecisionRecord(Contract):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    gate: str = Field(pattern=r"^G[0-9]$")
    question: str
    candidate_options: list[str]
    selected_option: str | None = None
    evidence_ids: list[str]
    assumptions: list[str]
    reasons: list[Reason]
    status: Literal["proposed", "accepted", "rejected", "needs_input", "blocked"]
    risks: list[str] = Field(default_factory=list)
    downstream_invalidate: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    expert_record_ids: list[str] = Field(default_factory=list)


class EvidenceRecord(Contract):
    evidence_id: str
    type: Literal["input_specification", "property_database", "solver_run", "source_reported"]
    source: str
    sha256: str | None = None
    valid_temperature_K: list[float] | None = None


class ToolResult(Contract):
    status: Literal["success", "needs_input", "unsupported", "failed"]
    tool_name: str
    run_id: str
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    data: dict[str, Any] = Field(default_factory=dict,json_schema_extra={"additionalProperties":True})
    units: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict,json_schema_extra={"additionalProperties":True})
    errors: list[Reason] = Field(default_factory=list)
    source_or_run: str
    convergence: dict[str, Any] = Field(default_factory=dict,json_schema_extra={"additionalProperties":True})
    validation: dict[str, Any] = Field(default_factory=dict,json_schema_extra={"additionalProperties":True})
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None


class GateState(Contract):
    gate: str
    status: Literal["not_started", "ready", "running", "passed", "failed", "blocked", "needs_input", "not_applicable"] = "not_started"
    artifact_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class ParameterSet(Contract):
    parameter_set_id: str
    model: str
    component_order: list[str]
    sources: list[EvidenceRecord]
    correlations: list[dict[str, Any]]
    valid_temperature_K: list[float]
    convention: str


class ExpertSkillRecord(Contract):
    record_id: str = Field(default_factory=lambda: str(uuid4()))
    source_run_id: str
    skill_id: str
    skill_version: str
    skill_sha256: str
    title: str
    owner: str
    gate: str
    tool_name: str
    selected_by: Literal['expert_rules','deepseek','qwen','counterevidence_rule']
    hypothesis: str
    procedure: str = ''
    criteria: list[str]
    input_facts: dict[str, Any] = Field(default_factory=dict)
    model_options: list[dict[str, Any]] = Field(default_factory=list)
    evidence_before: list[str] = Field(default_factory=list)
    evidence_after: list[str] = Field(default_factory=list)
    artifact_id: str
    observations: dict[str, Any] = Field(default_factory=dict)
    conclusion: Literal['admitted_for_test','supported_conditionally','refuted','needs_input','blocked']
    next_action: str
    action_status: Literal['observation_only','constraint_applied','recommendation_only'] = 'observation_only'
    limitations: list[str] = Field(default_factory=list)
    reused: bool = False


class DesignState(Contract):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    revision: int = 1
    parent_run_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    basis: DesignBasis
    intent: str = "PROCESS_DESIGN"
    status: Literal["running", "needs_input", "blocked", "partial_design", "failed", "thermodynamic_calculation_complete"] = "running"
    gates: dict[str, GateState] = Field(default_factory=lambda: {f"G{i}": GateState(gate=f"G{i}") for i in range(10)})
    artifacts: dict[str, ToolResult] = Field(default_factory=dict)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    invalidated_gates: list[str] = Field(default_factory=list)
    reused_artifact_ids: list[str] = Field(default_factory=list)
    report_markdown: str = ""
    original_message: str = ""
    provider: str = "deterministic"
    llm_calls: int = 0
    tool_calls: int = 0
    provider_events: list[dict[str, Any]] = Field(default_factory=list)
    design_preferences: dict[str, str] = Field(default_factory=dict)
    expert_records: list[ExpertSkillRecord] = Field(default_factory=list)
    expert_knowledge_hash: str = ''
    rejected_planner_proposals: list[dict[str, Any]] = Field(default_factory=list)


class PlannerChoice(Contract):
    gate: str
    tool_name: str
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    candidate_id: str | None = None
    skill_id: str | None = None
