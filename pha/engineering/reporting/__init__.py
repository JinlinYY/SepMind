"""Deterministic reports from actual run artifacts, with incomplete sections retained."""


def render_report(state):
    if state.gates['G0'].status=='needs_input':
        from ..workflow.intake import describe_missing
        artifact = state.artifacts.get('check_design_specifications')
        missing = (artifact.data.get('missing_labels') or describe_missing(artifact.data.get('missing',[]))) if artifact else state.questions
        return '\n'.join(['# 请补充设计依据','',
                          '尚未开始相平衡或精馏计算，当前缺少：','']+
                         ['- '+item for item in missing]+
                         ['', '请在右侧明确载入案例，或在左侧输入完整的组分、进料、压力、热状态和产品目标。',
                          '仅输入“解释本次计算结果”不会补充缺失条件。'])
    model = state.artifacts.get('select_thermodynamic_model')
    model_name = model.data.get('selected_model') if model and model.status=='success' else state.basis.thermodynamic_model
    lines = ["# 分离过程设计阶段报告（初步、未完成全部设计）", "",
             f"运行：{state.run_id}；版本：{state.revision}；意图：{state.intent}", "",
             "## 设计依据", "", f"压力：{state.basis.feed.pressure_kPa} kPa；物性模型：{model_name}；模式：{state.basis.design_mode}",
             f"已声明假设：{', '.join(state.basis.assumptions) or '无'}", ""]
    verified=state.artifacts.get('verify_and_refine_column')
    if verified and verified.validation.get('passed'):
        chosen=verified.data['selected_candidate']
        lines += ['## 本次最终初步方案','',
            f"严格塔候选 {chosen['candidate_id']}：回流比 {chosen['reflux_ratio']:.5g}；平衡级数 {chosen['equilibrium_stages']}（含部分再沸器、不含全凝器）；进料级 {chosen['feed_stage']}。",
            '原产品指标严格通过。初始 CMO 方案与被拒绝的候选保留在下面的证据中。',
            '设备结果属于显式假设下的初步估算；完整水力学、压降反馈和厂家性能并未获批。','']
    if state.expert_records:
        import json
        conclusions = {'admitted_for_test':'允许进入数值检验','supported_conditionally':'条件性支持',
                       'refuted':'被计算反证','needs_input':'证据待补充','blocked':'阻断'}
        lines += ['## 专家知识约束与假设检验','',f'本次知识版本哈希：{state.expert_knowledge_hash}',
                  '以下是依据实际输入与工具证据形成的公开决策记录。方法假设和数值自洽不等于工业验证。','']
        for record in state.expert_records:
            lines += [f'### {record.gate} {record.title}', '',f'采用 Skill：{record.skill_id} v{record.skill_version}；选择方式：{record.selected_by}',
                      f'输入判据：{json.dumps(record.input_facts,ensure_ascii=False)}',
                      f'待检验假设：{record.hypothesis}',f'审查标准：{", ".join(record.criteria)}']
            for option in record.model_options:
                lines.append(f'- 模型 {option["model"]}：'+('可进入检验' if option['eligible'] else '排除')+'；'+'; '.join(option['reasons']))
            lines += [f'观察与验证：{json.dumps(record.observations,ensure_ascii=False)}',
                      f'结论：{conclusions[record.conclusion]}；后续动作：{record.next_action}；动作状态：{record.action_status}',
                      f'证据：{", ".join(record.evidence_after)}；源运行：{record.source_run_id}；复用：{record.reused}',
                      '保留限制：'+'; '.join(record.limitations),'']
    lines += ['## 关卡与证据','']
    for gate in state.gates.values():
        if gate.gate == "G9":
            continue
        lines.append(f"- {gate.gate}: {gate.status}；{gate.reason}；证据：{', '.join(gate.artifact_ids) or '无'}")
    labels = {"calculate_material_balance": "物料衡算", "calculate_mccabe_thiele_stages": "理论级计算",
              "resolve_property_parameters": "物性来源", "assess_separation_feasibility": "条件性可行性",
              'select_process_design':'自主方案选择与计算依据','explore_reflux_candidates':'回流比与级数权衡',
              'verify_and_refine_column':'严格塔验证与反证修正','calculate_energy_balance':'焓基能量衡算',
              'estimate_column_equipment':'塔体与水力学初步估算','estimate_auxiliary_equipment':'附属设备与公用工程初步估算'}
    for key,title in labels.items():
        artifact = state.artifacts.get(key)
        if artifact is None or artifact.status != "success" or not artifact.validation.get("passed"):
            continue
        import json
        data = {k:v for k,v in artifact.data.items() if k not in ('steps','selected_simulation','tray_results','valve_layouts','load_performance_charts')}
        if 'valve_layouts' in artifact.data:
            data['valve_layouts']={name:{k:v for k,v in layout.items() if k!='centers_m'}
                                  for name,layout in artifact.data['valve_layouts'].items()}
        if 'selected_simulation' in artifact.data:
            data['native_evidence_id']=artifact.data['selected_simulation']['evidence_id']
            data['native_flowsheet']=artifact.data['selected_simulation']['saved_flowsheet']
        lines += ["", f"## {title}", "", f"来源：{artifact.artifact_id}；原运行：{artifact.source_or_run}",
                  "", "```json", json.dumps(data,ensure_ascii=False,indent=2), "```"]
        if artifact.assumptions:
            lines += ['', '本方法采用的条件性近似：'+', '.join(artifact.assumptions)]
    from .worked import calculation_appendix
    lines += calculation_appendix(state)
    scheme = state.artifacts.get('select_process_design')
    if scheme and scheme.status=='success' and scheme.validation.get('passed'):
        b = state.artifacts['calculate_material_balance'].data
        aux=state.artifacts.get('estimate_auxiliary_equipment')
        conditioned=aux and aux.validation.get('passed') and aux.data.get('feed_pump',{}).get('feed_heater')
        inlet=([f'  F["冷储罐进料 {b["F_kmol_h"]:.4f} kmol/h"] --> P["进料泵"]',
                f'  P --> H["预热器 {conditioned["duty_kW"]:.2f} kW"]',
                '  H --> C["二元精馏塔"]'] if conditioned else
               [f'  F["进料 {b["F_kmol_h"]:.4f} kmol/h"] --> C["二元精馏塔"]'])
        lines += ['', '## 初步流程草图', '', '```mermaid', 'flowchart LR']+inlet+[
                  '  C --> T["全凝器"]',f'  T --> D["馏出液 {b["D_kmol_h"]:.4f} kmol/h"]',
                  '  T -->|回流| C','  C --> K["部分再沸器"]','  K -->|汽相返回| C',
                  f'  K --> B["釜液 {b["B_kmol_h"]:.4f} kmol/h"]','```',
                  '', '仅表示工艺连接；计算范围见各工具证据，控制及安全系统仍需设计。']
    lines += ["", "## 未完成的设计与校核", "",
              ("本次请求了严格塔、能量与初步设备工具；实际完成项以关卡状态和工具证据为准。整体板效率为经验估计；完整漏液/夹带、压降反馈及厂家性能尚待验证。"
               if 'verify_and_refine_column' in state.artifacts else "本次为流程筛查模式，尚未执行严格塔、能量和设备工具；选择 preliminary_equipment 可启动深化计算。"),
              "有限相平衡采样不证明全局相稳定；物性及方法近似以本次工具记录为准。NRTL 独立实验筛查不代表工业设计精度。",
              "本报告不能作为设备制造、施工或安全合规依据。"]
    if state.questions:
        lines += ["", "## 待补充", ""]+[f"- {q}" for q in state.questions]
    return "\n".join(lines)
