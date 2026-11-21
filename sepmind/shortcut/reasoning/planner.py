"""A reproducible, cost-aware verification policy over the existing DWSIM tools.

This is a bounded hypothesis-testing prototype, not a calibrated information-gain
estimator, thermodynamic proof, global optimizer, or human-validated knowledge base.
"""

import math

from pydantic import Field
from typing import Literal

from ..utils.data_schemas import Contract, DesignHypothesis, HypothesisUpdate, VerificationAction
from sepmind.simulation.phase_screening import review_binary_vle
from .evidence import basis_fingerprint, request_fingerprint


class VerificationPolicy(Contract):
    selection: Literal["value_per_cost", "first_available"] = "value_per_cost"
    impact_weight: float = Field(default=1.0, gt=0)
    diagnostic_weight: float = Field(default=0.5, ge=0)
    vle_fixed_cost: float = Field(default=1.0, gt=0)
    vle_point_cost: float = Field(default=0.05, ge=0)
    shortcut_cost: float = Field(default=2.0, gt=0)
    max_cost_units: float = Field(default=20.0, gt=0)
    max_refinements: int = Field(default=2, ge=0, le=5)
    max_replays: int = Field(default=1, ge=0, le=2)
    max_grid_points: int = Field(default=81, ge=20, le=161)
    marginal_relative_volatility: float = Field(default=1.2, gt=1)


class HypothesisPlanner:
    def __init__(self, policy=None):
        self.policy = policy if isinstance(policy, VerificationPolicy) else VerificationPolicy(**(policy or {}))
        self.stop_reason = ""
        self.budget_limited = False

    def initialize(self, state):
        definitions = [
            ("phase_boundary", "A sampled phase boundary may obstruct ordinary-distillation initialization.", True),
            ("light_key_enrichment", "The nominated light key is enriched in sampled equilibrium vapor.", True),
            ("reflux_stage_relief", "A local reflux increase reduces estimated stage demand.", True),
            ("failure_reproducibility", "The same registered calculation fails again under identical inputs.", True),
            ("property_basis_validity", "The selected thermodynamic parameters are applicable to this system.", False),
        ]
        state.hypotheses = [DesignHypothesis(
            hypothesis_id=identifier, statement=statement, testable_with_current_tools=testable,
            basis_fingerprint=basis_fingerprint(state.task),
            scope="Current task and property model; finite samples/local comparisons only. "
                  + ("" if testable else "External property data or expert validation required."))
            for identifier, statement, testable in definitions]
        state.event("design", "hypotheses_initialized", hypotheses=[h.model_dump() for h in state.hypotheses])

    def _update(self, state, identifier, status, refs, observation):
        hypothesis = next(h for h in state.hypotheses if h.hypothesis_id == identifier)
        update = HypothesisUpdate(hypothesis_id=identifier, previous_status=hypothesis.status,
                                  status=status, evidence_ids=refs, observation=observation)
        hypothesis.status = status
        hypothesis.evidence_ids = list(dict.fromkeys(hypothesis.evidence_ids + refs))
        state.hypothesis_updates.append(update)
        state.event("review", "hypothesis_update", **update.model_dump())

    def observe(self, state, evidence):
        eligible = state.eligible_evidence()
        if evidence.evidence_id not in {e.evidence_id for e in eligible}:
            raise ValueError("Cannot update hypotheses using inapplicable evidence.")
        prior_same = [e for e in eligible if e.evidence_id != evidence.evidence_id
                      and request_fingerprint(e) == request_fingerprint(evidence)]
        failures = [e for e in prior_same if e.status == "failed"]
        if failures:
            self._update(state, "failure_reproducibility",
                         "supported" if evidence.status == "failed" else "counterevidence",
                         [failures[-1].evidence_id, evidence.evidence_id],
                         "Identical replay " + ("failed again; root cause remains unknown."
                                                if evidence.status == "failed"
                                                else "succeeded; this does not identify the earlier failure's cause."))
        if evidence.status == "failed":
            if not failures:
                self._update(state, "failure_reproducibility", "untested", [evidence.evidence_id],
                             "A failed calculation alone does not distinguish numerical, model or infrastructure causes.")
            return
        if evidence.tool == "binary_vle":
            observation = review_binary_vle(evidence.record)["observation"]
            boundary = bool(observation["crossing_intervals"] or observation["near_diagonal_samples"])
            low, high = observation["sampled_y_minus_x_range"]
            self._update(state, "phase_boundary", "supported" if boundary else "counterevidence",
                         [evidence.evidence_id], "Boundary signal detected on this grid; not an azeotrope proof."
                         if boundary else "No boundary signal on this grid; not a global no-azeotrope proof.")
            self._update(state, "light_key_enrichment", "supported" if low > 0 else
                         "counterevidence" if high <= 0 else "inconclusive", [evidence.evidence_id],
                         f"Sampled vapor-minus-liquid light-key fractions range from {low:.6g} to {high:.6g}.")
        else:
            others = [e for e in eligible if e.tool == evidence.tool and e.status == "ok"
                      and e.evidence_id != evidence.evidence_id
                      and abs(e.record["outputs"]["reflux_ratio"] - evidence.record["outputs"]["reflux_ratio"]) > 1e-9]
            if others:
                previous = others[-1]
                a, b = sorted([previous, evidence], key=lambda e: e.record["outputs"]["reflux_ratio"])
                reduced = b.record["outputs"]["stages_estimate"] < a.record["outputs"]["stages_estimate"] - 1e-9
                self._update(state, "reflux_stage_relief", "supported" if reduced else "counterevidence",
                             [a.evidence_id, b.evidence_id],
                             "Higher reflux " + ("reduced" if reduced else "did not reduce")
                             + " stage demand in this local comparison; no global monotonicity is established.")

    def _action(self, state, kind, tool, hypotheses, refs, impact, diagnostic, rationale, reflux=None, grid=None):
        cost = (self.policy.vle_fixed_cost + self.policy.vle_point_cost * len(grid)
                if tool == "binary_vle" else self.policy.shortcut_cost)
        score = (self.policy.impact_weight * impact + self.policy.diagnostic_weight * diagnostic) / cost
        return VerificationAction(
            action_id=f"v{len(state.verification_decisions) + 1}_{kind}_{reflux if reflux else len(grid or [])}",
            kind=kind, tool=tool, hypothesis_ids=hypotheses, evidence_ids=list(dict.fromkeys(refs)),
            reflux_ratio=reflux, grid=grid, expected_decision_impact=impact, diagnostic_value=diagnostic,
            estimated_cost_units=cost, score=score, rationale=rationale)

    def options(self, state):
        self.stop_reason, self.budget_limited = "", False
        options = self._options(state)
        affordable = [a for a in options
                      if state.estimated_cost_spent + a.estimated_cost_units <= self.policy.max_cost_units + 1e-9]
        if options and not affordable:
            self.stop_reason, self.budget_limited = "Estimated verification-cost budget exhausted.", True
        if self.policy.selection == "value_per_cost":
            affordable.sort(key=lambda a: -a.score)
        return affordable

    def _optional_phase_check(self, state, vle, evidence):
        """A competing diagnostic action when enrichment is positive but weak.

        Relative volatility is calculated from the sampled compositions, not supplied
        by the LLM. The threshold is a declared heuristic for additional investigation.
        """
        count = sum(e.tool == "binary_vle" and e.status == "ok" for e in evidence)
        if count > self.policy.max_refinements:
            return []
        points = vle.record["points"]
        xs = [p["x"][0] for p in points]
        marginal = set()
        for point in points:
            x, y = point["x"][0], point["y"][0]
            if 0 < y < 1:
                alpha = (y / (1 - y)) / (x / (1 - x))
                if 1 < alpha < self.policy.marginal_relative_volatility:
                    marginal.add(x)
        midpoints = [(a + b) / 2 for a, b in zip(xs, xs[1:]) if a in marginal or b in marginal]
        room = self.policy.max_grid_points - len(xs)
        grid = sorted(set(xs + midpoints[:max(0, room)]))
        if len(grid) == len(xs):
            return []
        return [self._action(state, "refine_vle", "binary_vle", ["phase_boundary", "light_key_enrichment"],
                [vle.evidence_id], 1.0, 1.0,
                "Weak sampled relative volatility: compare a targeted phase check with immediate candidate evaluation. "
                "The diagnostic priority is a heuristic, not a probability of hidden boundaries.", grid=grid)]

    def _options(self, state):
        from ..agents.process_simulation_agent import initial_grid
        evidence = state.eligible_evidence()
        latest = evidence[-1] if evidence else None
        if latest and latest.status == "failed":
            same = [e for e in evidence if request_fingerprint(e) == request_fingerprint(latest)]
            if (latest.record.get("failure_kind") == "solver_error"
                    and len(same) <= self.policy.max_replays):
                request = latest.record["request"]
                return [self._action(state, "replay_failed_call", latest.tool, ["failure_reproducibility"],
                        [latest.evidence_id] + latest.depends_on, 0.7, 1.0,
                        "Replay identical inputs once to test reproducibility, without claiming a root cause.",
                        reflux=request.get("reflux_ratio"), grid=request.get("liquid_mole_fractions"))]
            self.stop_reason = "Failed evidence cannot be repaired by the registered bounded replay policy; cause unresolved."
            return []
        vle = state.latest("binary_vle")
        if vle is None:
            return [self._action(state, "screen_vle", "binary_vle", ["phase_boundary", "light_key_enrichment"],
                    [], 1.0, 1.0, "Establish sampled phase behavior before shortcut initialization.",
                    grid=list(initial_grid(state.task)))]
        screen = review_binary_vle(vle.record)
        xs = [p["x"][0] for p in vle.record["points"]]
        boundary = screen["decision"] == "investigate_separation_boundary"
        coarse = max(b - a for a, b in zip(xs, xs[1:])) > 0.100001
        if boundary or coarse:
            count = sum(e.tool == "binary_vle" and e.status == "ok" for e in evidence)
            if count <= self.policy.max_refinements:
                crossings = screen["observation"]["crossing_intervals"]
                near = screen["observation"]["near_diagonal_samples"]
                midpoints = [(a + b) / 2 for a, b in zip(xs, xs[1:])
                             if b - a > 0.100001 or [a, b] in crossings or a in near or b in near]
                room = self.policy.max_grid_points - len(xs)
                grid = sorted(set(xs + midpoints[:max(0, room)]))
                if len(grid) > len(xs):
                    return [self._action(state, "refine_vle", "binary_vle", ["phase_boundary", "light_key_enrichment"],
                            [vle.evidence_id], 1.0, 1.0,
                            "Refine only crossing, near-diagonal or coarse intervals before committing to a route.", grid=grid)]
            self.stop_reason = "Sampled phase boundary/resolution remains unresolved; alternative routes require additional tools."
            return []
        if screen["observation"]["sampled_y_minus_x_range"][0] <= 0:
            self.stop_reason = "The nominated light key is not enriched in all sampled vapor points."
            return []
        shortcuts = [e for e in evidence if e.tool == "shortcut_distillation" and e.status == "ok"]
        optional_phase_check = self._optional_phase_check(state, vle, evidence)
        if not shortcuts:
            return [self._action(state, "test_reflux", "shortcut_distillation", ["reflux_stage_relief"],
                    [vle.evidence_id], 1.0, 0.6, "Evaluate the declared initial candidate under the sampled phase basis.",
                    reflux=state.task.initial_reflux_ratio)] + optional_phase_check
        current = shortcuts[-1]
        o, task = current.record["outputs"], state.task
        stage_bad = task.max_stages is not None and math.ceil(o["stages_estimate"]) > task.max_stages
        duty_bad = task.max_reboiler_duty_kw is not None and o["reboiler_duty_kw"] > task.max_reboiler_duty_kw
        if not stage_bad and not duty_bad:
            self.stop_reason = "A conditional shortcut candidate satisfies the numerical gates."
            return []
        tested = [e.record["outputs"]["reflux_ratio"] for e in shortcuts]
        suggestions = []
        # Generate alternatives in a fixed order; value_per_cost then ranks them.
        if stage_bad:
            suggestions += [(o["reflux_ratio"] * 1.5, 0.75), (o["reflux_ratio"] * 1.25, 0.9)]
        if duty_bad:
            suggestions += [(o["reflux_ratio"] / 1.5, 0.75), (o["reflux_ratio"] / 1.25, 0.9)]
        stage_lower = [e.record["outputs"]["reflux_ratio"] for e in shortcuts
                       if task.max_stages is not None and math.ceil(e.record["outputs"]["stages_estimate"]) > task.max_stages]
        duty_upper = [e.record["outputs"]["reflux_ratio"] for e in shortcuts
                      if task.max_reboiler_duty_kw is not None
                      and e.record["outputs"]["reboiler_duty_kw"] > task.max_reboiler_duty_kw]
        if stage_lower and duty_upper and max(stage_lower) < min(duty_upper):
            suggestions.append(((max(stage_lower) + min(duty_upper)) / 2, 1.0))
        actions = []
        for ratio, impact in suggestions:
            if (ratio > o["minimum_reflux_ratio"] * 1.001 and ratio <= task.reflux_ratio_limit
                    and all(abs(ratio - r) > 1e-8 for r in tested)
                    and all(abs(ratio - a.reflux_ratio) > 1e-8 for a in actions)):
                actions.append(self._action(state, "test_reflux", "shortcut_distillation", ["reflux_stage_relief"],
                               [vle.evidence_id, current.evidence_id], impact, 0.8,
                               "Test a bounded local reflux alternative against BOTH stage and duty limits; "
                               "priority is heuristic and does not assert an optimum.", reflux=ratio))
        if not actions:
            self.stop_reason = "No untested bounded reflux alternative is available; feasibility remains unresolved."
        return actions + optional_phase_check
