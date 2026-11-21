"""Simulation expert: plan registered tools, execute, and preserve evidence."""

from dataclasses import asdict
import json
import math
from uuid import uuid4

from .. import prompts
from sepmind.simulation.dwsim import BinaryVLERequest, ShortcutDistillationRequest
from ..llm import AgentContractError
from ..utils.data_schemas import Evidence, ExecutionPlan
from .base import SpecialistAgent
from ..prompts.hypothesis_prompts import ACTIVE_SIMULATION
from ..reasoning.evidence import basis_fingerprint


def shortcut_request(task, reflux):
    return ShortcutDistillationRequest(
        components=task.components, property_package=task.property_package,
        pressure_pa=task.pressure_pa, feed_molar_flow_mol_s=task.feed_molar_flow_mol_s,
        feed_light_fraction=task.feed_light_fraction, feed_state=task.feed_state,
        distillate_light_purity=task.distillate_light_purity,
        light_recovery=task.light_recovery, reflux_ratio=reflux)


def initial_grid(task):
    split = shortcut_request(task, task.initial_reflux_ratio)
    return tuple(sorted(set([0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99,
                             task.feed_light_fraction, task.distillate_light_purity, split.bottoms_light_fraction])))


def validate_record(record, request, tool):
    """Check engine provenance and numeric fields again before sharing with agents."""
    if (record.get("status") != "ok" or record.get("backend") != "DWSIM"
            or not record.get("evidence_id") or not record.get("version")):
        raise ValueError("Engine did not provide successful DWSIM evidence and provenance.")
    canonical = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    if canonical(record.get("request")) != canonical(asdict(request)):
        raise ValueError("Engine evidence does not match the requested inputs.")
    if tool == "binary_vle":
        points = record.get("points", [])
        if len(points) != len(request.liquid_mole_fractions):
            raise ValueError("Incomplete VLE grid.")
        for expected_x, point in zip(request.liquid_mole_fractions, points):
            x, y = point["x"], point["y"]
            if (len(x) != 2 or len(y) != 2
                    or not all(math.isfinite(v) and 0 <= v <= 1 for v in x + y)
                    or abs(sum(x) - 1) > 1e-6 or abs(sum(y) - 1) > 1e-6
                    or abs(x[0] - expected_x) > 1e-6
                    or not math.isfinite(point["temperature_k"]) or point["temperature_k"] <= 0):
                raise ValueError("Invalid binary VLE result.")
        if not record.get("checks", {}).get("all_points_solved"):
            raise ValueError("VLE solver checks did not pass.")
    else:
        o = record["outputs"]
        for name in ("stages_estimate", "minimum_stages", "minimum_reflux_ratio", "reflux_ratio",
                     "distillate_light_purity", "light_recovery", "reboiler_duty_kw", "condenser_duty_kw",
                     "distillate_flow_mol_s", "bottoms_flow_mol_s"):
            if not math.isfinite(o[name]):
                raise ValueError(f"Nonfinite shortcut result: {name}")
        if (o["minimum_stages"] <= 0 or o["stages_estimate"] < o["minimum_stages"]
                or o["minimum_reflux_ratio"] < 0
                or request.reflux_ratio <= o["minimum_reflux_ratio"]
                or abs(o["reflux_ratio"] - request.reflux_ratio) > 1e-9):
            raise ValueError("Invalid shortcut stages or reflux result.")
        d, b, f = o["distillate_flow_mol_s"], o["bottoms_flow_mol_s"], request.feed_molar_flow_mol_s
        xd, xb = o["distillate_composition"], o["bottoms_composition"]
        if (len(xd) != 2 or len(xb) != 2 or min(d, b) <= 0
                or not all(math.isfinite(v) and 0 <= v <= 1 for v in xd + xb)
                or max(abs(sum(xd) - 1), abs(sum(xb) - 1)) > 1e-6):
            raise ValueError("Invalid shortcut product compositions or flows.")
        for i, z in enumerate((request.feed_light_fraction, 1 - request.feed_light_fraction)):
            if abs(f * z - d * xd[i] - b * xb[i]) / f > 1e-6:
                raise ValueError("Shortcut component balance failed.")
        if (abs(xd[0] - o["distillate_light_purity"]) > 1e-9
                or abs(d * xd[0] / (f * request.feed_light_fraction) - o["light_recovery"]) > 1e-9):
            raise ValueError("Shortcut reported targets disagree with product streams.")
        if not record.get("checks", {}).get("flowsheet_solved"):
            raise ValueError("Shortcut solver checks did not pass.")


class ProcessSimulationAgent(SpecialistAgent):
    role = "simulation"

    def __init__(self, tools=None, backend=None, use_few_shots=True, example_library=None):
        super().__init__(backend, use_few_shots, example_library)
        self.tools = tools

    def execute(self, state, proposal, candidate=None, verification=None):
        expected = "binary_vle" if proposal.action == "screen_vle" else "shortcut_distillation"
        context = state.context() | {"design_proposal": proposal.model_dump()}
        if verification is not None:
            context["verification_action"] = verification.model_dump()
            if verification.tool != expected:
                raise AgentContractError("Verification tool does not match the execution proposal.")
        plan = (self._request(ACTIVE_SIMULATION if verification else prompts.SIMULATION, ExecutionPlan, context, state,
                              "active_verification" if verification else
                              "vle_execution" if expected == "binary_vle" else "shortcut_execution")
                if self.backend is not None else ExecutionPlan(
                    tool=expected, rationale="Execute the registered numerical protocol for this proposal.",
                    evidence_ids=proposal.evidence_ids))
        if plan.tool != expected:
            raise AgentContractError("Simulation tool does not match the approved design action.")
        if not set(proposal.evidence_ids).issubset(plan.evidence_ids):
            raise AgentContractError("Execution plan must retain the design proposal's evidence references.")
        state.event("simulation", "execution_plan", **plan.model_dump())
        if expected == "binary_vle":
            last = state.reviews[-1] if state.reviews else None
            grid = (tuple(verification.grid) if verification else
                    tuple(last.suggested_grid) if last and last.suggested_grid else initial_grid(state.task))
            request = BinaryVLERequest(state.task.components, state.task.property_package,
                                       state.task.pressure_pa, grid)
        else:
            request = shortcut_request(state.task, candidate.reflux_ratio)
        state.tool_calls += 1
        try:
            record = getattr(self.tools, expected)(request)
        except Exception as exc:
            return self._failed(state, request, expected, candidate, proposal, exc, "solver_error")
        try:
            validate_record(record, request, expected)
            if record["evidence_id"] in {e.evidence_id for e in state.evidence}:
                raise ValueError("Reused evidence ID is not accepted as a fresh calculation.")
            return Evidence(evidence_id=record["evidence_id"], task_revision=state.task_revision,
                            candidate_id=candidate.candidate_id if candidate else None,
                            tool=expected, status="ok", record=record,
                            basis_fingerprint=basis_fingerprint(state.task, expected),
                            depends_on=list(proposal.evidence_ids))
        except Exception as exc:
            return self._failed(state, request, expected, candidate, proposal, exc, "evidence_validation_failed")

    @staticmethod
    def _failed(state, request, tool, candidate, proposal, exc, kind):
        return Evidence(evidence_id=str(uuid4()), task_revision=state.task_revision,
                        candidate_id=candidate.candidate_id if candidate else None,
                        tool=tool, status="failed", record={"status": "failed",
                        "request": asdict(request), "error": str(exc), "failure_kind": kind},
                        basis_fingerprint=basis_fingerprint(state.task, tool),
                        depends_on=list(proposal.evidence_ids))
