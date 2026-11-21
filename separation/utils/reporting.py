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
    labels = {"awaiting_clarification": "等待补充设计条件", "preliminary_complete": "简捷初步设计完成（有条件）",
              "needs_engineering_review": "需要进一步工程验证", "tool_failed": "计算或数值证据检查失败",
              "budget_exhausted": "已达到本轮计算预算", "agent_failed": "代理执行或任务交接失败"}
    lines = [f"状态：{labels.get(state.status, state.status)}",
             f"运行模式：{'真实 LLM 三代理' if state.mode == 'llm' else '三角色规则基线（未调用 LLM）'}",
             f"决策策略：{'假设驱动主动验证' if state.strategy == 'hypothesis' else '原规则流程'}",
             f"任务版本：{state.task_revision}", ""]
    if state.questions:
        lines += ["需要补充："] + [f"- {q}" for q in state.questions] + [""]
    o = data["numerical_results"]
    if o:
        lines += ["DWSIM 简捷计算结果（产品组成与回收率为施加的分配规格）：",
                  f"- 回流比：{o['reflux_ratio']:.6g}",
                  f"- 理论级数估计：{o['stages_estimate']:.6g}",
                  f"- 最小理论级数估计：{o['minimum_stages']:.6g}",
                  f"- 最小回流比估计：{o['minimum_reflux_ratio']:.6g}",
                  f"- 再沸器负荷估计：{o['reboiler_duty_kw']:.6g} kW",
                  f"- 轻关键组分馏出液摩尔分数：{o['distillate_light_purity']:.8g}",
                  f"- 轻关键组分回收率：{o['light_recovery']:.8g}",
                  f"- 证据编号：{data['numerical_evidence_id']}", ""]
    if data["issues"]:
        lines += ["尚未解决的问题："] + [f"- {issue}" for issue in data["issues"]] + [""]
    if state.status == "agent_failed":
        errors = [e.details.get("reason", "") for e in state.events if e.action == "execution_error"]
        lines += ["代理错误："] + [f"- {error}" for error in errors] + [""]
    if state.strategy == "hypothesis":
        lines += ["设计假设状态（结论限定于当前模型和已采样条件）："]
        lines += [f"- {h.hypothesis_id}: {h.status}；证据：{', '.join(h.evidence_ids) or '尚无'}"
                  for h in state.hypotheses]
        lines += ["", "验证动作及选择依据："]
        for decision in state.verification_decisions:
            chosen = next(a for a in decision.options if a.action_id == decision.selected_action_id)
            lines.append(f"- {chosen.kind}；优先级 {chosen.score:.4g}；预计相对成本 "
                         f"{chosen.estimated_cost_units:.4g}；{decision.rationale}")
        lines += [f"- 停止原因：{reason}" for reason in data["verification_stop_reasons"]]
        lines += [f"- 累计预计相对成本：{state.estimated_cost_spent:.4g}（不是实际耗时）。", ""]
    lines += ["适用限制："] + [f"- {limit}" for limit in data["limitations"]]
    lines += ["", f"调用统计：{state.tool_calls} 次计算工具，{state.llm_calls} 次 LLM，{state.rounds} 轮协作。"]
    if data["served_models"]:
        lines.append("实际模型：" + ", ".join(data["served_models"]))
        lines.append(f"已记录的模型响应 token 总数：{data['usage']['recorded_total_tokens']}。")
    return "\n".join(lines)
