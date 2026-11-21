"""Design expert: formulate a bounded candidate or ask for missing inputs."""

from .. import prompts
from ..llm import AgentContractError
from ..utils.data_schemas import DesignProposal, VerificationChoice
from ..prompts.hypothesis_prompts import ACTIVE_DESIGN
from .base import SpecialistAgent


class SeparationDesignAgent(SpecialistAgent):
    role = "design"

    def choose_verification(self, state, options):
        """Choose a registered experiment, without editing its numeric arguments."""
        if not options:
            raise AgentContractError("No affordable verification experiment is available.")
        if self.backend is None:
            selected = options[0]
            return selected, selected.rationale
        context = state.context() | {"verification_options": [a.model_dump() for a in options]}
        choice = self._request(ACTIVE_DESIGN, VerificationChoice, context, state, "active_verification")
        selected = next((a for a in options if a.action_id == choice.action_id), None)
        if selected is None:
            raise AgentContractError("Design agent selected an unregistered verification action.")
        if not set(selected.evidence_ids).issubset(choice.evidence_ids):
            raise AgentContractError("Verification choice must retain all experiment evidence references.")
        return selected, choice.rationale

    def propose(self, state):
        missing = state.task.missing_fields()
        if self.backend is not None:
            last = state.reviews[-1] if state.reviews else None
            phase = ("clarification" if missing else "revision" if last and last.action == "revise_design"
                     else "refinement" if last and last.action == "refine_vle"
                     else "shortcut_initialization" if last else "initial_screening")
            proposal = self._request(prompts.DESIGN, DesignProposal, state.context(), state, phase)
        elif missing:
            proposal = DesignProposal(action="clarify", rationale="Required engineering inputs are missing.",
                                      questions=[f"Please specify {field}." for field in missing])
        else:
            last = state.reviews[-1] if state.reviews else None
            evidence = [last.evidence_id] if last else []
            if last is None or last.action == "refine_vle":
                proposal = DesignProposal(action="screen_vle", rationale="Check the nominated light key and sampled separation boundary.",
                                          evidence_ids=evidence)
            else:
                reflux = (last.suggested_reflux_ratio if last.action == "revise_design"
                          else state.task.initial_reflux_ratio)
                proposal = DesignProposal(action="simulate_shortcut", reflux_ratio=reflux,
                                          rationale="Evaluate a bounded shortcut candidate against the design constraints.",
                                          evidence_ids=evidence)
        # LLM advice never fills missing task data or bypasses phase screening.
        if missing and proposal.action != "clarify":
            raise AgentContractError("Design agent must clarify missing required task fields.")
        last = state.reviews[-1] if state.reviews else None
        if proposal.action == "screen_vle" and last is not None:
            if last.action != "refine_vle" or last.evidence_id not in proposal.evidence_ids:
                raise AgentContractError("Another VLE call requires a cited refinement review.")
        if proposal.action == "simulate_shortcut":
            if last is None or last.action not in ("continue_design", "revise_design"):
                raise AgentContractError("Shortcut design requires an approving phase/iteration review.")
            if last.evidence_id not in proposal.evidence_ids:
                raise AgentContractError("Design proposal must cite the preceding review evidence.")
            if proposal.reflux_ratio is None or proposal.reflux_ratio > state.task.reflux_ratio_limit:
                raise AgentContractError("Candidate reflux ratio is missing or outside the search limit.")
            if last.action == "continue_design" and abs(proposal.reflux_ratio - state.task.initial_reflux_ratio) > 1e-9:
                raise AgentContractError("The first candidate must honor the declared initial reflux ratio.")
            if last.action == "revise_design" and state.candidates and proposal.reflux_ratio <= state.candidates[-1].reflux_ratio:
                raise AgentContractError("The requested stage-limit revision needs an increased reflux ratio.")
        if proposal.action == "clarify" and not proposal.questions:
            proposal.questions = [f"Please specify {field}." for field in missing] or [proposal.rationale]
        return proposal
