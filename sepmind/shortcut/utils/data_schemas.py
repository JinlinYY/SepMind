"""Shared task schemas, handoffs, and engineering state for the agent team."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now():
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DesignTask(Contract):
    """All fractions are mole fractions. Component 0 is the nominated light key.

    Optional fields remain missing until explicitly supplied. Search controls are
    declared separately from process specifications, rather than inferred by LLM.
    """

    components: tuple[str, str] | None = None
    property_package: str | None = None
    property_basis_note: str | None = None
    pressure_pa: float | None = Field(default=None, gt=0)
    feed_molar_flow_mol_s: float | None = Field(default=None, gt=0)
    feed_light_fraction: float | None = Field(default=None, gt=0, lt=1)
    feed_state: Literal["saturated_liquid"] | None = None
    distillate_light_purity: float | None = Field(default=None, gt=0, lt=1)
    light_recovery: float | None = Field(default=None, gt=0, lt=1)
    max_stages: int | None = Field(default=None, ge=1, strict=True)
    max_reboiler_duty_kw: float | None = Field(default=None, gt=0)
    initial_reflux_ratio: float = Field(default=2.5, gt=0)
    reflux_ratio_limit: float = Field(default=20.0, gt=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.components and (any(not c.strip() for c in self.components)
                                or len(set(self.components)) != 2):
            raise ValueError("Two distinct nonempty compound names are required.")
        if (self.feed_light_fraction is not None and self.distillate_light_purity is not None
                and self.distillate_light_purity <= self.feed_light_fraction):
            raise ValueError("Distillate light-key purity must exceed its feed mole fraction.")
        if self.initial_reflux_ratio > self.reflux_ratio_limit:
            raise ValueError("Initial reflux ratio exceeds the declared search limit.")
        return self

    def missing_fields(self):
        required = ("components", "property_package", "property_basis_note", "pressure_pa",
                    "feed_molar_flow_mol_s", "feed_light_fraction", "feed_state",
                    "distillate_light_purity", "light_recovery")
        return [name for name in required if getattr(self, name) is None
                or (isinstance(getattr(self, name), str) and not getattr(self, name).strip())]


class RunLimits(Contract):
    max_rounds: int = Field(default=8, ge=1, le=30)
    max_tool_calls: int = Field(default=6, ge=1, le=20)
    max_llm_calls: int = Field(default=30, ge=1, le=100)


class DesignProposal(Contract):
    action: Literal["screen_vle", "simulate_shortcut", "clarify", "stop"]
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reflux_ratio: float | None = Field(default=None, gt=0)
    questions: list[str] = Field(default_factory=list)


class ExecutionPlan(Contract):
    tool: Literal["binary_vle", "shortcut_distillation"]
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewRecommendation(Contract):
    action: Literal["continue_design", "refine_vle", "revise_design", "accept_preliminary", "stop"]
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Candidate(Contract):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    route: Literal["ordinary_binary_distillation"] = "ordinary_binary_distillation"
    reflux_ratio: float = Field(gt=0)
    rationale: str
    evidence_ids: list[str]


class Evidence(Contract):
    evidence_id: str
    task_revision: int
    candidate_id: str | None = None
    tool: Literal["binary_vle", "shortcut_distillation"]
    status: Literal["ok", "failed"]
    record: dict[str, Any]
    basis_fingerprint: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class Review(Contract):
    evidence_id: str
    action: Literal["continue_design", "refine_vle", "revise_design", "accept_preliminary", "stop"]
    issues: list[str]
    checks: dict[str, Any]
    rationale: str
    suggested_reflux_ratio: float | None = None
    suggested_grid: list[float] | None = None


class AgentEvent(Contract):
    sequence: int
    timestamp: str = Field(default_factory=now)
    role: Literal["coordinator", "design", "simulation", "review"]
    action: str
    details: dict[str, Any] = Field(default_factory=dict)


class DesignState(Contract):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    task_revision: int = 1
    mode: Literal["rules", "llm"]
    strategy: Literal["baseline", "hypothesis"] = "baseline"
    task: DesignTask
    user_message: str = ""
    status: Literal["running", "awaiting_clarification", "preliminary_complete",
                    "needs_engineering_review", "tool_failed", "budget_exhausted", "agent_failed"] = "running"
    questions: list[str] = Field(default_factory=list)
    rounds: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    limits: RunLimits = Field(default_factory=RunLimits)
    candidates: list[Candidate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    hypotheses: list["DesignHypothesis"] = Field(default_factory=list)
    hypothesis_updates: list["HypothesisUpdate"] = Field(default_factory=list)
    verification_decisions: list["VerificationDecision"] = Field(default_factory=list)
    estimated_cost_spent: float = 0.0

    def eligible_evidence(self):
        from ..reasoning.evidence import eligible_evidence
        return eligible_evidence(self)

    def event(self, role, event_action, **details):
        self.events.append(AgentEvent(sequence=len(self.events) + 1, role=role,
                                     action=event_action, details=details))

    def latest(self, tool):
        return next((e for e in reversed(self.eligible_evidence()) if e.tool == tool), None)

    def context(self):
        # No SDK clients or API keys enter the state or agent prompts.
        return {
            "task": self.task.model_dump(), "user_message": self.user_message,
            "missing_fields": self.task.missing_fields(),
            "candidates": [c.model_dump() for c in self.candidates[-2:]],
            "latest_evidence": [e.model_dump() for tool in ("binary_vle", "shortcut_distillation")
                                if (e := self.latest(tool)) is not None],
            "last_review": self.reviews[-1].model_dump() if self.reviews else None,
            "available_evidence_ids": [e.evidence_id for e in self.eligible_evidence()],
            "strategy": self.strategy,
            "hypotheses": [h.model_dump() for h in self.hypotheses],
            "remaining_tool_calls": self.limits.max_tool_calls - self.tool_calls,
        }


class DesignHypothesis(Contract):
    hypothesis_id: str
    statement: str
    status: Literal["untested", "supported", "counterevidence", "inconclusive"] = "untested"
    testable_with_current_tools: bool = True
    evidence_ids: list[str] = Field(default_factory=list)
    basis_fingerprint: str
    scope: str


class HypothesisUpdate(Contract):
    hypothesis_id: str
    previous_status: str
    status: str
    evidence_ids: list[str]
    observation: str


class VerificationAction(Contract):
    action_id: str
    kind: Literal["screen_vle", "refine_vle", "test_reflux", "replay_failed_call"]
    tool: Literal["binary_vle", "shortcut_distillation"]
    hypothesis_ids: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    reflux_ratio: float | None = Field(default=None, gt=0)
    grid: list[float] | None = None
    expected_decision_impact: float = Field(ge=0, le=1)
    diagnostic_value: float = Field(ge=0, le=1)
    estimated_cost_units: float = Field(gt=0)
    score: float = Field(ge=0)
    rationale: str


class VerificationChoice(Contract):
    action_id: str
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationDecision(Contract):
    options: list[VerificationAction]
    selected_action_id: str
    selection_policy: str
    rationale: str
    evidence_id: str | None = None


class VerificationAssessment(Contract):
    action: Literal["continue", "accept_preliminary", "stop"]
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


DesignState.model_rebuild()
