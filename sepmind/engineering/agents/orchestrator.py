"""PHA orchestration/session inheritance with an explicit engineering gate policy."""

import json
import threading
from pathlib import Path

from sepmind.agent_runtime.orchestrator import MultiAgentOrchestrator
from sepmind.prompts.engineering_prompts import load_engineering_prompt, planning_prompt
from sepmind.streaming import emit_step
from sepmind.utils.request_stats import request_stats
from ..schemas import DesignBasis, DesignState, DecisionRecord, PlannerChoice, Reason
from ..tools.registry import missing_specifications
from ..workflow.graph import changed_gates, require_gate, descendants
from ..workflow.intents import route, extract_patch, merge_basis
from .specialists import EngineeringCalculationAgent, ThermodynamicsExpertAgent, ProcessDesignAdvisorAgent


class EngineeringOrchestrator(MultiAgentOrchestrator):
    PLAN = [
        ("G0", ("parse_design_basis", "check_design_specifications")),
        ("G2", ("select_thermodynamic_model", "resolve_property_parameters")),
        ("G1", ("calculate_binary_vle", "assess_separation_feasibility")),
        ("G3", ("calculate_material_balance",)),
        ("G4", ("estimate_minimum_reflux", "explore_reflux_candidates", "select_process_design", "calculate_mccabe_thiele_stages")),
    ]

    def __init__(self, basis=None, backend=None, registry=None, max_llm_calls=24, output_dir=None):
        if getattr(backend, "provider", None) in {"gemini", "openai", "anthropic"}:
            raise ValueError("Engineering LLM provider must be DeepSeek")
        super().__init__(name="ThermoExpert PHA engineering extension",
                         system_prompt=load_engineering_prompt("SYSTEM_ORCHESTRATOR"))
        self._backend = backend
        self.basis = basis if isinstance(basis,DesignBasis) else DesignBasis.model_validate(basis or {})
        self.calculation_agent = EngineeringCalculationAgent(registry)
        self.thermodynamics_agent = ThermodynamicsExpertAgent()
        self.advisor_agent = ProcessDesignAdvisorAgent(self.thermodynamics_agent.skills)
        # Actual inherited PHA team-registration path, not a copied set_agents API.
        super().set_agents(data_science_agent=self.calculation_agent,
                           domain_expert_agent=self.thermodynamics_agent,
                           health_coach_agent=self.advisor_agent)
        self.state = None
        self.runs = []
        self.max_llm_calls = max_llm_calls
        self.output_dir = Path(output_dir or Path(__file__).resolve().parents[3] / "output/engineering")
        self._run_lock = threading.RLock()

    def configure(self, api_key=None, provider=None, model_name=None, temperature=0.7,
                  gemini_api_key=None):
        """Reuse PHA's provider path, with a DeepSeek-only engineering policy."""
        provider = (provider or "deepseek").lower()
        if provider not in ('deepseek','qwen') or gemini_api_key:
            raise ValueError("Engineering LLM provider must be DeepSeek or Qwen")
        return super().configure(api_key=api_key, provider=provider,
                                 model_name=model_name, temperature=temperature)

    def _decide(self,state,gate,tool,skill_context=None):
        if gate=='G0' and missing_specifications(state.basis,state.intent=='THERMODYNAMIC_CALCULATION'):
            return '先完成本地输入检查，缺少设计依据时不调用 LLM 或启动工艺计算。',None
        refs = sorted(set(state.basis.source_ids)|{ref for a in state.artifacts.values() if a.status == 'success'
                       for ref in [a.artifact_id]+[e.evidence_id for e in a.evidence]})
        rationale = "Execute the next registered method after its prerequisite gates and evidence checks."
        if self._backend is not None:
            context = {"basis":state.basis.model_dump(),"legal_next_call":{"gate":gate,"tool_name":tool},
                       "available_evidence_ids":refs,"gate_states":{g:s.status for g,s in state.gates.items()}}
            context['verified_observations'] = {name:{k:v for k,v in artifact.data.items()
                if k in {'selected_model','conditional_feasible','azeotropic_compositions_under_model',
                         'minimum_reflux_ratio','candidates','default_candidate_id','policy','issues',
                         'selected_candidate','condenser_duty_kW','reboiler_duty_kW',
                         'diameter_m','actual_trays_estimate','unresolved_checks'}}
                for name,artifact in state.artifacts.items() if artifact.status=='success'}
            choices = state.artifacts.get('explore_reflux_candidates')
            needs_selection = tool=='select_process_design' and choices and choices.data.get('candidates')
            if needs_selection:
                context['selection_instruction'] = 'Choose candidate_id from a computed feasible candidate. Explain the stage/vapor-flow tradeoff using observed results. Never invent a reflux ratio. Reject computed failures.'
            if skill_context:
                context['expert_skill_context'] = skill_context
            for attempt in range(2):
                if state.llm_calls >= self.max_llm_calls:
                    raise ValueError('LLM_BUDGET: no further planner calls permitted')
                state.llm_calls += 1
                raw = self._call_llm(planning_prompt(context,PlannerChoice.model_json_schema()),max_retries=1)
                if raw.startswith('Error:'):
                    raise RuntimeError('LLM_PROVIDER_ERROR: '+raw)
                metadata = getattr(self._backend,'last_response_info',None)
                if metadata:
                    allowed = {'provider','requested_model','served_model','response_id','request_id','id','usage'}
                    state.provider_events.append({k:v for k,v in metadata.items() if k in allowed})
                choice = None
                try:
                    choice = PlannerChoice.model_validate_json(self._clear_json_format(raw))
                    if choice.gate!=gate or choice.tool_name!=tool:
                        raise ValueError(f'GATE_PRECONDITION: echo legal_next_call exactly: gate={gate}, tool_name={tool}')
                    if not set(choice.evidence_ids).issubset(refs):
                        raise ValueError('EVIDENCE_PRECONDITION: evidence_ids may contain only available_evidence_ids; use [] when unsure')
                    if skill_context and choice.skill_id not in {s['skill_id'] for s in skill_context['eligible_skills']}:
                        raise ValueError('SKILL_PRECONDITION: choose an eligible skill_id')
                    if needs_selection and choice.candidate_id not in {r['candidate_id'] for r in choices.data['candidates'] if r['status']=='feasible'}:
                        raise ValueError('INVALID_DESIGN_SELECTION: choose a computed feasible candidate')
                except ValueError as exc:
                    state.rejected_planner_proposals.append({'gate':gate,'tool':tool,'attempt':attempt+1,
                                                              'reason':str(exc)[:1000],
                                                              'proposal':{k:getattr(choice,k) for k in ('gate','tool_name','skill_id','candidate_id','evidence_ids')} if choice else None})
                    if attempt:
                        raise
                    context['rejected_proposal_feedback'] = {'reason':str(exc)[:1000],
                        'required_call':{'gate':gate,'tool_name':tool},'allowed_evidence_ids':refs,
                        'instruction':'Correct this proposal using only the legal tool, eligible skill and computed feasible candidate IDs. One correction is permitted.'}
                    continue
                break
            rationale = choice.rationale
            if needs_selection:
                feasible_ids = {r['candidate_id'] for r in choices.data['candidates'] if r['status']=='feasible'}
                if choice.candidate_id not in feasible_ids:
                    raise ValueError('INVALID_DESIGN_SELECTION: DeepSeek must nominate a computed feasible candidate_id')
                state.design_preferences = {'candidate_id':choice.candidate_id,'rationale':rationale}
            skill_id = choice.skill_id if skill_context else None
        else:
            skill_id = skill_context['eligible_skills'][0]['skill_id'] if skill_context else None
        return rationale,skill_id

    def _skill_context(self,state,gate,tool):
        return (self.thermodynamics_agent.skill_context(state,gate,tool) if gate in ('G1','G2')
                else self.advisor_agent.skill_context(state,gate,tool) if gate in ('G4','G5','G6','G7') else None)

    def _gate(self,state,gate,tools):
        if state.gates[gate].status == "passed":
            return True
        require_gate(state,gate)
        status = state.gates[gate]
        status.status = "running"
        for tool in tools:
            skill_context = self._skill_context(state,gate,tool)
            rationale,skill_id = self._decide(state,gate,tool,skill_context)
            if gate in ("G1","G2"):
                result = self.thermodynamics_agent.execute(state,gate,tool,self.calculation_agent)
            else:
                result = self.calculation_agent.execute(state,gate,tool)
            state.artifacts[tool] = result
            status.artifact_ids.append(result.artifact_id)
            expert_start = len(state.expert_records)
            if skill_context:
                self.thermodynamics_agent.skills.observe(state,gate,tool,skill_context,skill_id,result)
            valid = result.status == "success" and result.validation.get("passed") is True
            if not valid:
                status.status = "needs_input" if result.status == "needs_input" else "blocked" if result.status == "unsupported" else "failed"
                status.reason = "; ".join(e.explanation for e in result.errors) or '；'.join(result.data.get('missing_labels',[])) or str(result.validation)
                state.questions += result.data.get('missing_labels',result.data.get('missing',[]))
            options, selected = [tool,'request_missing_evidence_or_stop'],tool
            if tool=='select_process_design' and result.data.get('candidate_id'):
                options = [r['candidate_id'] for r in state.artifacts['explore_reflux_candidates'].data['candidates']]
                selected = result.data['candidate_id']
            if tool=='select_thermodynamic_model' and result.data.get('selected_model'):
                assessment=(skill_context or {}).get('model_assessment',result.data.get('expert_model_assessment',{}))
                options = [r['model'] for r in assessment.get('model_options',[])]
                selected = result.data['selected_model']
            state.decisions.append(DecisionRecord(
                gate=gate,question=f"Are prerequisites and evidence sufficient for {tool}?",
                candidate_options=options,selected_option=selected,
                evidence_ids=[result.artifact_id]+[e.evidence_id for e in result.evidence],
                assumptions=result.assumptions,reasons=[Reason(code="VALIDATED_TOOL" if valid else result.error_type or "VALIDATION_FAILED",
                                                               explanation=rationale if valid else status.reason)],
                status="accepted" if valid else "needs_input" if status.status == "needs_input" else "blocked",
                skill_ids=[skill_id] if skill_id else [],
                expert_record_ids=[r.record_id for r in state.expert_records[expert_start:]]))
            emit_step("EngineeringGate",f"{gate}: {tool} {'validated' if valid else status.status}",detail=result.artifact_id)
            if not valid:
                state.status = "needs_input" if status.status == "needs_input" else "blocked" if status.status == "blocked" else "failed"
                return False
        status.status = "passed"
        status.reason = "All registered tool results passed their numerical/data checks; scope limitations retained."
        return True

    def _persist(self,state):
        self.output_dir.mkdir(parents=True,exist_ok=True)
        target = self.output_dir/(state.run_id+".json")
        temp = target.with_suffix(".tmp")
        temp.write_text(state.model_dump_json(indent=2),encoding="utf-8")
        temp.replace(target)

    def run(self,basis=None,message="",intent="PROCESS_DESIGN"):
        with self._run_lock:
            self.thermodynamics_agent.skills.reload()
            basis = DesignBasis.model_validate(basis.model_dump() if isinstance(basis,DesignBasis) else basis or self.basis.model_dump())
            old = self.state
            state = DesignState(basis=basis,revision=old.revision+1 if old else 1,
                                parent_run_id=old.run_id if old else None,intent=intent,original_message=message,
                                provider=getattr(self._backend,"provider","deterministic") if self._backend else "deterministic",
                                expert_knowledge_hash=self.thermodynamics_agent.skills.knowledge_hash)
            if old:
                invalid = changed_gates(old.basis,basis) | {"G0","G8","G9"}
                if old.expert_knowledge_hash != state.expert_knowledge_hash:
                    invalid |= descendants({'G2','G1'})
                state.invalidated_gates = sorted(invalid)
                for tool,artifact in old.artifacts.items():
                    gate = self.calculation_agent.registry.TOOLS[tool][0]
                    if gate not in invalid and old.gates[gate].status == "passed":
                        state.artifacts[tool] = artifact.model_copy(deep=True)
                        state.gates[gate] = old.gates[gate].model_copy(deep=True)
                        state.reused_artifact_ids.append(artifact.artifact_id)
                for record in old.expert_records:
                    if record.artifact_id in state.reused_artifact_ids:
                        reused = record.model_copy(deep=True)
                        reused.reused = True
                        state.expert_records.append(reused)
                self.runs.append(old.model_copy(deep=True))
            self.state,self.basis = state,basis
            try:
                plan = list(self.PLAN)
                if basis.design_level == 'preliminary_equipment' and intent != 'THERMODYNAMIC_CALCULATION':
                    plan[-1] = ('G4',plan[-1][1]+('verify_and_refine_column',))
                    plan.append(('G5',('calculate_energy_balance',)))
                    plan.append(('G6',('estimate_column_equipment',)))
                    plan.append(('G7',('estimate_auxiliary_equipment',)))
                for gate,tools in plan:
                    if intent == "THERMODYNAMIC_CALCULATION" and gate in ("G3","G4"):
                        break
                    if not self._gate(state,gate,tools):
                        break
                if state.status == "running":
                    state.status = "thermodynamic_calculation_complete" if intent == "THERMODYNAMIC_CALCULATION" else "partial_design"
                # Missing stages are explicit, not a simulation of performed sizing.
                for gate in ("G5","G6","G7"):
                    if state.gates[gate].status == 'not_started':
                        state.gates[gate].status = "blocked"
                        state.gates[gate].reason = ("当前选择流程筛查模式，未请求严格塔、能量和设备深化计算；可选择 preliminary_equipment。"
                            if basis.design_level != 'preliminary_equipment' else 'Prerequisite calculation or qualified equipment inputs still required.')
                if state.gates["G0"].status == "passed":
                    self._gate(state,"G8",("check_design_consistency",))
                    if state.gates["G8"].status == "passed":
                        self._gate(state,"G9",("render_preliminary_design_report",))
            except Exception as exc:
                state.status = "failed"
                state.questions.append(str(exc))
                for gate in state.gates.values():
                    if gate.status == "running":
                        gate.status,gate.reason = "failed",str(exc)
            if state.status == "running":
                state.status = "partial_design"
            state.report_markdown = self.advisor_agent.explain(state)
            self._persist(state)
            return state

    def respond(self,user_message,task_updates=None):
        with self._run_lock:
            self.add_user_message(user_message)  # inherited PHA conversation state
            request_stats.reset()
            intent = route(user_message,self.state is not None)
            if task_updates:
                intent = "DESIGN_REVISION" if self.state else "PROCESS_DESIGN"
            if intent == "KNOWLEDGE_QA":
                response = self.thermodynamics_agent.knowledge_answer(user_message)
            elif intent == "UNSUPPORTED":
                response = "该任务超出已验证的二元普通精馏范围；未执行工艺设计或生成设备数值。"
            elif intent == "RESULT_EXPLANATION":
                response = self.state.report_markdown
            else:
                patch = task_updates if task_updates is not None else extract_patch(user_message,self.basis)
                if intent == "DESIGN_REVISION" and not patch:
                    response = "未识别到明确可更新的字段，设计依据保持不变。请说明字段和单位，例如‘改为80 kPa’，或使用结构化表单。"
                    self.add_response(response)
                    return response
                updated = merge_basis(self.basis,patch)
                response = self.run(updated,user_message,intent).report_markdown
            self.add_response(response)  # inherited PHA conversation history
            return response

    def reset_conversation(self):
        super().reset_conversation()
        self.state = None
        self.runs.clear()
        self.basis = DesignBasis()
