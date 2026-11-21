"""Instrumented reuse of existing tools, with review/repair boundaries explicit."""
from dataclasses import asdict
from pathlib import Path
import json, time
from sepmind.engineering.tools.atomic_recovery import AtomicRecoveryRegistry, RecoveryAction
from sepmind.engineering.tools.registry import EngineeringToolRegistry
from sepmind.engineering.agents.orchestrator import EngineeringOrchestrator
from sepmind.engineering.design.rigorous import COMPOUNDS, product_checks
from sepmind.engineering.design.binary import material_balance
from sepmind.simulation.dwsim import DwsimBackend, RigorousColumnRequest
from .initialization import EVIDENCE_POLICY, LEGACY_POLICY, InitializationEvidenceMissing, profile_capabilities
from .logging import save

class BudgetExceeded(RuntimeError):
    pass

class Meter:
    def __init__(self, limits):
        self.limits=limits;self.llm=0;self.tools=0;self.native=0;self.columns=0;self.vle=0
        self.simulation_s=0.;self.preparation_s=0.;self.recalculation_s=0.
        self.recalculation_tools=0;self.recalculation_native=0;self.start=time.monotonic()
    def wall(self):
        if time.monotonic()-self.start>=self.limits.episode_timeout_s:
            raise BudgetExceeded('BUDGET_EXHAUSTED: episode wall time')
    def tool(self):
        self.wall()
        if self.tools>=self.limits.tools:raise BudgetExceeded('BUDGET_EXHAUSTED: registered/atomic tools')
        self.tools+=1
    def request(self):
        self.wall()
        if self.llm>=self.limits.llm:raise BudgetExceeded('BUDGET_EXHAUSTED: LLM requests')
        self.llm+=1
    def native_call(self,kind):
        self.wall()
        attr='columns' if kind=='rigorous_column' else 'vle'
        cap=self.limits.columns if attr=='columns' else self.limits.vle
        if self.native>=self.limits.native or getattr(self,attr)>=cap:
            raise BudgetExceeded('BUDGET_EXHAUSTED: '+kind)
        self.native+=1;setattr(self,attr,getattr(self,attr)+1)

class MeasuredBackend:
    def __init__(self,meter,ledger,backend=None):
        self.meter=meter;self.ledger=ledger
        self.backend=backend or DwsimBackend(timeout_s=meter.limits.native_timeout_s)
    def _call(self,kind,request):
        self.meter.native_call(kind)
        index=self.meter.native
        self.ledger.emit('native_start',index=index,action=kind,request=asdict(request))
        t=time.monotonic()
        try:
            result=getattr(self.backend,kind)(request)
            if not str(result.get('version','')).startswith('DWSIM version 9.0.5'):
                raise RuntimeError('ENVIRONMENT_ERROR: native version is not DWSIM 9.0.5')
            self.ledger.emit('native_end',index=index,action=kind,status='returned',
                evidence_id=result.get('evidence_id'),duration_s=time.monotonic()-t)
            return result
        except Exception as exc:
            self.ledger.emit('native_end',index=index,action=kind,status='failed',
                error=type(exc).__name__+': '+str(exc)[:2000],duration_s=time.monotonic()-t)
            raise
        finally:self.meter.simulation_s+=time.monotonic()-t
    def rigorous_column(self,request):return self._call('rigorous_column',request)
    def binary_vle(self,request):return self._call('binary_vle',request)

class MeasuredPreparationRegistry(EngineeringToolRegistry):
    def __init__(self,meter,ledger):self.meter=meter;self.ledger=ledger
    def execute(self,name,state,gate,arguments):
        self.meter.tool();start=time.monotonic()
        self.ledger.emit('tool_start',tool=name,stage='common_preparation',gate=gate,arguments=arguments)
        result=super().execute(name,state,gate,arguments)
        self.ledger.emit('tool_end',tool=name,stage='common_preparation',duration_s=time.monotonic()-start,
            result=result.model_dump())
        return result

def prepare(basis,folder,meter,ledger):
    start=time.monotonic()
    team=EngineeringOrchestrator(basis=basis,backend=None,
        registry=MeasuredPreparationRegistry(meter,ledger),output_dir=Path(folder)/'screen_snapshots')
    state=team.run(message='Frozen binary task: common deterministic screening only.')
    meter.preparation_s+=time.monotonic()-start
    stage=state.artifacts.get('calculate_mccabe_thiele_stages')
    save(Path(folder)/'screen_state.json',state.model_dump())
    if stage is None or stage.status!='success':
        raise RuntimeError('PROPERTY_OR_SCREENING_FAILURE: '+str(state.questions)+str(state.status))
    return state,stage.data

class Tools(AtomicRecoveryRegistry):
    def __init__(self,basis,screen,folder,meter,ledger,arm,prepared_state, *, controller_policy=LEGACY_POLICY):
        super().__init__(basis,screen,folder,native_budget=meter.limits.native,
            backend=MeasuredBackend(meter,ledger))
        self.meter=meter;self.ledger=ledger;self.arm=arm;self.prepared_state=prepared_state
        self.records={};self.record_actions={};self.last_id=None;self.last_review=None
        self.last_action=None;self.failure=None;self.column_events=[];self.reused_artifacts=[]
        self.controller_policy = controller_policy
        self.effective_initialization = None
        self.record_profiles = {}

    def sample_native(self):
        result = super().sample_native()
        if self.controller_policy == EVIDENCE_POLICY:
            profiles = profile_capabilities(self.native)
            result.update(enthalpies_available=profiles['native_enthalpy']['available'],
                          initialization_profiles=profiles)
        return result

    def initial_profile(self, action):
        if self.controller_policy != EVIDENCE_POLICY:
            return super().initial_profile(action)
        requested = action.profile
        capabilities = profile_capabilities(self.native)
        effective = requested
        reason = None
        native_id = self.native.get('evidence_id') if self.native else None
        if not capabilities[requested]['available']:
            reason = f'{requested} requires {capabilities[requested]["requires"]}'
            if not self.arm.classified_revision:
                self.ledger.emit('initialization_selection', requested=requested, effective=None,
                                 reason=reason, native_evidence_id=native_id)
                raise InitializationEvidenceMissing('INITIALIZATION_EVIDENCE: '+reason)
            effective = 'native_cmo' if capabilities['native_cmo']['available'] else 'default'
        try:
            seed = super().initial_profile(action.model_copy(update={'profile':effective}))
        except ValueError as exc:
            if not (self.arm.classified_revision and effective == 'native_enthalpy'
                    and str(exc).startswith('INITIALIZATION_FAILED:')):
                raise
            reason = str(exc)
            effective = 'native_cmo'
            seed = super().initial_profile(action.model_copy(update={'profile':effective}))
        self.ledger.emit('initialization_selection', requested=requested, effective=effective,
                         reason=reason, native_evidence_id=native_id,
                         equilibrium_stages=action.equilibrium_stages, feed_stage=action.feed_stage,
                         reflux_factor=action.reflux_factor)
        self.effective_initialization = effective
        return seed

    def reviewed_redesign(self):
        """Propose one fixed-reflux stage-margin trial after a closed off-spec column."""
        review = self.last_review
        if (self.controller_policy != EVIDENCE_POLICY or not self.arm.classified_revision or not review
                or review['evidence_id'] != self.last_id or self.failure != 'product_off_spec'
                or not (review['physical'] and review['material_and_energy_closure']
                        and review['frozen_user_inputs_preserved'])):
            return None
        resample = not self.arm.dependency_reuse and self.native is not None
        if (self.meter.columns >= self.meter.limits.columns
                or self.meter.native+1+resample > self.meter.limits.native
                or (resample and self.meter.vle >= self.meter.limits.vle)):
            return None
        action = self.record_actions[self.last_id]
        # The reused preliminary strict design uses a two-stage allowance in
        # each column section to test CMO/MESH differences (rigorous.py).
        added = min(4, self.basis.column.max_stages-action['equilibrium_stages'])
        if added <= 0:
            return None
        candidate = {'equilibrium_stages':action['equilibrium_stages']+added,
                     'feed_stage':action['feed_stage']+added//2, 'reflux_factor':action['reflux_factor']}
        if any(all(prior[k]==v for k,v in candidate.items()) for prior in self.record_actions.values()):
            return None
        candidate['profile'] = self.record_profiles[self.last_id]
        return {'evidence_id':self.last_id, 'failed_targets':[k for k,v in review['strict_targets'].items() if not v],
            'candidate':candidate,
            'scope':'Unverified stage-margin trial at the same reflux, requiring strict calculation and review'}
    def _consume_native(self):
        # Meter at the actual backend boundary; denied launch is not a solve.
        self.native_calls=self.meter.native+1
    def rescreen_full(self):
        start=time.monotonic();before_t=self.meter.tools;before_n=self.meter.native
        state,_=prepare(self.basis,self.folder/f'recalculation-{self.meter.columns+1:02d}',self.meter,self.ledger)
        if self.native is not None:
            self.meter.tool()
            self.ledger.emit('tool_start',tool='sample_native_vle',stage='full_recalculation',arguments={})
            result=self.sample_native()
            self.ledger.emit('tool_end',tool='sample_native_vle',stage='full_recalculation',status='success',data=result)
        self.meter.recalculation_tools+=self.meter.tools-before_t
        self.meter.recalculation_native+=self.meter.native-before_n
        self.meter.recalculation_s+=time.monotonic()-start
        self.ledger.emit('dependency_recalculation',mode='full',tool_calls=self.meter.tools-before_t,
            native_calls=self.meter.native-before_n,duration_s=time.monotonic()-start,
            recomputed_ids=[a.artifact_id for a in state.artifacts.values()])
    def simulate(self,action):
        # Reuse existing validated profile and request adapters, WITHOUT hidden
        # runtime product_checks, automatic candidate changes or acceptance.
        if action.equilibrium_stages is None or action.feed_stage is None:
            raise ValueError('INPUT_MISSING: explicit N/feed required')
        if not 1<=action.feed_stage<action.equilibrium_stages<=self.basis.column.max_stages:
            raise ValueError('INPUT_INVALID: stage/feed outside common range')
        if not self.audit_model()['admissible']:raise ValueError('MODEL_PRECONDITION: qualified parameters required')
        r=self._reflux(action.reflux_factor)
        if self.last_action is not None:
            if self.arm.dependency_reuse:
                ids=[a.artifact_id for a in self.prepared_state.artifacts.values()]
                self.reused_artifacts.extend(ids)
                self.ledger.emit('dependency_recalculation',mode='selective',retained_ids=ids,
                    native_equilibrium_retained=self.native.get('evidence_id') if self.native else None,
                    measured_time_saved_s=None)
            else:self.rescreen_full()
        profile,source=self.initial_profile(action)
        b=material_balance(self.basis);nrtl=self.basis.thermodynamic_model=='NRTL'
        request=RigorousColumnRequest(
            tuple(COMPOUNDS[c.cas or c.canonical_id] for c in self.basis.components),
            'NRTL' if nrtl else "Raoult's Law",self.basis.feed.pressure_kPa*1000,
            b['F_kmol_h']/3.6,b['zF'],b['D_kmol_h']/3.6,r,
            action.equilibrium_stages,action.feed_stage,
            save_path=str(self.folder/f'column-{self.meter.columns+1:02d}.dwxmz'),
            solver_preference='simultaneous_correction' if nrtl else 'default',
            include_profiles=True,initial_profile=profile,initial_estimate_source_evidence_id=source)
        index=self.meter.columns+1
        save(self.folder/f'column-{index:02d}.request.json',asdict(request))
        self.last_action=action.model_dump();self.last_review=None
        start=time.monotonic();attempt={'index':index,'request':asdict(request),'status':'started'}
        try:
            record=self.backend.rigorous_column(request)
            rid=record['evidence_id'];path=self.folder/f'column-{index:02d}.json';save(path,record)
            self.records[rid]={'path':str(path),'record':record};self.record_actions[rid]=action.model_dump()
            if self.controller_policy == EVIDENCE_POLICY:
                self.record_profiles[rid] = self.effective_initialization
            self.last_id=rid;self.failure=None;attempt.update(status='returned',evidence_id=rid,record_file=str(path))
            return {'evidence_id':rid,'outputs':record['outputs'],'solver_checks':record.get('checks',{}),
                'scope':'Raw numerical output; no independent product acceptance has been applied.'}
        except BudgetExceeded:
            attempt['status']='not_launched';raise
        except Exception as exc:
            self.failure='solver_failure';attempt.update(status='solver_failure',error=type(exc).__name__+': '+str(exc)[:1600]);raise
        finally:
            attempt['duration_s']=time.monotonic()-start
            self.column_events.append(attempt)
            save(self.folder/'column_events.json',self.column_events)
    def review(self,rid):
        if not self.arm.review:raise ValueError('MODULE_DISABLED: independent internal review')
        if rid not in self.records:raise ValueError('EVIDENCE_PRECONDITION: executed record required')
        result=product_checks(self.records[rid]['record'],self.basis,self.screen['reflux_ratio'])
        self.last_review={'evidence_id':rid,**result}
        self.failure=None if result['passed'] else 'product_off_spec' if not all(result['strict_targets'].values()) else 'numerical_validation_failure'
        return self.last_review
    def execute_action(self,action,rid=None):
        self.meter.tool();start=time.monotonic()
        self.ledger.emit('tool_start',tool=action.tool,stage='agent',arguments=action.model_dump(),evidence_id=rid)
        try:
            if action.tool=='review':result=self.review(rid or self.last_id)
            else:
                # All actual physical methods are inherited existing methods.
                common=RecoveryAction.model_validate({k:v for k,v in action.model_dump().items() if k in RecoveryAction.model_fields})
                if common.tool=='audit_model':self.model_audit=self.audit_model();result=self.model_audit
                elif common.tool=='audit_phase':self.phase_audit=self.audit_phase();result=self.phase_audit
                elif common.tool=='sample_native_vle':result=self.sample_native()
                elif common.tool=='screen_native':result=self.screen_column(common.reflux_factor)
                elif common.tool=='simulate_column':result=self.simulate(common)
                else:raise ValueError('UNKNOWN_TOOL')
            event={'tool':action.tool,'status':'success','data':result}
        except BudgetExceeded:raise
        except InitializationEvidenceMissing as exc:
            self.failure = 'initialization_evidence'
            event = {'tool':action.tool, 'status':'failed', 'error':str(exc),
                     'initialization_profiles':profile_capabilities(self.native)}
        except (ValueError,RuntimeError,TimeoutError) as exc:
            event={'tool':action.tool,'status':'failed','error':type(exc).__name__+': '+str(exc)[:2000]}
            if not self.failure:
                self.failure='property_evidence' if any(x in str(exc) for x in ['MODEL_','PARAMETER','PROPERTY']) else 'invalid_decision'
        event['duration_s']=time.monotonic()-start
        self.events.append(event);self.ledger.emit('tool_end',stage='agent',**event)
        return event
