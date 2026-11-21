"""Matched PHA-derived teams: roles, generic reflection, expert decisions.

This evaluates explicit decisions over common atomic tools. It never calls the
production one-click verify_and_refine_column or imports accepted seed designs.
"""
import copy,hashlib,json,time
from pathlib import Path

from ..agents.orchestrator import EngineeringOrchestrator
from ..schemas import DesignState
from ..tools.atomic_recovery import (AtomicRecoveryRegistry,RecoveryAction,ExpertReport,
                                    REVISION_FIELDS,REVISION_ALWAYS,save)

ARMS=('roles','reflection','expert')
ROLES={
 'thermodynamics':'Review property-method applicability and phase/assumption evidence.',
 'calculation':'Review measured numerical residuals, product targets and the next useful calculation.',
 'process_advisor':'Review separation decisions, frozen requirements and economical use of the remaining computation budget.'}


def expert_context(tools):
    """Case-independent operational knowledge; no scenario labels or gold outputs."""
    context={'source':'SepMind explicit decision policy v1',
      'rules':['Numerical nonconvergence alone does not establish physical infeasibility.',
               'A converged column can still violate product targets; accept only native closure and original target checks.',
               'Use source-qualified model/phase evidence before asserting a method or route is applicable.',
               'Preserve user reflux constraints; trial design settings are hypotheses, not predicted performance.']}
    if tools.task_kind=='revision':
        context.update(field_dependency_knowledge={k:sorted(v) for k,v in REVISION_FIELDS.items()},
                       revision_bookkeeping=sorted(REVISION_ALWAYS),
                       policy='Invalidate artifacts whose numerical/qualification inputs change; retain unaffected artifacts and their source IDs.')
        return context,['submit_revision_plan','stop']
    if tools.task_kind=='admissibility':
        if tools.model_audit is not None and not tools.model_audit['admissible']:return context,['finish','stop']
        if tools.phase_audit is not None:return context,['finish','stop']
        # Phase audit itself runs the same model-domain guard. A separate model
        # audit is useful but is not an artificial mandatory extra operation.
        return context,['audit_model','audit_phase','stop']
    # Engineering recovery knowledge from the existing native resynthesis policy.
    # It guides action choice rather than providing an accepted candidate.
    nrtl=any((c.cas or c.canonical_id)=='7732-18-5' for c in tools.basis.components)
    if nrtl:
        context['repair_guidance']='For alcohol/water after CMO/MESH disagreement or solver failure, inspect the same backend equilibrium; re-screen at preserved reflux. If Rmin differs by over 10%, test an enthalpy-coupled initializer. A trial margin of two contacts per section is an existing preliminary policy, not an adequacy guarantee.'
        if tools.native is None:return context,['sample_native_vle','audit_model','audit_phase','stop']
        if tools.native_screen is None:return context,['screen_native','audit_model','audit_phase','stop']
        gap=abs(tools.native_screen['minimum_reflux_ratio']/tools.screen['minimum_reflux_ratio']-1)
        context['observed_Rmin_relative_difference']=gap
        context['suggested_initializer']='native_enthalpy' if gap>.1 else 'native_cmo'
    else:
        context['repair_guidance']='For an admitted near-ideal pair and a converged but under-separated column, a small stage/feed adjustment can be tested before requesting further thermodynamic calculations. The existing trial margin adds two contacts in each section (N+4, feed+2); verify the result, and investigate equilibrium if this trial fails.'
    return context,['audit_model','audit_phase','sample_native_vle','screen_native','simulate_column','stop']


class MechanismTeam(EngineeringOrchestrator):
    def __init__(self,*,arm,atomic_tools,backend,output_dir,max_calls=24,max_steps=8):
        if arm not in ARMS:raise ValueError('Unknown mechanism arm')
        super().__init__(basis=atomic_tools.basis,backend=backend,max_llm_calls=max_calls,output_dir=output_dir)
        self.arm=arm;self.atomic=atomic_tools;self.max_steps=max_steps
        self.state=DesignState(basis=self.basis,provider=backend.provider)
        self.messages=[];self.reports={};self.reflections=[];self.policy_records=[]

    def _context(self):
        t=self.atomic
        common={'task_kind':t.task_kind,'basis':t.basis.model_dump(),
            'goal':{'repair':'Recover a strictly valid column from the actual initial counterexample. Choose each diagnostic, design trial and initializer yourself.',
                    'admissibility':'Classify whether the requested model AND target interval are admitted under project evidence. Ground the final classification in executed audits. Do not design a column merely to answer this audit.',
                    'revision':'Submit which existing production tools should be recomputed after the explicit patch. Required fields must be covered; extra recomputation is penalized. This task scores a plan, not a revised physical design.'}[t.task_kind],
            'initial_screen':({k:t.screen[k] for k in ('theoretical_stages_rounded_up','feed_stage_from_top','reflux_ratio','minimum_reflux_ratio') if k in t.screen} if t.task_kind=='repair' else {}),
            'initial_counterexample':t.seed,'revision':t.revision,'tool_results':[{'tool':e['tool'],'status':e['status'],'data':e.get('data'),'error':e.get('error')} for e in t.events],
            'native_budget_remaining':t.native_budget-t.native_calls,
            'llm_requests_remaining':self.max_llm_calls-self.state.llm_calls,
            'tools':t.capabilities(),'specialist_reports':self.reports,
            'rules_for_all_arms':'Frozen feed, pressure and target cannot be relaxed. Trial R/N/feed are design hypotheses; all performance values require actual numerical tools. No automatic column repair is supplied. Baselines may independently reason, diagnose, revise and stop.',
            'coordination_for_all_arms':'Specialist reports are initial suggestions and may be outdated after a tool executes. Prioritize the latest observed tool feedback. Repeating an unchanged deterministic audit adds no new evidence. When enough audit evidence is available, submit your explicit classification using finish/stop or alongside the audit action.',
            'scope':'Binary q=1, uniform-pressure, equilibrium-stage preliminary research; no vendor/industrial certification.'}
        from ..knowledge import MODEL_CARDS
        cards=json.loads(MODEL_CARDS.read_text(encoding='utf8'))
        common['shared_model_reference_cards']=cards['cards']
        if t.task_kind=='revision':
            from ..tools.registry import EngineeringToolRegistry
            common['production_tools']=[{'name':name,'gate':gate} for name,(gate,_) in EngineeringToolRegistry.TOOLS.items()]
            common['revision_bookkeeping_required_for_all_arms']=sorted(REVISION_ALWAYS)
            common['revision_bookkeeping_execution']='The server automatically adds these bookkeeping updates for EVERY arm. Your plan should identify the physically affected production calculations; including bookkeeping explicitly is also allowed.'
            common['shared_production_tool_notes']={
                'parse_design_basis':'Normalize the currently submitted basis and provenance.',
                'check_design_specifications':'Validate independent user requirements and units.',
                'select_thermodynamic_model':'Qualify pair, selected method and pressure domain.',
                'resolve_property_parameters':'Load qualified property parameters and operating-domain evidence.',
                'calculate_binary_vle':'Calculate equilibrium from model, pair, pressure and composition interval.',
                'assess_separation_feasibility':'Review the target interval using the equilibrium artifact.',
                'calculate_material_balance':'Compute stream flows and splits from feed flow, compositions and targets.',
                'estimate_minimum_reflux':'Compute the operating-line envelope from equilibrium, composition targets and q.',
                'explore_reflux_candidates':'Compute stage and internal-flow tradeoffs from balance and equilibrium.',
                'select_process_design':'Record selected scheme and internal molar stream flows from computed candidates.',
                'calculate_mccabe_thiele_stages':'Compute stages/feed at selected R using the balance and equilibrium artifacts.',
                'verify_and_refine_column':'Production strictly verified column artifact; depends on feed, pressure, model, targets and selected design.',
                'calculate_energy_balance':'Compute duties and closure from the accepted strict-column artifact.',
                'estimate_column_equipment':'Compute tray/hydraulic estimates from native stage properties/loads and tray geometry.',
                'estimate_auxiliary_equipment':'Compute exchangers/utilities/pump estimates from duties, geometry and utility conditions.',
                'check_design_consistency':'Review consistency against the current requirements and evidence.',
                'render_preliminary_design_report':'Render the current version and retained evidence.'}
        if self.arm=='reflection':common['generic_reflection_memory']=self.reflections
        if self.arm=='expert':
            knowledge,allowed=expert_context(t);common['expert_decision_knowledge']=knowledge
        else:allowed=list(t.DESCRIPTIONS)
        if t.task_kind=='revision':allowed=[x for x in allowed if x in ('submit_revision_plan','stop')]
        if t.task_kind=='admissibility':allowed=[x for x in allowed if x in ('audit_model','audit_phase','finish','stop','sample_native_vle','simulate_column')]
        common['admissible_next_tools']=allowed
        return common

    def _ask(self,role,schema,context):
        for correction in range(2):
            # Snapshot before serializing the actual HTTP prompt. Later role
            # reports and reflection memory must not rewrite earlier logs.
            context=copy.deepcopy(context)
            if self.state.llm_calls>=self.max_llm_calls:raise ValueError('LLM_BUDGET: episode limit')
            self.state.llm_calls+=1
            definition=schema.model_json_schema()
            if schema is RecoveryAction:
                definition['properties']['tool']['enum']=context['admissible_next_tools']
                if self.atomic.task_kind=='admissibility':
                    keep={'tool','rationale','classification'}
                    definition['properties']={k:v for k,v in definition['properties'].items() if k in keep}
                    definition['required']=sorted(set(definition.get('required',[]))|{'classification'})
                    definition['properties']['classification']['description']='Required. A non-unknown classification is your final answer, which may accompany an audit action or finish/stop. It must be supported by the executed evidence. Use unknown only while still diagnosing.'
                if self.atomic.task_kind=='revision':
                    keep={'tool','rationale','recompute_tools'}
                    definition['properties']={k:v for k,v in definition['properties'].items() if k in keep}
                    definition['properties']['recompute_tools']={'type':'array','items':{'type':'string','enum':[v['name'] for v in context['production_tools']]},'maxItems':17}
                    definition['required']=sorted(set(definition.get('required',[]))|{'recompute_tools'})
                if self.atomic.task_kind=='repair':
                    definition['properties'].pop('recompute_tools',None)
                    definition['properties'].pop('classification',None)
            prompt=('You are the '+role+' in a PHA-derived chemical separation design team. '
                +ROLES.get(role,'Integrate the evidence and choose one defensible next action. You may independently diagnose failures and revise previous choices.')+
                ' Return one JSON object matching the schema. Provide concise public observations and a testable next action, not an internal thought transcript.\n'
                +json.dumps({'context':context,'output_schema':definition},ensure_ascii=False))
            started=time.monotonic();raw=None;metadata={}
            try:
                raw=self._backend.generate(prompt);metadata=copy.deepcopy(self._backend.last_response_info or {})
                result=schema.model_validate_json(self._clear_json_format(raw))
                if isinstance(result,RecoveryAction) and result.tool not in context['admissible_next_tools']:
                    raise ValueError('ACTION_PRECONDITION: tool outside declared next-action set')
                if isinstance(result,RecoveryAction) and self.atomic.task_kind=='admissibility' and result.tool in ('finish','stop') and result.classification=='unknown':
                    raise ValueError('CLASSIFICATION_REQUIRED: final classification must be explicit: admissible, unsupported_model, or infeasible_under_model; select it from executed evidence')
                entry={'role':role,'context':context,'response':raw,'metadata':metadata,'elapsed_s':time.monotonic()-started,'valid':True,
                       'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),'context_log_version':2}
                self.messages.append(entry);self.state.provider_events.append(metadata)
                save(self.output_dir/'llm_messages.json',self.messages)
                return result
            except (ValueError,RuntimeError) as exc:
                if raw is not None:self.state.provider_events.append(metadata)
                self.messages.append({'role':role,'context':context,'response':raw,'metadata':metadata,
                    'elapsed_s':time.monotonic()-started,'valid':False,'error':str(exc)[:1500],
                    'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),'context_log_version':2})
                save(self.output_dir/'llm_messages.json',self.messages)
                if correction or isinstance(exc,RuntimeError):raise
                context={**context,'structured_correction':str(exc)[:1500],
                         'correction_instruction':'Use only the exact tool names in admissible_next_tools: '+json.dumps(context['admissible_next_tools'])}

    def run_episode(self):
        started=time.monotonic();error=None;final=None
        try:
            # All three arms consult precisely the same actual core roles once.
            for role in ROLES:
                report=self._ask(role,ExpertReport,self._context())
                self.reports[role]=report.model_dump()
            for step in range(self.max_steps):
                if time.monotonic()-started>1200:raise TimeoutError('Episode wall-time budget reached')
                if self.arm=='reflection':
                    reflection=self._ask('reflector',ExpertReport,{**self._context(),
                        'reflection_task':'Review observed feedback and your earlier actions. State a concise evidence-grounded lesson and propose the next test. Do not presume a failure cause without evidence.'})
                    self.reflections.append(reflection.model_dump())
                context=self._context()
                if self.arm=='expert':self.policy_records.append({'step':step,'knowledge':context['expert_decision_knowledge'],'allowed_tools':context['admissible_next_tools']})
                action=self._ask('supervisor',RecoveryAction,context)
                event=self.atomic.execute(action)
                if self.atomic.accepted is not None:final={'strict_recovery':True};break
                if action.tool=='submit_revision_plan' and event['status']=='success':final=event['data'];break
                if self.atomic.task_kind=='admissibility' and event['status']=='success' and action.classification!='unknown':
                    final={'classification':action.classification};break
                if action.tool in ('finish','stop'):final=event.get('data');break
        except (ValueError,RuntimeError,TimeoutError) as exc:error=type(exc).__name__+': '+str(exc)[:1500]
        t=self.atomic;success=False
        if t.task_kind=='repair':success=t.accepted is not None
        elif t.task_kind=='admissibility' and final:
            # All groups need the same executed evidence. The expected label is
            # held by the runner and NOT sent to this team.
            classification=final.get('classification')
            evidence=(t.model_audit is not None and not t.model_audit['admissible'] and classification=='unsupported_model'
                      or t.phase_audit is not None and classification==t.phase_audit['classification'])
            success=bool(evidence)
        elif t.task_kind=='revision' and final:success=bool(final.get('coverage_passed'))
        result={'arm':self.arm,'task_kind':t.task_kind,'provider':self._backend.provider,
            'requested_model':self._backend.model_name,'strict_recovery':t.accepted is not None,
            'evidence_supported_endpoint':success,'final':final,'error':error,'elapsed_s':time.monotonic()-started,
            'llm_calls':self.state.llm_calls,'native_calls':t.native_calls,'column_attempts':t.column_attempts,
            'tool_calls':len(t.events),'failed_tool_calls':sum(e['status']=='failed' for e in t.events),
            'usage':{k:sum(e.get('usage',{}).get(k,0) for e in self.state.provider_events) for k in ('prompt_tokens','completion_tokens','total_tokens')},
            'served_models':sorted({e['served_model'] for e in self.state.provider_events if e.get('served_model')}),
            'accepted':t.accepted,'policy_records':self.policy_records,
            'success_within_additional_native_budget':{str(k):bool(t.accepted and t.native_calls<=k) for k in (1,2,3,4)},
            'reflections':self.reflections,'public_reports':self.reports,
            'scope':'Research decision-policy endpoint; revision is plan-only, repair is independently checked native performance.'}
        save(self.output_dir/'result.json',result)
        return result
