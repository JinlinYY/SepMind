"""Evidence-linked report serialization and rendering."""


def report_data(state):
    last = state.latest("shortcut_distillation")
    numerical = last.record["outputs"] if last is not None and last.status == "ok" else None
    limitations = [
        "This run supports binary saturated-liquid shortcut initialization only.",
        "The property-basis note is supplied context, not independent parameter validation.",
        "No global no-azeotrope proof or rigorous product-performance verification is claimed.",
        "Reflux revision is a bounded heuristic; no global economic or energy optimum is claimed.",
    ]
    for evidence in state.evidence:
        limitations.extend(f"[{evidence.tool}] {limit}" for limit in evidence.record.get("limitations", []))
    if state.strategy == "hypothesis":
        limitations += [
            "Verification priorities and costs are declared heuristics, not calibrated probabilities or information gain.",
            "Identical replay tests failure reproducibility only; no root-cause diagnosis is established.",
            "Hypotheses are authored, scoped test statements; human-expert validation remains outstanding.",
        ]
    responses = [e.details for e in state.events if e.action == "llm_response"]
    examples = {item["example_id"]: item for event in state.events
                if event.action == "few_shot_context" for item in event.details.get("examples", [])}
    return {
        "status": state.status, "mode": state.mode, "strategy": state.strategy, "run_id": state.run_id,
        "task_revision": state.task_revision, "scope": "conditional_shortcut_initialization",
        "questions": state.questions,
        "task": state.task.model_dump(),
        "numerical_results": numerical,
        "numerical_evidence_id": last.evidence_id if numerical else None,
        "recommended_candidate_id": last.candidate_id if numerical and state.status == "preliminary_complete" else None,
        "issues": state.reviews[-1].issues if state.reviews else [],
        "limitations": list(dict.fromkeys(limitations)),
        "llm_providers": sorted({r["provider"] for r in responses}),
        "served_models": sorted({r["served_model"] for r in responses if r.get("served_model")}),
        "few_shot_examples": list(examples.values()),
        "hypotheses": [h.model_dump() for h in state.hypotheses],
        "hypothesis_updates": [u.model_dump() for u in state.hypothesis_updates],
        "verification_decisions": [d.model_dump() for d in state.verification_decisions],
        "evidence_dependencies": [{"evidence_id": e.evidence_id, "depends_on": e.depends_on,
                                   "basis_fingerprint": e.basis_fingerprint}
                                  for e in state.eligible_evidence()],
        "verification_stop_reasons": [e.details["reason"] for e in state.events
                                      if e.action == "verification_stopped"],
        "usage": {"rounds": state.rounds, "tool_calls": state.tool_calls, "llm_calls": state.llm_calls,
                  "estimated_verification_cost_units": state.estimated_cost_spent,
                  "recorded_llm_responses": len(responses),
                  "recorded_total_tokens": sum(r.get("usage", {}).get("total_tokens", 0) for r in responses)},
    }


def render_report(state):
    data = report_data(state)
    labels = {"awaiting_clarification": "Awaiting design inputs", "preliminary_complete": "Conditional shortcut design complete",
              "needs_engineering_review": "Engineering verification required", "tool_failed": "Calculation or evidence check failed",
              "budget_exhausted": "Calculation budget reached", "agent_failed": "Agent execution or handoff failed"}
    lines = [f"Status {labels.get(state.status, state.status)}",
             f"Mode {'Three-agent LLM workflow' if state.mode == 'llm' else 'Deterministic three-role workflow'}",
             f"Strategy {'Hypothesis-driven verification' if state.strategy == 'hypothesis' else 'Rule-based workflow'}",
             f"Task revision {state.task_revision}", ""]
    if state.questions:
        lines += ["Required inputs"] + [f"- {q}" for q in state.questions] + [""]
    o = data["numerical_results"]
    if o:
        lines += ["DWSIM shortcut results under imposed product composition and recovery specifications",
                  f"- Reflux ratio {o['reflux_ratio']:.6g}",
                  f"- Estimated equilibrium stages {o['stages_estimate']:.6g}",
                  f"- Estimated minimum equilibrium stages {o['minimum_stages']:.6g}",
                  f"- Estimated minimum reflux ratio {o['minimum_reflux_ratio']:.6g}",
                  f"- Estimated reboiler duty {o['reboiler_duty_kw']:.6g} kW",
                  f"- Light-key mole fraction in the distillate {o['distillate_light_purity']:.8g}",
                  f"- Light-key recovery {o['light_recovery']:.8g}",
                  f"- Evidence ID {data['numerical_evidence_id']}", ""]
    if data["issues"]:
        lines += ["Open issues"] + [f"- {issue}" for issue in data["issues"]] + [""]
    if state.status == "agent_failed":
        errors = [e.details.get("reason", "") for e in state.events if e.action == "execution_error"]
        lines += ["Agent errors"] + [f"- {error}" for error in errors] + [""]
    if state.strategy == "hypothesis":
        lines += ["Design hypotheses under the stated model and sampled conditions"]
        lines += [f"- {h.hypothesis_id}: {h.status}. Evidence {', '.join(h.evidence_ids) or 'None'}"
                  for h in state.hypotheses]
        lines += ["", "Verification actions and selection rationale"]
        for decision in state.verification_decisions:
            chosen = next(a for a in decision.options if a.action_id == decision.selected_action_id)
            lines.append(f"- {chosen.kind}. Priority {chosen.score:.4g}. Estimated relative cost "
                         f"{chosen.estimated_cost_units:.4g}. {decision.rationale}")
        lines += [f"- Stop reason {reason}" for reason in data["verification_stop_reasons"]]
        lines += [f"- Total estimated relative cost {state.estimated_cost_spent:.4g} (relative units).", ""]
    lines += ["Applicability limits"] + [f"- {limit}" for limit in data["limitations"]]
    lines += ["", f"Calls and rounds {state.tool_calls} tool calls, {state.llm_calls} LLM calls, {state.rounds} rounds."]
    if data["served_models"]:
        lines.append("Model used " + ", ".join(data["served_models"]))
        lines.append(f"Recorded response tokens {data['usage']['recorded_total_tokens']}.")
    return "\n".join(lines)
