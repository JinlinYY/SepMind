"""Multicomponent process branch reusing PHA coordination and specialist tools.

The original binary orchestrator is retained unchanged as the baseline. This
branch reports its actual extraction slice and explicitly blocks unsupported
downstream regeneration instead of relabelling it a completed hybrid design.
"""
import copy
import json
from pathlib import Path
import threading

from sepmind.agent_runtime.orchestrator import MultiAgentOrchestrator
from sepmind.prompts.engineering_prompts import load_engineering_prompt
from sepmind.prompts.data_science_prompts import render_prompt
from sepmind.streaming import emit_step
from ..schemas import PlannerChoice, DecisionRecord, Reason
from ..schemas.process import ProcessDesignBasis, ProcessDesignState, ExtractionSearch, parse_process_basis
from ..workflow.process_revision import extraction_revision_options, ExtractionRevisionChoice
from ..tools.process import ProcessToolRegistry, missing_process_inputs
from ..skills.process import ProcessSkillRegistry
from ..workflow.intents import route, extract_patch
from .orchestrator import EngineeringOrchestrator
from .specialists import EngineeringCalculationAgent, ThermodynamicsExpertAgent, ProcessDesignAdvisorAgent


class ProcessEngineeringOrchestrator(EngineeringOrchestrator):
    PLAN=[('G0','check_process_basis'),('G2','qualify_lle_model'),('G3','calculate_process_feed_inventory'),
          ('G1','screen_extraction_phase_split'),('G4','explore_extraction_candidates'),
          ('G8','review_extraction_candidates'),('G4','select_extraction_candidate')]

    def __init__(self,basis,backend=None,output_dir=None,max_llm_calls=20):
        if backend is not None and getattr(backend,'provider',None) not in ('deepseek','qwen'):
            raise ValueError('Process LLM provider must be DeepSeek or Qwen')
        MultiAgentOrchestrator.__init__(self,name='SepMind',system_prompt=load_engineering_prompt('PROCESS_PLANNER'))
        self._backend=backend;self.basis=ProcessDesignBasis.model_validate(basis)
        self.calculation_agent=EngineeringCalculationAgent(ProcessToolRegistry())
        self.thermodynamics_agent=ThermodynamicsExpertAgent();self.advisor_agent=ProcessDesignAdvisorAgent()
        self.process_skills=ProcessSkillRegistry()
        self.set_agents(data_science_agent=self.calculation_agent,domain_expert_agent=self.thermodynamics_agent,health_coach_agent=self.advisor_agent)
        self.output_dir=Path(output_dir or Path(__file__).resolve().parents[3]/'output/engineering/process_runs')
        self.max_llm_calls=max_llm_calls;self._run_lock=threading.RLock();self.state=None;self.runs=[]

    def _process_choice(self,state,gate,tool):
        skills=self.process_skills.for_tool(tool)
        refs=[a.artifact_id for a in state.artifacts.values() if a.status=='success']
        fallback=PlannerChoice(gate=gate,tool_name=tool,skill_id=skills[0]['skill_id'],evidence_ids=refs,
                               rationale='Inspect the stated prerequisites, execute the typed tool and retain its numerical evidence and limits.')
        # Missing inputs remain a local check and do not consume provider calls.
        if self._backend is None or gate=='G0':return fallback
        if state.llm_calls>=self.max_llm_calls:raise ValueError('LLM_BUDGET: bounded process planner calls exhausted')
        context={'basis':state.basis.model_dump(),'legal_next_call':{'gate':gate,'tool_name':tool},
                 'eligible_skills':skills,'available_evidence_ids':refs,
                 'active_search':(state.active_search or state.basis.search).model_dump(),
                 'revision_history':state.revision_history}
        a=state.artifacts.get('explore_extraction_candidates')
        if tool=='select_extraction_candidate' and a:
            context['computed_feasible_candidates']=[{k:r[k] for k in ('candidate_id','stages','solvent_feed_mass_ratio','solvent_mass_flow_kg_h')}|
                {'extraction_recovery':r['raw']['solute_extraction_recovery'],'water_coextraction_kg_h':r['raw']['water_coextraction_kg_h']} for r in a.data['candidates'] if r['status']=='feasible']
            if not context['computed_feasible_candidates']:return fallback
        prompt=render_prompt('{{ policy }}\nOUTPUT_SCHEMA:\n{{ schema }}\nCONTEXT_DATA:\n{{ context }}',
            policy=load_engineering_prompt('PROCESS_PLANNER'),schema=json.dumps(PlannerChoice.model_json_schema()),context=json.dumps(context,ensure_ascii=False))
        state.llm_calls+=1
        raw=self._call_llm(prompt,max_retries=1)
        if raw.startswith('Error:'):raise ValueError('LLM_PROVIDER_ERROR: '+raw)
        choice=PlannerChoice.model_validate_json(self._clear_json_format(raw))
        if choice.gate!=gate or choice.tool_name!=tool or choice.skill_id not in {s['skill_id'] for s in skills} or not set(choice.evidence_ids).issubset(refs):
            raise ValueError('INVALID_PROCESS_PLAN: illegal tool, skill or evidence')
        if tool=='select_extraction_candidate' and choice.candidate_id not in {r['candidate_id'] for r in context['computed_feasible_candidates']}:
            raise ValueError('INVALID_DESIGN_SELECTION: a computed feasible extraction candidate is required')
        metadata=getattr(self._backend,'last_response_info',None)
        if metadata:state.provider_events.append(copy.deepcopy(metadata))
        return choice

    def _revise_extraction(self,state):
        options=extraction_revision_options(state)
        if not options:return False
        refs=[a.artifact_id for a in state.artifacts.values()]
        choice=ExtractionRevisionChoice(action_id=options[0]['action_id'],evidence_ids=refs,
            rationale=options[0]['rationale'])
        if self._backend is not None:
            if state.llm_calls>=self.max_llm_calls:raise ValueError('LLM_BUDGET: correction planner budget exhausted')
            context={'frozen_requirements':state.basis.model_dump(),'numerical_failure':'EXTRACTION_TARGET_NOT_MET',
                     'available_evidence_ids':refs,'legal_revisions':options,
                     'failed_candidates':state.artifacts['explore_extraction_candidates'].data['candidates']}
            prompt=('Choose exactly one bounded expert correction. Return JSON matching '+
                json.dumps(ExtractionRevisionChoice.model_json_schema())+
                '. Cite available evidence. Do not invent values, relax targets, change models or claim a result. '+json.dumps(context))
            state.llm_calls+=1
            raw=self._call_llm(prompt,max_retries=1)
            choice=ExtractionRevisionChoice.model_validate_json(self._clear_json_format(raw))
            if not set(choice.evidence_ids).issubset(refs) or not choice.evidence_ids:
                raise ValueError('INVALID_REVISION_EVIDENCE')
            metadata=getattr(self._backend,'last_response_info',None)
            if metadata:state.provider_events.append(copy.deepcopy(metadata))
        selected=next((o for o in options if o['action_id']==choice.action_id),None)
        if selected is None:raise ValueError('INVALID_CORRECTION: choose a declared bounded action')
        previous=(state.active_search or state.basis.search).model_dump()
        state.active_search=ExtractionSearch.model_validate(selected['search'])
        state.revision_history.append({'revision':len(state.revision_history)+1,
            'diagnosis':'Checked extraction endpoint below unchanged target; not physical infeasibility',
            'action_id':choice.action_id,'previous_search':previous,'next_search':selected['search'],
            'evidence_ids':choice.evidence_ids,'rationale':choice.rationale,
            'invalidated_gates':['G1','G4','G8'],'targets_unchanged':True})
        state.decisions.append(DecisionRecord(gate='G8',question='Revise a checked off-spec extraction design',
            candidate_options=[o['action_id'] for o in options],selected_option=choice.action_id,
            evidence_ids=choice.evidence_ids,assumptions=state.basis.assumptions,
            reasons=[Reason(code='BOUNDED_EXPERT_CORRECTION',explanation=choice.rationale)],status='accepted'))
        state.accepted_candidate_id=None
        state.design_preferences.pop('extraction_candidate_id',None)
        for tool in ('screen_extraction_phase_split','explore_extraction_candidates','review_extraction_candidates','select_extraction_candidate'):
            state.artifacts.pop(tool,None)
        for gate in ('G1','G4','G8'):
            state.gates[gate].status='not_started';state.gates[gate].reason='Invalidated by bounded extraction revision; requires recalculation'
        emit_step('ExpertCorrection',choice.action_id+': '+choice.rationale)
        return True

    def run(self,basis=None,message='',intent='PROCESS_DESIGN'):
        with self._run_lock:
            if basis is not None:self.basis=ProcessDesignBasis.model_validate(basis)
            old=self.state
            state=ProcessDesignState(basis=self.basis.model_copy(deep=True),original_message=message,
                provider=getattr(self._backend,'provider','deterministic'),revision=len(self.runs)+1,parent_run_id=old.run_id if old else None)
            self.state=state;self.runs.append(state)
            pending=list(self.PLAN)
            while pending:
                gate,tool=pending.pop(0)
                state.gates[gate].status='running'
                try:
                    choice=self._process_choice(state,gate,tool)
                    if choice.candidate_id:state.design_preferences['extraction_candidate_id']=choice.candidate_id
                    owner=self.process_skills.for_tool(tool)[0]['owner']
                    if owner=='thermodynamics':out=self.thermodynamics_agent.execute(state,gate,tool,self.calculation_agent)
                    else:out=self.calculation_agent.execute(state,gate,tool)
                    state.artifacts[tool]=out;state.artifact_history.append(out.model_copy(deep=True))
                    passed=out.status=='success' and out.validation.get('passed') is True
                    state.gates[gate].status='passed' if passed else 'needs_input' if out.status=='needs_input' else 'failed'
                    state.gates[gate].artifact_ids.append(out.artifact_id)
                    state.gates[gate].reason='; '.join(r.explanation for r in out.errors) if not passed else out.data.get('scope','')
                    state.decisions.append(DecisionRecord(gate=gate,question=tool,candidate_options=[tool],selected_option=tool,
                        evidence_ids=choice.evidence_ids+[out.artifact_id],assumptions=state.basis.assumptions,
                        reasons=[Reason(code='EXECUTED_TYPED_PROCESS_TOOL',explanation=choice.rationale)],
                        status='accepted' if passed else 'needs_input' if out.status=='needs_input' else 'rejected',skill_ids=[choice.skill_id]))
                    state.expert_records.append({'gate':gate,'tool':tool,'owner':owner,'skill_id':choice.skill_id,
                        'skill_sha256':self.process_skills.hashes[choice.skill_id],'status':state.gates[gate].status,
                        'validation':copy.deepcopy(out.validation),'artifact_id':out.artifact_id})
                    if not passed:
                        if tool=='select_extraction_candidate' and self._revise_extraction(state):
                            pending=list(self.PLAN[3:]);continue
                        state.status='needs_input' if out.status=='needs_input' else 'failed';break
                except ValueError as exc:
                    state.status='failed';state.gates[gate].status='failed';state.gates[gate].reason=str(exc);break
            if state.status=='running':state.status='partial_design'
            for gate in ('G5','G6','G7'):
                state.gates[gate].status='blocked'
                state.gates[gate].reason='Full downstream VLE/association, energy, regeneration/recycle and equipment qualification are not yet available for this hybrid route.'
            state.report_markdown=self.report(state)
            state.gates['G9'].status='passed';state.gates['G9'].reason='Evidence-linked partial report only; not complete process approval'
            folder=self.output_dir/state.run_id;folder.mkdir(parents=True,exist_ok=False)
            (folder/'run.json').write_text(state.model_dump_json(indent=2),encoding='utf8')
            (folder/'report.md').write_text(state.report_markdown,encoding='utf8')
            return state

    def respond(self,user_message,task_updates=None):
        with self._run_lock:
            from sepmind.utils.request_stats import request_stats
            request_stats.reset()
            self.add_user_message(user_message)
            intent=route(user_message,self.state is not None)
            if task_updates:intent='DESIGN_REVISION'
            if intent=='RESULT_EXPLANATION':
                response=self.state.report_markdown
            elif intent=='KNOWLEDGE_QA':
                response=('SepMind 先核对原料和目标，再审查物性证据、检验分相、比较实际计算的萃取候选，最后独立复核级间连接与组分守恒。'
                          '当前醋酸／水／乙酸乙酯分支仅准入经实验点筛查的 NRTL 液液平衡模型，不能据此批准气液平衡、缔合、能量或完整溶剂循环。'
                          '普通 Wilson 不用于稳定液液分相设计。依据：engineering/runtime_process_skills/ 与 engineering/data/hybrid/acid_lle_colombo1999_v1.json。'
                          '本条为方法说明，未新增数值计算；具体结果以已保存的运行证据为准。')
            elif intent in ('UNSUPPORTED','THERMODYNAMIC_CALCULATION'):
                response='该请求不在当前已验证的联合流程工具范围内；未新增工艺数值。请使用结构化任务和已准入的萃取工具。'
            else:
                patch=task_updates
                if patch is None:
                    legacy_patch=extract_patch(user_message,self.basis)
                    patch={'extraction_pressure_Pa':legacy_patch['feed']['pressure_kPa']*1000} if set(legacy_patch)=={'feed'} and set(legacy_patch['feed'])=={'pressure_kPa'} else {}
                if intent=='DESIGN_REVISION' and not patch:
                    response='未识别到明确的可更新字段，设计依据保持不变。可明确说“压力改为100 kPa”，其他字段请使用结构化任务。'
                else:
                    if patch:
                        # Full recalculation until fine-grained reuse is qualified.
                        raw=self.basis.model_dump();raw.update(patch);self.basis=ProcessDesignBasis.model_validate(raw)
                    response=self.run(message=user_message,intent=intent).report_markdown
            self.advisor_agent.add_user_message(user_message);self.advisor_agent.add_coach_message(response)
            self.add_response(response)
            return response

    def reset_conversation(self):
        family=self.basis.process_family
        MultiAgentOrchestrator.reset_conversation(self)
        self.state=None;self.runs.clear();self.basis=ProcessDesignBasis(process_family=family)

    @staticmethod
    def report(state):
        lines=['# SepMind 联合流程初步设计','',f'运行状态：{state.status}。以下区分已计算的萃取段与尚未验证的回收流程。','',
               '| 关卡 | 状态 | 说明 |','|---|---|---|']
        lines += [f'| {k} | {v.status} | {v.reason} |' for k,v in state.gates.items() if k!='G9']
        a=state.artifacts.get('explore_extraction_candidates')
        if a and a.status=='success':
            lines += ['','## 实际萃取候选','', '| 候选 | 接触级数 | S/F（质量比） | 萃取回收率 | 状态 |','|---|---:|---:|---:|---|']
            for r in a.data['candidates']:
                recovery=f"{r['raw']['solute_extraction_recovery']*100:.4f}%" if 'raw' in r else '未接受计算结果'
                lines.append(f"| {r['candidate_id']} | {r['stages']} | {r['solvent_feed_mass_ratio']} | {recovery} | {r['status']} |")
        if state.accepted_candidate_id:lines+=['',f'选定萃取候选：{state.accepted_candidate_id}。不是整套联合流程的完成状态。']
        if state.revision_history:
            lines+=['','## 计算反证与有界修正','',
                '原始目标不变；以下修改仅涉及设计变量，每次修改均重新检查分相、级联和独立校核。']
            lines += [f"- 修正 {r['revision']}：{r['action_id']}。{r['rationale']}" for r in state.revision_history]
        lines+=['','模型经过来源实验点筛查；相稳定性采用有限多起点检查，不是全局证明。稀释末端组成超出所用实验连线端点，属于明确保留的初步模型外推。',
                '完整产品纯度、溶剂再生与补加、能量、水力学及设备设计尚未验证，不提供虚构值。',
                '公开决策记录说明依据、工具与校验，不是模型私有思维链。']
        return '\n'.join(lines)


def create_engineering_orchestrator(basis=None,**kwargs):
    parsed=parse_process_basis(basis)
    return ProcessEngineeringOrchestrator(parsed,**kwargs) if isinstance(parsed,ProcessDesignBasis) else EngineeringOrchestrator(parsed,**kwargs)
