import json, time, random
from pathlib import Path
from typing import Literal
from pydantic import Field
from sepmind.engineering.schemas import Contract
from sepmind.engineering.agents.orchestrator import EngineeringOrchestrator
from sepmind.llm.backend_multimodel import DeepSeekBackend
from .config import task_basis, knowledge, digest
from .initialization import EVIDENCE_POLICY, LEGACY_POLICY, POLICY_DIRECTORY, POLICIES, profile_capabilities
from .tools import Meter, Tools, prepare, BudgetExceeded
from .logging import Ledger, save
from .evaluator import evaluate
from .stopping import product_targets_met

class Action(Contract):
    tool: Literal['audit_model','audit_phase','sample_native_vle','screen_native','simulate_column','review','finish','stop']
    rationale: str=Field(min_length=1,max_length=1800)
    equilibrium_stages: int|None=Field(default=None,ge=3,le=200)
    feed_stage: int|None=Field(default=None,ge=1,le=199)
    reflux_factor: float=Field(default=1.,ge=1.,le=2.)
    profile: Literal['default','native_cmo','native_enthalpy']='default'
    skill_id: str|None=None
    evidence_id: str|None=None
    claim_success: bool=False

class Plan(Contract):
    steps: list[str]=Field(min_length=1,max_length=10)
    update_reason: str=Field(min_length=1,max_length=1500)

class Report(Contract):
    observation: str=Field(min_length=1,max_length=1500)
    recommendation: str=Field(min_length=1,max_length=1500)

MAPPING={'audit_model':('G2','resolve_property_parameters','thermodynamics'),
    'audit_phase':('G1','assess_separation_feasibility','thermodynamics'),
    'sample_native_vle':('G1','calculate_binary_vle','thermodynamics'),
    'screen_native':('G4','calculate_mccabe_thiele_stages','process_advisor'),
    'simulate_column':('G4','verify_and_refine_column','process_advisor'),
    'review':('G4','verify_and_refine_column','process_advisor')}

class Episode(EngineeringOrchestrator):
    """PHA-derived research controller; production class and defaults untouched."""
    def __init__(self,case,arm,limits,folder,seed,model='deepseek-flash',backend=None, *,
                 controller_policy=LEGACY_POLICY, stop_at_first_target=False):
        if controller_policy not in POLICIES:
            raise ValueError(f'Unknown controller policy: {controller_policy}')
        basis,provenance=task_basis(case)
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        self.ledger=Ledger(self.folder/'events.jsonl');self.meter=Meter(limits)
        self.case,self.arm,self.seed,self.model=case,arm,seed,model
        self.random=random.Random(seed);self.source=provenance
        self.provider_backend=backend or DeepSeekBackend(model_name=model,temperature=.2,
            max_tokens=limits.max_output_tokens,json_mode=True,timeout_s=limits.llm_timeout_s,thinking=False)
        super().__init__(basis=basis,backend=self.provider_backend,max_llm_calls=limits.llm,
            output_dir=self.folder/'pha_snapshots')
        self.shared_knowledge=knowledge();self.messages=[];self.observations=[]
        self.controller_policy = controller_policy
        self.stop_at_first_target = stop_at_first_target
        self.policy_prompt = ''
        if controller_policy == EVIDENCE_POLICY:
            supplement = POLICY_DIRECTORY/'INITIALIZATION_RECOVERY_SKILL.md'
            self.shared_knowledge['protocol_skill_supplement'] = {
                'skill_id':'rigorous_counterexample_redesign', 'sha256':digest(supplement),
                'procedure':supplement.read_text(encoding='utf8')}
            self.policy_prompt = (POLICY_DIRECTORY/'BINARY_EVIDENCE_PROMPT.md').read_text(encoding='utf8')
        self.invalid_decisions=0;self.invalid_claims=0;self.roles=[];self.tools=None
        save(self.folder/'input.json',{'case':case,'basis':basis.model_dump(),'source':provenance,
            'arm':arm.__dict__,'limits':limits.__dict__,'local_seed':seed,'controller_policy':controller_policy,
            'provider_seed':None,'provider_seed_reason':'Retained DeepSeek backend exposes no sampling seed',
            'stop_at_first_target':stop_at_first_target})

    def target_submission_action(self):
        if not getattr(self, 'stop_at_first_target', False):
            return None
        tools = self.tools
        if tools.last_id is None or tools.failure == 'solver_failure':
            return None
        entry = tools.records.get(tools.last_id)
        if entry is None or not product_targets_met(entry['record'], self.basis.target):
            return None
        if not self.arm.review:
            return 'finish'
        review = tools.last_review
        if not review or review['evidence_id'] != tools.last_id:
            return 'review'
        return 'finish' if review['passed'] else None

    def eligible(self):
        submission = self.target_submission_action()
        if submission:
            return [submission]
        t=self.tools
        allowed=['audit_model','audit_phase','sample_native_vle','screen_native','simulate_column','finish','stop']
        if self.arm.review:allowed.append('review')
        # Physical input dependencies remain in every arm, not an ablation.
        if t.native is None:allowed.remove('screen_native')
        if self.arm.review and t.last_id and (not t.last_review or t.last_review['evidence_id']!=t.last_id):
            if t.failure!='solver_failure':
                return ['review'] if getattr(self,'controller_policy',LEGACY_POLICY)==EVIDENCE_POLICY else ['review','stop']
        if self.arm.classified_revision:
            if t.failure=='solver_failure':
                if t.native is None:return ['sample_native_vle','audit_model','audit_phase','stop']
                if t.native_screen is None:return ['screen_native','audit_model','audit_phase','stop']
            if t.failure=='property_evidence':return ['audit_model','audit_phase','stop']
        return allowed

    def skills_for(self,tool):
        if tool not in MAPPING:return []
        gate,mapped,owner=MAPPING[tool]
        context=self.thermodynamics_agent.skills.context(self.tools.prepared_state,gate,mapped,owner)
        return [s['skill_id'] for s in context['eligible_skills']]

    def context(self):
        t=self.tools
        ids=list(t.records)
        routing={tool:self.skills_for(tool) for tool in MAPPING} if self.arm.expert else {}
        recent=self.observations[-12:]
        context={'task':self.basis.model_dump(),'common_computed_screen':t.screen,
            'stage_scope':'Binary strict-column design, unchanged original requirements, no equipment endpoint.',
            'knowledge':self.shared_knowledge,'observations':recent,
            'executed_record_ids':ids,'latest_executed_id':t.last_id,
            'last_submitted_design_action':t.last_action,
            'tools':{k:v for k,v in t.DESCRIPTIONS.items() if k not in ['submit_revision_plan','finish','stop']},
            'special_tools':{'finish':'Submit an actually executed evidence_id (latest if omitted); claim_success is your conclusion.',
                'review':'Internal independent review (available only if listed in allowed actions).',
                'stop':'Stop without a completed design.'},
            'common_ranges':{'N':[3,self.basis.column.max_stages],'feed':'1..N-1',
                'reflux_factor':[1,2],'fixed_reflux_requires_factor_1':bool(self.basis.column.reflux_multiplier or self.basis.column.reflux_ratio),
                'profiles':['default','native_cmo','native_enthalpy']},
            'budget':{'llm_remaining':self.meter.limits.llm-self.meter.llm,
                'tools_remaining':self.meter.limits.tools-self.meter.tools,
                'native_remaining':self.meter.limits.native-self.meter.native,
                'strict_remaining':self.meter.limits.columns-self.meter.columns,
                'vle_remaining':self.meter.limits.vle-self.meter.vle},
            'allowed_actions':self.eligible() if self.stop_at_first_target or self.arm.expert or self.arm.review or self.arm.classified_revision else
                ['audit_model','audit_phase','sample_native_vle','screen_native','simulate_column','finish','stop'],
            'mandatory_skill_bindings':routing,
            'previous_invalid_decisions':self.invalid_decisions}
        if self.arm.classified_revision:
            context['failure_classification']=t.failure
            context['revision_policy']='Solver failure: diagnose same-backend equilibrium/initialization; off-spec converged design: revise design then recalculate; missing property evidence: audit/stop. No solver failure proves physical infeasibility.'
        else:context['revision_policy']='Generic retry: inspect observations and propose another legal action or stop within the same budget. No machine-classified correction recommendation.'
        if self.arm.review:context['internal_review_status']=t.last_review
        if self.arm.expert:context['stage_policy']='Select a binding eligible skill_id for physical actions; use its prerequisites and evidence tests. Review each returned latest column before submission.' if self.arm.review else 'Select a binding eligible skill_id for physical actions. No internal reviewer is enabled in this ablation.'
        if self.stop_at_first_target:
            submission = self.target_submission_action()
            if submission:
                context['target_submission_gate'] = {
                    'validated_scope': 'native convergence and original product targets only',
                    'evidence_id': t.last_id, 'required_action': submission,
                }
        if self.controller_policy == EVIDENCE_POLICY:
            context['initialization_profiles'] = profile_capabilities(t.native)
            context['initialization_native_evidence_id'] = t.native.get('evidence_id') if t.native else None
            if self.arm.classified_revision:
                context['revision_policy'] += (
                    ' Missing prerequisites for the requested numerical seed permit a single bounded seed change '
                    'while preserving the original design and physical model. Inspect the recorded effective profile.')
            if self.arm.review and t.last_id:
                current = t.last_review if t.last_review and t.last_review['evidence_id']==t.last_id else None
                if current is not None:
                    status = 'reviewed_pass' if current['passed'] else 'reviewed_fail'
                else:
                    status = 'awaiting_review' if context['allowed_actions']==['review'] else 'earlier_record'
                context['latest_column_review'] = {'evidence_id':t.last_id, 'status':status}
                context['internal_review_status'] = current
                suggestion = t.reviewed_redesign()
                if suggestion is not None:
                    context['reviewed_redesign_candidate'] = suggestion
        return context

    def ask(self,role,schema,extra=None):
        self.meter.request()
        prompt='You are SepMind research '+role+'. Return one JSON object, no private chain-of-thought; give concise engineering grounds. Do not invent computed properties or performance. Use actual tools and immutable requirements. No Python/code execution. Finish only by submitting an executed column. All trial N/feed/reflux are hypotheses, not known correct answers.\n'
        if self.policy_prompt:
            prompt += self.policy_prompt + '\n'
        if self.stop_at_first_target:
            prompt += ('The objective is to submit the first feasible design. Once the target submission '
                       'gate is active, take its required action for its exact evidence ID. '
                       'Do not request new calculations or optimize an on-spec candidate.\n')
        prompt+=json.dumps({'context':self.context(),'handoff':extra,'output_schema':schema.model_json_schema()},ensure_ascii=False)
        self.add_user_message(prompt)
        self.ledger.emit('llm_start',request_index=self.meter.llm,role=role,prompt=prompt)
        start=time.monotonic();raw=None
        try:
            raw=self.provider_backend.generate(prompt)
            metadata=getattr(self.provider_backend,'last_response_info',None) or {}
            metadata={k:v for k,v in metadata.items() if k in ['provider','requested_model','served_model','request_id','response_id','usage']}
            self.messages.append(metadata)
            self.add_response(raw);self.roles.append(role)
            self.ledger.emit('llm_end',request_index=self.meter.llm,role=role,response=raw,
                metadata=metadata,duration_s=time.monotonic()-start)
            return schema.model_validate_json(self._clear_json_format(raw))
        except Exception as exc:
            if raw is None:self.ledger.emit('llm_error',request_index=self.meter.llm,role=role,
                error=type(exc).__name__+': '+str(exc)[:500],duration_s=time.monotonic()-start)
            raise

    def next_action(self):
        topology=self.arm.topology
        if topology=='react':return self.ask('single Reason–Act–Observe agent',Action)
        if topology=='planner_executor':
            plan=self.ask('Planner updating the plan from current observations',Plan)
            return self.ask('Executor selecting the next actual action',Action,{'planner':plan.model_dump()})
        if topology=='multi_agent':
            thermo=self.ask('thermodynamics expert',Report)
            proposal=self.ask('engineering design expert',Action,{'thermodynamics':thermo.model_dump()})
            return self.ask('results analysis expert integrating the team action',Action,
                {'thermodynamics':thermo.model_dump(),'engineering':proposal.model_dump()})
        return self.ask('expert stage coordinator',Action)

    def validate_action(self,a):
        submission = self.target_submission_action()
        if submission and (a.tool != submission or a.evidence_id not in (None, self.tools.last_id)):
            raise ValueError('TARGET_SUBMISSION_PRECONDITION: complete review or submission for the current on-spec result')
        if self.arm.expert or self.arm.review or self.arm.classified_revision:
            if a.tool not in self.eligible():raise ValueError('STAGE_PRECONDITION: action not eligible at current evidence stage')
        if self.arm.expert and a.tool in MAPPING and a.skill_id not in self.skills_for(a.tool):
            raise ValueError('SKILL_PRECONDITION: an applicable runtime Skill identity is required')
        if (getattr(self,'controller_policy',LEGACY_POLICY)==EVIDENCE_POLICY and a.tool=='review'
                and self.eligible()==['review'] and a.evidence_id not in (None,self.tools.last_id)):
            raise ValueError('REVIEW_PRECONDITION: review the latest executed column evidence')
        if a.tool=='finish' and self.arm.review:
            rid=a.evidence_id or self.tools.last_id
            if not self.tools.last_review or self.tools.last_review['evidence_id']!=rid or not self.tools.last_review['passed']:
                raise ValueError('REVIEW_PRECONDITION: selected column has no passing internal independent review')
        if a.tool=='simulate_column' and self.arm.classified_revision and self.tools.failure=='solver_failure':
            if a.profile=='default' and self.tools.native is not None:
                raise ValueError('REVISION_PRECONDITION: solver failure requires using diagnosed native initialization, not unchanged default retry')

    def run_episode(self):
        started=time.monotonic();terminal='unfinished';error=None;final=None;selected=None;claimed=False;steps=0
        try:
            state,screen=prepare(self.basis,self.folder/'preparation',self.meter,self.ledger)
            self.tools=Tools(self.basis,screen,self.folder/'tools',self.meter,self.ledger,self.arm,state,
                             controller_policy=self.controller_policy)
            for steps in range(1,self.meter.limits.actions+1):
                self.meter.wall()
                try:
                    a=self.next_action()
                    self.ledger.emit('decision',step=steps,action=a.model_dump())
                    self.validate_action(a)
                except BudgetExceeded:raise
                except ValueError as exc:
                    self.invalid_decisions+=1
                    self.observations.append({'tool':'decision','status':'invalid','error':str(exc)[:1200]})
                    self.ledger.emit('invalid_decision',step=steps,error=str(exc)[:1500]);continue
                if a.tool=='stop':terminal='stopped';break
                if a.tool=='finish':
                    rid=a.evidence_id or self.tools.last_id
                    claimed=a.claim_success;final=a.model_dump();selected=rid
                    terminal='submitted';break
                event=self.tools.execute_action(a,a.evidence_id)
                # Numeric raw streams are retained in full in the JSONL. Limit
                # only prompt history, never the raw evidence or data files.
                obs=json.loads(json.dumps(event))
                if 'outputs' in obs.get('data',{}):
                    out=obs['data']['outputs'];out.pop('stage_profiles',None)
                    temperatures=out.pop('stage_temperatures_K',None)
                    if temperatures:out['temperature_range_K']=[min(temperatures),max(temperatures)]
                self.observations.append(obs)
                submission = self.target_submission_action()
                if submission:
                    self.ledger.emit('target_submission_gate', required_action=submission,
                                     evidence_id=self.tools.last_id)
            else:terminal='budget_exhausted';error='BUDGET_EXHAUSTED: action attempts'
        except BudgetExceeded as exc:terminal='budget_exhausted';error=str(exc)
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)[:2000]
            terminal='provider_failure' if any(x in error for x in ['DeepSeek','HTTP','connection','completion']) else 'environment_or_worker_failure'
            self.ledger.emit('episode_error',terminal=terminal,error=error)
        method_s=time.monotonic()-started
        external_started=time.monotonic();endpoint_reviews=[]
        if self.tools:
            for event in self.tools.column_events:
                if event['status']=='not_launched':continue
                review=evaluate(self.tools.records[event['evidence_id']]['record'],self.basis,self.tools.screen['reflux_ratio']) if event.get('evidence_id') else {'passed':False,'solver_failure':True}
                endpoint_reviews.append({**event,'external_review':review})
        selected_record=self.tools.records.get(selected) if self.tools and selected else None
        final_review=evaluate(selected_record['record'],self.basis,self.tools.screen['reflux_ratio']) if selected_record else {'passed':False,'missing_final_record':True}
        self.ledger.emit('external_evaluation',selected_evidence_id=selected,final_review=final_review,
            all_attempts=endpoint_reviews,not_returned_to_agent=True)
        first_failed=not endpoint_reviews[0]['external_review']['passed'] if endpoint_reviews else None
        success=bool(terminal=='submitted' and final_review['passed'])
        usage_known={k:sum(m.get('usage',{}).get(k,0) for m in self.messages) for k in ['prompt_tokens','completion_tokens','total_tokens']}
        usage_complete=len(self.messages)==self.meter.llm and all('total_tokens' in m.get('usage',{}) for m in self.messages)
        usage=usage_known if usage_complete else {k:None for k in usage_known}
        row={'case':self.case,'arm':self.arm.id,'seed':self.seed,'terminal':terminal,'error':error,
            'verified_success':success,'claimed_success':claimed,'false_acceptance':bool(claimed and not success),
            'first_strict_failed':first_failed,'recovered':bool(success and first_failed is True),
            'llm_requests':self.meter.llm,'usage':usage,'usage_known':usage_known,'usage_complete':usage_complete,'tool_calls':self.meter.tools,
            'native_calls':self.meter.native,'strict_calls':self.meter.columns,'vle_calls':self.meter.vle,
            'method_time_s':method_s,'simulation_time_s':self.meter.simulation_s,
            'preparation_time_s':self.meter.preparation_s,'external_eval_time_s':time.monotonic()-external_started,
            'revision_count':max(0,self.meter.columns-1),'invalid_decisions':self.invalid_decisions,
            'fixed_constraint_violations':sum(e['external_review'].get('fixed_violations',0) or 0 for e in endpoint_reviews),
            'recalculation_tools':self.meter.recalculation_tools,'recalculation_native':self.meter.recalculation_native,
            'recalculation_time_s':self.meter.recalculation_s,
            'retained_artifact_references':len(self.tools.reused_artifacts) if self.tools else 0,
            'measured_selective_time_saved_s':None,
            'served_models':sorted({m.get('served_model') for m in self.messages if m.get('served_model')}),
            'endpoint_reviews':endpoint_reviews,'final':final,'selected_evidence_id':selected,
            'final_record_file':selected_record['path'] if selected_record else None,'external_review':final_review,
            'directory':str(self.folder),'phase':'unset','stop_at_first_target':self.stop_at_first_target}
        save(self.folder/'result.json',row);self.ledger.emit('episode_end',result=row)
        return row
