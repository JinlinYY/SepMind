"""Typed hybrid-process tools within the existing SepMind tool envelope."""
import hashlib
from itertools import product
import json
from pathlib import Path
import numpy as np

from ..schemas import Contract, ToolResult, Reason, EvidenceRecord
from ..schemas.process import ProcessDesignBasis
from ..thermo.lle import load_lle_model, flash_lle
from ..design.extraction import stream_to_molar, extraction_cascade
from ..validation.extraction import review_extraction
from pha.streaming import emit_step


class ProcessBasisInput(Contract):
    basis: ProcessDesignBasis


def missing_process_inputs(b):
    missing=[]
    if len(b.components)<2:missing.append('components: canonical component identities')
    feed=next((s for s in b.streams if s.stream_id==b.feed_stream_id),None)
    if feed is None:missing.append('feed stream')
    else:
        if feed.flow is None:missing.append('feed mass/molar flow and unit after pretreatment')
        if not feed.composition:missing.append('feed composition and basis after pretreatment')
    for field in ('solvent_component_id','carrier_component_id','solute_component_id','extraction_temperature_K','extraction_pressure_Pa'):
        if getattr(b,field) is None:missing.append(field)
    if len({b.solvent_component_id,b.carrier_component_id,b.solute_component_id}-{None})!=3:
        missing.append('three distinct solvent/carrier/solute identities')
    if not b.targets:missing.append('explicit process product/recovery/concentration targets')
    return missing


class ProcessToolRegistry:
    TOOLS={
        'check_process_basis':('G0',ProcessBasisInput),
        'qualify_lle_model':('G2',ProcessBasisInput),
        'calculate_process_feed_inventory':('G3',ProcessBasisInput),
        'screen_extraction_phase_split':('G1',ProcessBasisInput),
        'explore_extraction_candidates':('G4',ProcessBasisInput),
        'select_extraction_candidate':('G4',ProcessBasisInput),
        'review_extraction_candidates':('G8',ProcessBasisInput),
    }
    DEPENDENCIES={'check_process_basis':[], 'qualify_lle_model':['check_process_basis'],
        'calculate_process_feed_inventory':['qualify_lle_model'],
        'screen_extraction_phase_split':['calculate_process_feed_inventory'],
        'explore_extraction_candidates':['screen_extraction_phase_split'],
        'select_extraction_candidate':['explore_extraction_candidates','review_extraction_candidates'],
        'review_extraction_candidates':['explore_extraction_candidates']}

    def capabilities(self):
        return [dict(name=n,gate=g,input_schema=s.model_json_schema(),implemented=True) for n,(g,s) in self.TOOLS.items()]

    def execute(self,name,state,gate,arguments):
        if name not in self.TOOLS:raise ValueError('UNREGISTERED_TOOL')
        if self.TOOLS[name][0]!=gate:raise ValueError('GATE_PRECONDITION: tool belongs to a different process gate')
        typed=ProcessBasisInput.model_validate(arguments)
        if typed.basis!=state.basis:raise ValueError('SOURCE_CONFLICT: process basis differs from frozen run')
        for required in self.DEPENDENCIES[name]:
            a=state.artifacts.get(required)
            if a is None or a.status!='success' or not a.validation.get('passed'):
                raise ValueError('GATE_PRECONDITION: validated process prerequisite missing: '+required)
        state.tool_calls+=1
        out=ToolResult(status='success',tool_name=name,run_id=state.run_id,source_or_run=state.run_id,
            evidence=[EvidenceRecord(evidence_id=state.basis.design_id,type='input_specification',source='frozen multicomponent process basis')])
        try:
            out.data=getattr(self,name)(state)
            if name=='qualify_lle_model':
                out.evidence.append(EvidenceRecord(evidence_id=out.data['parameter_sha256'],type='property_database',
                    source=out.data['card']['source_url'],sha256=out.data['card']['source_sha256']))
            out.validation={'passed':True,'scope':out.data.get('scope','Only the named operation and stated checks')}
            out.convergence={'converged':True} if name in ('screen_extraction_phase_split','explore_extraction_candidates') else {'applicable':False}
            out.units={'component_flows':'kmol/h','mass_flows':'kg/h','temperature':'K','pressure':'Pa','composition':'explicit mass or mole fraction'}
        except ValueError as exc:
            code=str(exc).split(':',1)[0]
            out.status='needs_input' if code in ('INPUT_UNDERDETERMINED','MODEL_OUT_OF_RANGE','PROPERTY_UNQUALIFIED') else 'failed'
            out.error_type=code;out.errors=[Reason(code=code,explanation=str(exc))];out.validation={'passed':False}
        return out

    @staticmethod
    def check_process_basis(state):
        missing=missing_process_inputs(state.basis)
        if missing:raise ValueError('INPUT_UNDERDETERMINED: '+'; '.join(missing))
        return {'component_count':len(state.basis.components),'missing':[],
                'source_findings':state.basis.unresolved_source_findings,
                'unresolved_downstream_targets':[t.target_id for t in state.basis.targets if t.quantity=='purity_basis_unresolved'],
                'scope':'Extraction branch input sufficiency; downstream targets and energy are separately gated'}

    @staticmethod
    def model(state):
        selected=state.artifacts.get('qualify_lle_model')
        return load_lle_model(selected.data['model_id'] if selected else state.basis.thermodynamic_model_id or 'acid_lle_colombo1999_v1')

    def qualify_lle_model(self,state):
        m=self.model(state);b=state.basis
        if {c.canonical_id for c in b.components}!=set(m.order):raise ValueError('PROPERTY_UNQUALIFIED: no source-qualified LLE model for these components')
        m.check_domain(b.extraction_temperature_K,b.extraction_pressure_Pa)
        return {'model_id':m.card['model_id'],'parameter_sha256':m.digest,'card':m.card,
                'scope':'Conditional isothermal ternary LLE screening only; no VLE/enthalpy/association qualification'}

    def calculate_process_feed_inventory(self,state):
        m=self.model(state);b=state.basis
        feed=next(s for s in b.streams if s.stream_id==b.feed_stream_id)
        f=stream_to_molar(feed,m)
        return {'component_order':m.order,'feed_kmol_h':f.tolist(),'feed_mass_flow_kg_h':float(f@m.mw),
                'feed_component_mass_kg_h':(f*m.mw).tolist(),'scope':'Feed conversion and identity checks only, no product split imposed'}

    def screen_extraction_phase_split(self,state):
        m=self.model(state);b=state.basis;f=np.array(state.artifacts['calculate_process_feed_inventory'].data['feed_kmol_h'])
        search=state.active_search or b.search
        screens=[]
        for ratio in search.solvent_feed_mass_ratios:
            s=np.zeros_like(f);s[m.order.index(b.solvent_component_id)]=float(f@m.mw)*ratio/m.mw[m.order.index(b.solvent_component_id)]
            try:
                result=flash_lle(m,(f+s)/sum(f+s),b.extraction_temperature_K,b.extraction_pressure_Pa)
                screens.append({'solvent_feed_mass_ratio':ratio,'screen':result})
            except ValueError as exc:screens.append({'solvent_feed_mass_ratio':ratio,'error':str(exc)})
        split=next((r['screen'] for r in screens if r.get('screen',{}).get('phase_count')==2),None)
        if split is None:raise ValueError('FEAS_NO_TWO_LIQUIDS: no tested solvent ratio provides an accepted two-liquid split; this is not a global infeasibility proof')
        return {'screen':split,'screened_ratios':screens,'scope':'All bounded solvent ratios screened; every cascade contact must still pass its own phase check'}

    def explore_extraction_candidates(self,state):
        m=self.model(state);b=state.basis;f=np.array(state.artifacts['calculate_process_feed_inventory'].data['feed_kmol_h'])
        search=state.active_search or b.search
        carrier,solute,solvent=[m.order.index(v) for v in (b.carrier_component_id,b.solute_component_id,b.solvent_component_id)]
        target=next((t for t in b.targets if t.quantity=='recovery' and t.location=='extract' and t.component_id==b.solute_component_id),None)
        if target is None:
            raise ValueError('INPUT_UNDERDETERMINED: available extraction synthesis currently needs an explicit extraction recovery criterion; a treated-water mg/L target requires separately qualified regeneration and density calculations, not a fabricated recovery conversion')
        candidates=[]
        for n,ratio in list(product(search.stage_candidates,search.solvent_feed_mass_ratios))[:search.maximum_candidates]:
            cid=f'extract-n{n}-sf{ratio:g}';s=np.zeros_like(f);s[solvent]=float(f@m.mw)*ratio/m.mw[solvent]
            row={'candidate_id':cid,'stages':n,'solvent_feed_mass_ratio':ratio,'solvent_mass_flow_kg_h':float(s@m.mw)}
            try:
                raw=extraction_cascade(m,f,s,b.extraction_temperature_K,b.extraction_pressure_Pa,n,carrier,solute,solvent,search.configuration,search.max_iterations)
                review=review_extraction(raw,m,b.extraction_temperature_K,expected_feed=f,expected_solvent=s,solute_index=solute)
                achieved=raw['solute_extraction_recovery']
                on_spec=achieved>=target.value if target.operator=='>=' else achieved>target.value if target.operator=='>' else achieved<=target.value if target.operator=='<=' else achieved<target.value
                row.update(status='feasible' if review['passed'] and on_spec else 'off_spec',raw=raw,independent_review=review,target_passed=on_spec)
            except ValueError as exc:row.update(status='failed',reason=str(exc))
            candidates.append(row)
            emit_step('ExtractionCandidate',f"{cid}: {row['status']}")
        return {'candidates':candidates,'feasible_candidate_ids':[r['candidate_id'] for r in candidates if r['status']=='feasible'],
                'target':target.model_dump(),'executed_search':search.model_dump(),'scope':'Extraction endpoint only; no final-product purity, full-flowsheet recovery, energy or solvent recycle claim'}

    def review_extraction_candidates(self,state):
        m=self.model(state);a=state.artifacts['explore_extraction_candidates'].data
        search=state.active_search or state.basis.search
        f=np.array(state.artifacts['calculate_process_feed_inventory'].data['feed_kmol_h'])
        solvent=m.order.index(state.basis.solvent_component_id);solute=m.order.index(state.basis.solute_component_id)
        reviews=[]
        for candidate in a['candidates']:
            if 'raw' in candidate:
                s=np.zeros_like(f);s[solvent]=float(f@m.mw)*candidate['solvent_feed_mass_ratio']/m.mw[solvent]
                review=review_extraction(candidate['raw'],m,state.basis.extraction_temperature_K,expected_feed=f,expected_solvent=s,solute_index=solute)
                if candidate['stages']!=candidate['raw']['stages'] or candidate['stages'] not in search.stage_candidates or candidate['solvent_feed_mass_ratio'] not in search.solvent_feed_mass_ratios:
                    review['passed']=False;review['issues'].append('frozen candidate grid or stage count mismatch')
                reviews.append({'candidate_id':candidate['candidate_id'],**review})
        if any(not r['passed'] for r in reviews):raise ValueError('INDEPENDENT_REVIEW_FAILED: raw candidate invariants failed')
        return {'reviews':reviews,'scope':'Independent numerical review of available extraction results; missing downstream stages remain unresolved'}

    def select_extraction_candidate(self,state):
        options=state.artifacts['explore_extraction_candidates'].data['candidates']
        audited={r['candidate_id']:r for r in state.artifacts['review_extraction_candidates'].data['reviews']}
        target=next(t for t in state.basis.targets if t.quantity=='recovery' and t.location=='extract' and t.component_id==state.basis.solute_component_id)
        def passes_target(candidate):
            actual=candidate['raw']['solute_extraction_recovery']
            return np.isfinite(actual) and {'>=':actual>=target.value,'>':actual>target.value,'<=':actual<=target.value,'<':actual<target.value}[target.operator]
        feasible=[r for r in options if r['status']=='feasible' and r['independent_review']['passed'] and audited.get(r['candidate_id'],{}).get('passed') and passes_target(r)]
        if not feasible:raise ValueError('EXTRACTION_TARGET_NOT_MET: no computed candidate meets the original extraction target')
        requested=state.design_preferences.get('extraction_candidate_id')
        selected=next((r for r in feasible if r['candidate_id']==requested),None)
        if requested and selected is None:raise ValueError('INVALID_DESIGN_SELECTION: choose only an independently checked computed candidate')
        if selected is None:selected=min(feasible,key=lambda r:(r['solvent_feed_mass_ratio'],r['stages']))
        state.accepted_candidate_id=selected['candidate_id']
        return {'selected_candidate':selected,'scope':'Selected extraction section only; solvent circulation and stages are design trade-offs, not a computed energy/economic optimum'}
