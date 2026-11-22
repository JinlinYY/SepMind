"""Deterministic reports from actual run artifacts, with incomplete sections retained."""


def render_report(state):
    if state.gates['G0'].status=='needs_input':
        from ..workflow.intake import describe_missing
        artifact = state.artifacts.get('check_design_specifications')
        missing = (artifact.data.get('missing_labels') or describe_missing(artifact.data.get('missing',[]))) if artifact else state.questions
        return '\n'.join(['# Complete the design basis','',
                          'The following inputs are required before phase equilibrium and distillation calculations.','']+
                         ['- '+item for item in missing]+
                         ['', 'Load a case in the right panel or enter component, feed, pressure, feed-state, and product requirements in the chat.',
                          'Supply the missing inputs before requesting a result explanation.'])
    model = state.artifacts.get('select_thermodynamic_model')
    model_name = model.data.get('selected_model') if model and model.status=='success' else state.basis.thermodynamic_model
    lines = ["# Preliminary separation process design report", "",
             f"Run {state.run_id}. Revision {state.revision}. Intent {state.intent}", "",
             "## Design basis", "", f"Pressure {state.basis.feed.pressure_kPa} kPa. Property model {model_name}. Mode {state.basis.design_mode}",
             f"Declared assumptions {', '.join(state.basis.assumptions) or 'None'}", ""]
    verified=state.artifacts.get('verify_and_refine_column')
    if verified and verified.validation.get('passed'):
        chosen=verified.data['selected_candidate']
        lines += ['## Selected preliminary design','',
            f"Rigorous column candidate {chosen['candidate_id']} with reflux ratio {chosen['reflux_ratio']:.5g}, equilibrium stages {chosen['equilibrium_stages']} (including the partial reboiler and excluding the total condenser), and feed stage {chosen['feed_stage']}.",
            'The candidate met the original product specifications. See the evidence below for the initial CMO design and rejected candidates.',
            'Equipment values are preliminary estimates under the stated assumptions. Full hydraulics, pressure-drop feedback, and vendor performance require further qualification.','']
    if state.expert_records:
        import json
        conclusions = {'admitted_for_test':'Admitted for numerical testing','supported_conditionally':'Conditionally supported',
                       'refuted':'Refuted by calculations','needs_input':'Evidence needed','blocked':'Blocked'}
        lines += ['## Expert constraints and hypothesis checks','',f'Knowledge version hash {state.expert_knowledge_hash}',
                  'This decision record is based on task inputs and tool evidence. Findings apply to the stated assumptions and numerical scope.','']
        for record in state.expert_records:
            lines += [f'### {record.gate} {record.title}', '',f'Skill {record.skill_id} v{record.skill_version}. Selected by {record.selected_by}',
                      f'Decision inputs {json.dumps(record.input_facts,ensure_ascii=False)}',
                      f'Hypothesis {record.hypothesis}',f'Review criteria {", ".join(record.criteria)}']
            for option in record.model_options:
                lines.append(f'- Model {option["model"]}. '+('Eligible for testing' if option['eligible'] else 'Excluded')+'. '+'; '.join(option['reasons']))
            lines += [f'Observations and checks {json.dumps(record.observations,ensure_ascii=False)}',
                      f'Conclusion {conclusions[record.conclusion]}. Next action {record.next_action}. Action state {record.action_status}',
                      f'Evidence {", ".join(record.evidence_after)}. Source run {record.source_run_id}. Reused {record.reused}',
                      'Limitations '+'; '.join(record.limitations),'']
    lines += ['## Workflow stages and evidence','']
    for gate in state.gates.values():
        if gate.gate == "G9":
            continue
        lines.append(f"- {gate.gate}: {gate.status}. {gate.reason}. Evidence {', '.join(gate.artifact_ids) or 'None'}")
    labels = {"calculate_material_balance": "Material balance", "calculate_mccabe_thiele_stages": "Equilibrium stage calculation",
              "resolve_property_parameters": "Property sources", "assess_separation_feasibility": "Conditional feasibility",
              'select_process_design':'Candidate selection and calculation basis','explore_reflux_candidates':'Reflux and stage trade-offs',
              'verify_and_refine_column':'Rigorous column verification and revision','calculate_energy_balance':'Enthalpy balance',
              'estimate_column_equipment':'Preliminary column sizing and hydraulics','estimate_auxiliary_equipment':'Preliminary auxiliary equipment and utilities'}
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
        lines += ["", f"## {title}", "", f"Artifact {artifact.artifact_id}. Source run {artifact.source_or_run}",
                  "", "```json", json.dumps(data,ensure_ascii=False,indent=2), "```"]
        if artifact.assumptions:
            lines += ['', 'Conditional assumptions used in this calculation '+', '.join(artifact.assumptions)]
    from .worked import calculation_appendix
    lines += calculation_appendix(state)
    scheme = state.artifacts.get('select_process_design')
    if scheme and scheme.status=='success' and scheme.validation.get('passed'):
        b = state.artifacts['calculate_material_balance'].data
        aux=state.artifacts.get('estimate_auxiliary_equipment')
        conditioned=aux and aux.validation.get('passed') and aux.data.get('feed_pump',{}).get('feed_heater')
        inlet=([f'  F["Cold tank feed {b["F_kmol_h"]:.4f} kmol/h"] --> P["Feed pump"]',
                f'  P --> H["Preheater {conditioned["duty_kW"]:.2f} kW"]',
                '  H --> C["Binary distillation column"]'] if conditioned else
               [f'  F["Feed {b["F_kmol_h"]:.4f} kmol/h"] --> C["Binary distillation column"]'])
        lines += ['', '## Preliminary flowsheet', '', '```mermaid', 'flowchart LR']+inlet+[
                  '  C --> T["Total condenser"]',f'  T --> D["Distillate {b["D_kmol_h"]:.4f} kmol/h"]',
                  '  T -->|Reflux| C','  C --> K["Partial reboiler"]','  K -->|Vapor return| C',
                  f'  K --> B["Bottoms {b["B_kmol_h"]:.4f} kmol/h"]','```',
                  '', 'The diagram shows process connections. See the run evidence for calculation scope. Controls and safety systems require further design.']
    lines += ["", "## Open design and verification items", "",
              ("See the stage status and tool evidence for the requested rigorous column, energy, and preliminary equipment calculations. Overall tray efficiency is empirical. Weeping, entrainment, pressure-drop feedback, and vendor performance require further checks."
               if 'verify_and_refine_column' in state.artifacts else "This run covers process screening. Select preliminary_equipment for rigorous column, energy, and equipment calculations."),
              "The phase stability assessment uses finite equilibrium samples. See the tool records for property and method assumptions and the scope of experimental screening.",
              "Equipment fabrication, construction, and safety compliance require separate qualification."]
    if state.questions:
        lines += ["", "## Missing inputs", ""]+[f"- {q}" for q in state.questions]
    return "\n".join(lines)
