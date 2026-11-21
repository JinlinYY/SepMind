"""Coordinator for design -> simulation -> independent review -> revision."""

from .engineering_review_agent import EngineeringReviewAgent
from .process_simulation_agent import ProcessSimulationAgent
from .separation_design_agent import SeparationDesignAgent
from ..tools.dwsim import DwsimBackend
from ..llm import AgentContractError, LLMBudgetExceeded
from ..utils.data_schemas import Candidate, DesignProposal, DesignState, DesignTask, RunLimits, VerificationDecision
from ..utils.few_shots import FewShotLibrary
from ..reasoning import HypothesisPlanner, VerificationPolicy


class SeparationOrchestrator:
    """Three specialist roles sharing explicit, revision-scoped engineering state.

    Pass a PHA-compatible backend with generate(prompt) for actual LLM agents.
    backend=None is an explicitly labelled deterministic baseline, not simulated LLM use.
    """

    def __init__(self, tools=None, backend=None, limits=None, on_event=None,
                 use_few_shots=True, few_shots_dir=None, strategy="baseline", verification_policy=None):
        if strategy not in ("baseline", "hypothesis"):
            raise ValueError("strategy must be baseline or hypothesis.")
        self.strategy = strategy
        self.verification_policy = VerificationPolicy.model_validate(verification_policy or {})
        self.tools = tools  # resolve DWSIM lazily, after task clarification
        self.example_library = FewShotLibrary(few_shots_dir)
        self.design_agent = SeparationDesignAgent(backend, use_few_shots, self.example_library)
        self.simulation_agent = ProcessSimulationAgent(tools, backend, use_few_shots, self.example_library)
        self.review_agent = EngineeringReviewAgent(backend, use_few_shots, self.example_library)
        self.mode = "llm" if backend is not None else "rules"
        self.limits = limits if isinstance(limits, RunLimits) else RunLimits(**(limits or {}))
        self.on_event = on_event
        self.state = None
        self.previous_runs = []

    def configure(self, api_key=None, provider="deepseek", model_name=None):
        """Configure the team backend, following the original PHA agent API."""
        from ..llm import make_backend
        backend = make_backend(provider=provider, model_name=model_name, api_key=api_key)
        for agent in (self.design_agent, self.simulation_agent, self.review_agent):
            agent.backend = backend
        self.mode = "llm"
        return self

    def set_agents(self, design_agent, simulation_agent, review_agent):
        """Install independently configured specialists, like PHA.set_agents."""
        if (not isinstance(design_agent, SeparationDesignAgent)
                or not isinstance(simulation_agent, ProcessSimulationAgent)
                or not isinstance(review_agent, EngineeringReviewAgent)):
            raise TypeError("Provide one instance of each chemical specialist class.")
        modes = [a.backend is not None for a in (design_agent, simulation_agent, review_agent)]
        if any(modes) and not all(modes):
            raise ValueError("Configure all three specialist backends, or use rules for all three.")
        self.design_agent, self.simulation_agent, self.review_agent = design_agent, simulation_agent, review_agent
        if simulation_agent.tools is None:
            simulation_agent.tools = self.tools
        self.mode = "llm" if all(modes) else "rules"
        return self

    def get_team_structure(self):
        return {"coordinator": type(self).__name__, "design": type(self.design_agent).__name__,
                "simulation": type(self.simulation_agent).__name__, "review": type(self.review_agent).__name__}

    def reset_conversation(self):
        self.state = None
        self.previous_runs.clear()

    def _emit(self, state, role, event_action, **details):
        state.event(role, event_action, **details)
        if self.on_event:
            # Observers receive a copy, never a reference that can change state.
            self.on_event(state.events[-1].model_dump())

    def run(self, task, message=""):
        task = task if isinstance(task, DesignTask) else DesignTask.model_validate(task)
        revision = self.state.task_revision + 1 if self.state else 1
        prior = self.state
        if prior is not None:
            self.previous_runs.append(self.state.model_copy(deep=True))
        # No old evidence is eligible after a task update, including pressure changes.
        state = DesignState(task=task.model_copy(deep=True), mode=self.mode, strategy=self.strategy, task_revision=revision,
                            user_message=message, limits=self.limits.model_copy(deep=True))
        self.state = state
        self._emit(state, "coordinator", "start", mode=self.mode, strategy=self.strategy, task_revision=revision,
                   scope="binary_shortcut_preliminary_design", team=self.get_team_structure(),
                   few_shots={a.role: a.use_few_shots for a in
                              (self.design_agent, self.simulation_agent, self.review_agent)})
        if prior is not None:
            self._emit(state, "coordinator", "evidence_invalidated", previous_run_id=prior.run_id,
                       evidence_ids=[e.evidence_id for e in prior.evidence],
                       reason="New task revision conservatively invalidates all earlier evidence and dependent hypotheses.")
        planner = HypothesisPlanner(self.verification_policy) if self.strategy == "hypothesis" else None
        if planner and not task.missing_fields():
            planner.initialize(state)
            self._emit(state, "coordinator", "verification_policy", **self.verification_policy.model_dump(),
                       cost_unit_meaning="Declared relative cost proxies, not elapsed seconds or calibrated information gain.")
        try:
            for _ in range(state.limits.max_rounds):
                state.rounds += 1
                verification = None
                if planner and not task.missing_fields():
                    if state.tool_calls >= state.limits.max_tool_calls:
                        state.status = "budget_exhausted"
                        break
                    options = planner.options(state)
                    if not options:
                        state.status = ("budget_exhausted" if planner.budget_limited else
                                        "tool_failed" if state.evidence and state.evidence[-1].status == "failed"
                                        else "needs_engineering_review")
                        self._emit(state, "coordinator", "verification_stopped", reason=planner.stop_reason)
                        break
                    verification, rationale = self.design_agent.choose_verification(state, options)
                    decision = VerificationDecision(options=options, selected_action_id=verification.action_id,
                                                    selection_policy=self.verification_policy.selection, rationale=rationale)
                    state.verification_decisions.append(decision)
                    self._emit(state, "design", "verification_selected", **decision.model_dump())
                    proposal = DesignProposal(
                        action="screen_vle" if verification.tool == "binary_vle" else "simulate_shortcut",
                        reflux_ratio=verification.reflux_ratio, evidence_ids=verification.evidence_ids, rationale=rationale)
                else:
                    proposal = self.design_agent.propose(state)
                self._emit(state, "design", "proposal", **proposal.model_dump())
                if proposal.action == "clarify":
                    state.status = "awaiting_clarification"
                    state.questions = proposal.questions
                    break
                if proposal.action == "stop":
                    state.status = "needs_engineering_review"
                    break
                if state.tool_calls >= state.limits.max_tool_calls:
                    state.status = "budget_exhausted"
                    break
                candidate = None
                if proposal.action == "simulate_shortcut":
                    candidate = Candidate(reflux_ratio=proposal.reflux_ratio, rationale=proposal.rationale,
                                          evidence_ids=proposal.evidence_ids)
                    if (any(abs(c.reflux_ratio - candidate.reflux_ratio) < 1e-12 for c in state.candidates)
                            and not (verification and verification.kind == "replay_failed_call")):
                        raise AgentContractError("Repeated candidate without a numerical change.")
                    state.candidates.append(candidate)
                if self.simulation_agent.tools is None:
                    self.simulation_agent.tools = DwsimBackend()
                evidence = self.simulation_agent.execute(state, proposal, candidate, verification=verification)
                state.evidence.append(evidence)
                if verification:
                    state.estimated_cost_spent += verification.estimated_cost_units
                    state.verification_decisions[-1].evidence_id = evidence.evidence_id
                    planner.observe(state, evidence)
                self._emit(state, "simulation", "tool_result", tool=evidence.tool,
                           evidence_id=evidence.evidence_id, status=evidence.status,
                           candidate_id=evidence.candidate_id)
                review = (self.review_agent.review_verification(state, evidence, verification) if verification
                          else self.review_agent.review(state, evidence))
                state.reviews.append(review)
                self._emit(state, "review", "engineering_review", **review.model_dump())
                if review.action == "accept_preliminary":
                    state.status = "preliminary_complete"
                    break
                if review.action == "stop":
                    state.status = "tool_failed" if evidence.status == "failed" else "needs_engineering_review"
                    break
                self._emit(state, "coordinator", "route_revision", next_action=review.action,
                           evidence_id=review.evidence_id)
            else:
                state.status = "budget_exhausted"
        except LLMBudgetExceeded as exc:
            state.status = "budget_exhausted"
            self._emit(state, "coordinator", "llm_budget_exhausted", reason=str(exc))
        except Exception as exc:
            state.status = "agent_failed"
            self._emit(state, "coordinator", "execution_error", error_type=type(exc).__name__, reason=str(exc))
        self._emit(state, "coordinator", "finish", status=state.status,
                   rounds=state.rounds, tool_calls=state.tool_calls, llm_calls=state.llm_calls)
        return state

    def respond(self, message, task_updates=None):
        """Resume with explicit structured updates; preserve other user inputs.

        message is discussion context, not an implicit source of numerical updates.
        Changes must be passed through task_updates so they can be validated.
        """
        task = self.state.task.model_dump() if self.state else {}
        task.update(task_updates or {})
        state = self.run(task, message=message)
        from ..utils.reporting import render_report
        return render_report(state)
