"""Research-only atomic tools; no automatic repair or hidden accepted designs.

PHA's production registry remains unchanged. All experimental arms use this
same typed registry and the same source-qualified physics and native adapter.
"""
from dataclasses import asdict
import json,math,time,uuid
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field,model_validator
from scipy.interpolate import PchipInterpolator

from ..schemas import Contract,DesignBasis
from ..thermo import package_for,selected_model
from ..design.binary import material_balance,minimum_reflux,stages
from ..design.rigorous import COMPOUNDS,product_checks
from sepmind.simulation.dwsim import DwsimBackend,BinaryVLERequest,RigorousColumnRequest


class RecoveryAction(Contract):
    tool:Literal['audit_model','audit_phase','sample_native_vle','screen_native',
                 'simulate_column','submit_revision_plan','finish','stop']
    rationale:str=Field(min_length=1,max_length=1800)
    equilibrium_stages:int|None=Field(default=None,ge=3,le=200)
    feed_stage:int|None=Field(default=None,ge=1,le=199)
    reflux_factor:float=Field(default=1.,ge=1.,le=2.)
    profile:Literal['default','native_cmo','native_enthalpy']='default'
    recompute_tools:list[str]|None=Field(default=None,max_length=17)
    classification:Literal['admissible','unsupported_model','infeasible_under_model','unknown']='unknown'

    @model_validator(mode='before')
    @classmethod
    def optional_null_is_omitted(cls,values):
        # Provider JSON encoders may emit null for optional unused fields. Treat
        # null exactly like omission for already-declared neutral defaults in
        # EVERY arm. Never guess missing N/feed or any physical performance.
        if isinstance(values,dict):
            values=dict(values)
            for name in ('reflux_factor','profile','classification'):
                if name in values and values[name] is None:values.pop(name)
        return values


class ExpertReport(Contract):
    observation:str=Field(min_length=1,max_length=1400)
    proposed_next_test:str=Field(min_length=1,max_length=1000)


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    # A short-lived reader or virus scanner can hold the Windows destination.
    # Keep the complete temporary file and bound retries; persistent failures
    # still raise instead of silently losing experimental evidence.
    for attempt in range(50):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==49:raise
            time.sleep(.1)


# Field-level causal inputs, separated from the conservative production gate DAG.
# Values were traced to registry implementations, not inferred from scenario IDs.
REVISION_FIELDS={
 'feed.flow':{'calculate_material_balance','explore_reflux_candidates','select_process_design',
   'calculate_mccabe_thiele_stages','verify_and_refine_column','calculate_energy_balance',
   'estimate_column_equipment','estimate_auxiliary_equipment'},
 'feed.pressure_kPa':{'select_thermodynamic_model','resolve_property_parameters','calculate_binary_vle',
   'assess_separation_feasibility','estimate_minimum_reflux','explore_reflux_candidates',
   'select_process_design','calculate_mccabe_thiele_stages','verify_and_refine_column',
   'calculate_energy_balance','estimate_column_equipment','estimate_auxiliary_equipment'},
 'equipment.cooling_outlet_K':{'estimate_auxiliary_equipment'},
}
REVISION_ALWAYS={'parse_design_basis','check_design_specifications','check_design_consistency','render_preliminary_design_report'}


def revision_required_tools(changed_fields):
    unknown=set(changed_fields)-set(REVISION_FIELDS)
    if unknown:raise ValueError('Unsupported revision fields: '+str(sorted(unknown)))
    return sorted(REVISION_ALWAYS|set().union(*(REVISION_FIELDS[f] for f in changed_fields)))


class AtomicRecoveryRegistry:
    DESCRIPTIONS={
      'audit_model':'Check the requested property method, pair, assumptions and pressure against source-qualified adapters. No column calculation.',
      'audit_phase':'Run the qualified binary equilibrium/operating-envelope test at the frozen targets. Requires an admissible model. A conditional finite-domain test, not global phase stability.',
      'sample_native_vle':'One native DWSIM equilibrium dataset, including enthalpies for NRTL. Consumes one native invocation; provides no accepted column or recommended design.',
      'screen_native':'Compute Rmin and CMO equilibrium stages/feed using sampled native equilibrium at original reflux times reflux_factor. Supplies no design margin or automatic retry.',
      'simulate_column':'One fixed-design native MESH attempt. Supply equilibrium_stages and feed_stage explicitly. profile=default needs no sampled data; native_cmo or native_enthalpy require a sample. No automatic parameter changes or fallback.',
      'submit_revision_plan':'Submit a set of existing production tool names to recompute after the explicit patch. This endpoint scores a dependency plan only, not a new physical design.',
      'finish':'For an admissibility task, report the evidence-supported classification; an accepted repair is detected directly from native results.',
      'stop':'Stop without fabricating results. For a repair this does not count as strict recovery.',
    }

    def __init__(self,basis,screen,folder,seed=None,native_budget=4,backend=None,task_kind='repair',revision=None):
        self.basis=DesignBasis.model_validate(basis.model_dump() if isinstance(basis,DesignBasis) else basis)
        self.screen=screen;self.folder=Path(folder).resolve();self.folder.mkdir(parents=True,exist_ok=True)
        self.seed=seed;self.native_budget=native_budget;self.native_calls=0;self.column_attempts=0
        self.backend=backend or DwsimBackend(timeout_s=180)
        self.task_kind=task_kind;self.revision=revision;self.events=[];self.model_audit=None
        self.phase_audit=None;self.native=None;self.native_screen=None;self.accepted=None

    def capabilities(self):return [{'name':k,'description':v} for k,v in self.DESCRIPTIONS.items()]

    def audit_model(self):
        try:
            model=selected_model(self.basis);package_for(self.basis)
            return {'admissible':True,'model':model,'scope':'Registered adapter domain only; no industrial qualification.'}
        except ValueError as exc:return {'admissible':False,'reason':str(exc)}

    def audit_phase(self):
        audit=self.audit_model()
        if not audit['admissible']:return {'classification':'unsupported_model','model_audit':audit}
        try:
            result=minimum_reflux(package_for(self.basis),self.basis,material_balance(self.basis))
            return {'classification':'admissible','minimum_reflux':result,'scope':'Conditional sampled binary operating-envelope feasibility.'}
        except ValueError as exc:
            reason=str(exc)
            label='infeasible_under_model' if reason.startswith(('FEAS_AZEOTROPE','STAGE_PINCH')) else 'unsupported_model'
            return {'classification':label,'reason':reason,'scope':'Under the registered model only.'}

    def _consume_native(self):
        if self.native_calls>=self.native_budget:raise ValueError('NATIVE_BUDGET: no additional native invocation allowed')
        self.native_calls+=1

    def _reflux(self,factor):
        if self.basis.column.reflux_ratio is not None or self.basis.column.reflux_multiplier is not None:
            if factor!=1.:raise ValueError('FIXED_SPECIFICATION: user reflux constraint must be preserved')
        return float(self.screen['reflux_ratio'])*factor

    def sample_native(self):
        if not self.audit_model()['admissible']:raise ValueError('MODEL_PRECONDITION: model not admitted')
        b=material_balance(self.basis);nrtl=selected_model(self.basis)=='NRTL'
        xs=set(map(float,np.linspace(1e-6,1-1e-6,301 if nrtl else 201)))|{b['xB'],b['xD'],b['zF']}
        if nrtl:xs.update(map(float,np.geomspace(1e-6,.05,51)))
        self._consume_native()
        record=self.backend.binary_vle(BinaryVLERequest(tuple(COMPOUNDS[c.cas or c.canonical_id] for c in self.basis.components),
            'NRTL' if nrtl else "Raoult's Law",self.basis.feed.pressure_kPa*1000,tuple(sorted(xs)),nrtl))
        save(self.folder/f'equilibrium-{self.native_calls:02d}.json',record);self.native=record
        return {'evidence_id':record['evidence_id'],'points':len(record['points']),
                'enthalpies_available':nrtl,'scope':'Native equilibrium observations, not a column result.'}

    def _equilibrium(self):
        if self.native is None:raise ValueError('EVIDENCE_PRECONDITION: sample native equilibrium first')
        p=self.native['points'];xs=[v['x'][0] for v in p];ys=[v['y'][0] for v in p]
        b=material_balance(self.basis)
        if any(y<=x for x,y in zip(xs,ys) if b['xB']<=x<=b['xD']) or any(a>=z for a,z in zip(ys,ys[1:])):
            raise ValueError('NATIVE_VLE_CONFLICT: admitted monotone enrichment interval not supported')
        fit=PchipInterpolator([0.,*xs,1.],[0.,*ys,1.],extrapolate=False)
        class Equilibrium:
            def point(self,x,pressure):
                y=float(fit(x))
                if not math.isfinite(y):raise ValueError('MODEL_OUT_OF_RANGE: no native interpolation extrapolation')
                return {'x':[x,1-x],'y':[y,1-y]}
        return Equilibrium()

    def screen_column(self,factor):
        eq=self._equilibrium();b=material_balance(self.basis);effective=self.basis.model_copy(deep=True)
        effective.column.reflux_multiplier=None;effective.column.reflux_ratio=self._reflux(factor)
        effective.assumptions=sorted(set(effective.assumptions+['constant_molar_overflow']))
        minimum=minimum_reflux(eq,effective,b);result=stages(eq,effective,b,minimum)
        self.native_screen=result
        return {k:result[k] for k in ('reflux_ratio','minimum_reflux_ratio','theoretical_stages_rounded_up',
                                     'feed_stage_from_top','stage_convention')}

    def initial_profile(self,action):
        if action.profile=='default':return None,None
        eq=self._equilibrium();p=self.native['points'];b=material_balance(self.basis)
        n,feed,r=action.equilibrium_stages,action.feed_stage,self._reflux(action.reflux_factor)
        if action.profile=='native_enthalpy':
            from ..design.enthalpy_seed import coupled_initial_profile
            if 'liquid_enthalpy_kJ_mol' not in p[0]:raise ValueError('DATA_PARAMETER_MISSING: no native phase enthalpies')
            result=coupled_initial_profile(p,b,r,n,feed)
            save(self.folder/f'initializer-{len(self.events):02d}.json',result)
            if result['status']!='initial_guess':raise ValueError('INITIALIZATION_FAILED: '+result.get('reason',result['status']))
            return result['profile'],self.native['evidence_id']
        screen=self.screen_column(action.reflux_factor)
        full=self.native_screen;old_n=full['theoretical_stages_rounded_up'];old_feed=full['feed_stage_from_top']
        source=[b['xD']]+[v['x'] for v in full['steps'][:-1]]+[b['xB']]
        source=[max(b['xB'],min(b['xD'],x)) for x in source]
        coordinates=[i*old_feed/feed if i<=feed else old_feed+(i-feed)*(old_n-old_feed)/(n-feed) for i in range(n+1)]
        xi=np.interp(coordinates,list(range(old_n+1)),source)
        temp=PchipInterpolator([v['x'][0] for v in p],[v['temperature_k'] for v in p],extrapolate=False)
        F,D,B=[b[k]/3.6 for k in ('F_kmol_h','D_kmol_h','B_kmol_h')]
        profile=[{'temperature_K':float(temp(x)),'liquid_flow_mol_s':B if i==n else r*D+(F if i>=feed else 0.),
                  'vapor_flow_mol_s':0. if i==0 else (r+1)*D,'liquid_light_fraction':float(x),
                  'vapor_light_fraction':b['xD'] if i==0 else eq.point(float(x),0)['y'][0]} for i,x in enumerate(xi)]
        return profile,self.native['evidence_id']

    def simulate(self,action):
        if not self.audit_model()['admissible']:raise ValueError('MODEL_PRECONDITION: model not admitted')
        if action.equilibrium_stages is None or action.feed_stage is None:raise ValueError('INPUT_MISSING: explicit stages and feed_stage required')
        if action.feed_stage>=action.equilibrium_stages:raise ValueError('INPUT_INVALID: feed_stage must be smaller than equilibrium_stages')
        if action.equilibrium_stages>self.basis.column.max_stages:raise ValueError('FIXED_SPECIFICATION: maximum stage limit')
        profile,source=self.initial_profile(action);b=material_balance(self.basis);r=self._reflux(action.reflux_factor)
        nrtl=selected_model(self.basis)=='NRTL';self._consume_native();self.column_attempts+=1
        request=RigorousColumnRequest(tuple(COMPOUNDS[c.cas or c.canonical_id] for c in self.basis.components),
            'NRTL' if nrtl else "Raoult's Law",self.basis.feed.pressure_kPa*1000,b['F_kmol_h']/3.6,b['zF'],b['D_kmol_h']/3.6,
            r,action.equilibrium_stages,action.feed_stage,save_path=str(self.folder/f'column-{self.column_attempts:02d}.dwxmz'),
            solver_preference='simultaneous_correction' if nrtl else 'default',include_profiles=True,
            initial_profile=profile,initial_estimate_source_evidence_id=source)
        save(self.folder/f'column-{self.column_attempts:02d}.request.json',asdict(request))
        record=self.backend.rigorous_column(request);path=self.folder/f'column-{self.column_attempts:02d}.json';save(path,record)
        checks=product_checks(record,self.basis,self.screen['reflux_ratio'])
        if checks['passed']:self.accepted={'record_file':str(path),'evidence_id':record['evidence_id'],'checks':checks,'request':asdict(request)}
        o=record['outputs']
        return {'evidence_id':record['evidence_id'],'record_file':str(path),'checks':checks,
                'outputs':{k:o[k] for k in ('distillate','bottoms','light_recovery','condenser_duty_kW','reboiler_duty_kW')}}

    def execute(self,action):
        action=RecoveryAction.model_validate(action) if isinstance(action,dict) else action
        start=time.monotonic();event={'event_id':str(uuid.uuid4()),'tool':action.tool,'arguments':action.model_dump()}
        try:
            if action.tool=='audit_model':self.model_audit=self.audit_model();result=self.model_audit
            elif action.tool=='audit_phase':self.phase_audit=self.audit_phase();result=self.phase_audit
            elif action.tool=='sample_native_vle':result=self.sample_native()
            elif action.tool=='screen_native':result=self.screen_column(action.reflux_factor)
            elif action.tool=='simulate_column':result=self.simulate(action)
            elif action.tool=='submit_revision_plan':
                if self.task_kind!='revision':raise ValueError('TASK_PRECONDITION: no revision task')
                from .registry import EngineeringToolRegistry
                if action.recompute_tools is None:raise ValueError('REVISION_TOOLS_REQUIRED')
                if not set(action.recompute_tools)<=set(EngineeringToolRegistry.TOOLS):raise ValueError('UNKNOWN_REVISION_TOOL')
                required=set(revision_required_tools(self.revision['changed_fields']))
                # Shared transport/bookkeeping is automatic in every arm. The
                # experiment scores chemical/evidence dependencies, not omission
                # of a parser/logger/report refresh from a numerical tool list.
                proposed=set(action.recompute_tools)|REVISION_ALWAYS
                result={'missing':sorted(required-proposed),'extra':sorted(proposed-required),'coverage_passed':required<=proposed,
                        'minimal_plan':required==proposed,'unnecessary_native_column_planned':int('verify_and_refine_column' in proposed-required),
                        'standard_bookkeeping_added':sorted(REVISION_ALWAYS-set(action.recompute_tools)),
                        'scope':'Dependency-plan endpoint only; no revised physical performance or actual simulation saving claimed.'}
            else:result={'classification':action.classification,'stopped':action.tool=='stop'}
            event.update(status='success',data=result)
        except (ValueError,RuntimeError,TimeoutError) as exc:
            event.update(status='failed',error=type(exc).__name__+': '+str(exc)[:2000])
        event['elapsed_s']=time.monotonic()-start;event['native_calls_total']=self.native_calls
        self.events.append(event);save(self.folder/'atomic_events.json',self.events)
        return event
