"""Engineering reviewer: independent numeric gates plus optional LLM advice."""

import math

from .. import prompts
from ..llm import AgentContractError
from ..utils.data_schemas import Review, ReviewRecommendation, VerificationAssessment
from ..prompts.hypothesis_prompts import ACTIVE_REVIEW
from sepmind.simulation.phase_screening import review_binary_vle
from .base import SpecialistAgent


class EngineeringReviewAgent(SpecialistAgent):
    role = "review"

    def review_verification(self, state, evidence, verification):
        """Keep physical gates; expose observations, never a prescribed LLM action."""
        numeric = self._checks(state, evidence)
        acceptable = (evidence.status == "ok" and evidence.tool == "shortcut_distillation"
                      and all(numeric.checks.get(k) is True for k in
                              ("specified_split_reproduced", "stage_limit_satisfied", "duty_limit_satisfied")))
        hard_stop = (evidence.record.get("failure_kind") == "evidence_validation_failed"
                     or "nominated_light_key_not_enriched_in_sampled_vapor" in numeric.issues
                     or "specified_split_not_reproduced" in numeric.issues)
        action = "accept_preliminary" if acceptable else "stop" if hard_stop else "continue"
        rationale = ("Conditional shortcut checks pass; rigorous performance and property validation remain outstanding."
                     if acceptable else "Use the hypothesis and experiment policy to investigate these observations.")
        if self.backend is not None:
            context = state.context() | {
                "current_evidence_id": evidence.evidence_id,
                "verification_action": verification.model_dump(),
                "numerical_observations": {"checks": numeric.checks, "issues": numeric.issues},
                "recent_hypothesis_updates": [u.model_dump() for u in state.hypothesis_updates[-3:]],
            }
            assessment = self._request(ACTIVE_REVIEW, VerificationAssessment, context, state, "active_verification")
            if evidence.evidence_id not in assessment.evidence_ids:
                raise AgentContractError("Verification review must cite the current evidence.")
            if assessment.action == "accept_preliminary" and not acceptable:
                raise AgentContractError("Verification reviewer cannot accept failed or incomplete numerical checks.")
            if hard_stop and assessment.action != "stop":
                raise AgentContractError("Verification reviewer cannot bypass an invalid evidence or split check.")
            action, rationale = assessment.action, assessment.rationale
        return Review(evidence_id=evidence.evidence_id,
                      action="continue_design" if action == "continue" else action,
                      issues=numeric.issues, checks=numeric.checks, rationale=rationale)

    def _checks(self, state, evidence):
        if evidence.status == "failed":
            return Review(evidence_id=evidence.evidence_id, action="stop",
                          issues=["calculation_failed_not_proof_of_infeasibility"], checks={"solver_success": False},
                          rationale="Inspect the solver error and input assumptions before another engineering decision.")
        if evidence.tool == "binary_vle":
            screen = review_binary_vle(evidence.record)
            differences = [p["y"][0] - p["x"][0] for p in evidence.record["points"]]
            xs = [p["x"][0] for p in evidence.record["points"]]
            boundary = screen["decision"] == "investigate_separation_boundary"
            coarse = max(b - a for a, b in zip(xs, xs[1:])) > 0.100001
            if boundary or coarse:
                previous = sum(e.tool == "binary_vle" for e in state.evidence)
                grid = sorted(set(xs + [(a + b) / 2 for a, b in zip(xs, xs[1:])]))
                retry = previous < 2 and len(grid) <= 81
                return Review(evidence_id=evidence.evidence_id, action="refine_vle" if retry else "stop",
                              issues=["sampled_phase_boundary_or_resolution_requires_investigation"],
                              checks=screen["observation"], suggested_grid=grid if retry else None,
                              rationale="Refine the VLE evidence once; unresolved boundaries require further engineering validation.")
            if min(differences) <= 0:
                return Review(evidence_id=evidence.evidence_id, action="stop",
                              issues=["nominated_light_key_not_enriched_in_sampled_vapor"], checks=screen["observation"],
                              rationale="Review component order and thermodynamic basis; do not silently swap product requirements.")
            return Review(evidence_id=evidence.evidence_id, action="continue_design", issues=[],
                          checks=screen["observation"],
                          rationale="Sampled VLE supports conditional shortcut initialization; global feasibility remains unverified.")
        o, task = evidence.record["outputs"], state.task
        tolerance = 1e-9
        checks = {
            "specified_split_reproduced": (o["distillate_light_purity"] + tolerance >= task.distillate_light_purity
                                         and o["light_recovery"] + tolerance >= task.light_recovery),
            "stage_limit_satisfied": task.max_stages is None or math.ceil(o["stages_estimate"]) <= task.max_stages,
            "duty_limit_satisfied": task.max_reboiler_duty_kw is None or o["reboiler_duty_kw"] <= task.max_reboiler_duty_kw,
            "comparison_tolerance": tolerance,
            "rigorous_performance_verified": False, "property_parameters_independently_verified": False,
        }
        if not checks["specified_split_reproduced"]:
            return Review(evidence_id=evidence.evidence_id, action="stop", issues=["specified_split_not_reproduced"],
                          checks=checks, rationale="The shortcut result does not reproduce the imposed split; inspect the model.")
        if not checks["duty_limit_satisfied"]:
            return Review(evidence_id=evidence.evidence_id, action="stop", issues=["reboiler_duty_limit_exceeded"],
                          checks=checks, rationale="The current tool policy cannot establish a lower-duty feasible design.")
        if not checks["stage_limit_satisfied"]:
            next_reflux = o["reflux_ratio"] * 1.5
            retry = next_reflux <= task.reflux_ratio_limit
            return Review(evidence_id=evidence.evidence_id, action="revise_design" if retry else "stop",
                          issues=["stage_limit_exceeded"], checks=checks,
                          suggested_reflux_ratio=next_reflux if retry else None,
                          rationale="Test a bounded reflux increase against both stages and duty; no optimum is asserted.")
        return Review(evidence_id=evidence.evidence_id, action="accept_preliminary", issues=[], checks=checks,
                      rationale="Accept this conditional shortcut initialization; rigorous design and property validation remain outstanding.")

    def review(self, state, evidence):
        review = self._checks(state, evidence)
        if self.backend is not None:
            context = state.context() | {"deterministic_checks": review.model_dump(),
                                         "required_action": review.action}
            phase = ("solver_failure" if evidence.status == "failed" else "vle_review"
                     if evidence.tool == "binary_vle" else "stage_review" if "stage_limit_exceeded" in review.issues
                     else "preliminary_review" if review.action == "accept_preliminary" else "constraint_review")
            advice = self._request(prompts.REVIEW, ReviewRecommendation, context, state, phase)
            if evidence.evidence_id not in advice.evidence_ids:
                raise AgentContractError("Review must cite the current calculation evidence.")
            if advice.action not in (review.action, "stop"):
                raise AgentContractError("Review advice conflicts with mandatory engineering checks.")
            review.action = advice.action
            review.rationale = advice.rationale
            if advice.action == "stop" and not review.issues:
                review.issues.append("reviewer_requested_additional_engineering_validation")
        return review
