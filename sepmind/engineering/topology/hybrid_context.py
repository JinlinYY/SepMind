"""Bounded model-visible evidence; complete immutable ledgers stay on disk."""
import copy
import hashlib
import json
from pathlib import Path


def load_native_phase_evidence(paths,root,allowed_cards):
    from separation.tools.mixture import mixture_card
    results=[]
    for value in paths:
        path=Path(value).resolve()
        if not path.is_relative_to(root/'output'):
            raise ValueError('SUPPLEMENTARY_EVIDENCE: workspace calculation output required')
        record=json.loads(path.read_text(encoding='utf8'))
        identifier=record.get('property_card_id')
        if identifier not in allowed_cards or record.get('backend')!='DWSIM' or record.get('status')!='ok':
            raise ValueError('SUPPLEMENTARY_EVIDENCE: actual compatible native record required')
        card,checksum=mixture_card(identifier)
        if checksum!=record.get('parameter_sha256'):
            raise ValueError('SUPPLEMENTARY_EVIDENCE: parameter hash mismatch')
        weights=card['molecular_weights_g_mol']
        points=[]
        for row in record['points']:
            phases=[]
            for phase in row.get('phases',[]):
                masses=[x*w for x,w in zip(phase['composition'],weights)]
                phases.append({key:phase[key] for key in ['composition','molar_fraction','density_kg_m3'] if key in phase} |
                    {'mass_fractions':[v/sum(masses) for v in masses]})
            points.append({key:row[key] for key in ['point_id','request','converged','numerical_validation_passed',
                'ideal_vapor_screen_passed','maximum_log_fugacity_residual','error'] if key in row} | {'phases':phases})
        results.append(dict(evidence_id=record['evidence_id'],property_card_id=identifier,
            source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),points=points,
            scope=record.get('scope','Supplementary native phase calculation; whole flowsheet must be recomputed.')))
    return results


def compact_context(context):
    result=copy.deepcopy(context)
    vle=result.get('computed_solvent_vle')
    if vle:
        vle['points']=[{key:row[key] for key in ['point_id','converged','temperature_K',
            'liquid_mole_fractions','vapor_mole_fractions','numerical_validation_passed',
            'maximum_log_fugacity_residual'] if key in row} for row in vle['points']]
    lle=result.get('computed_lle_loading_screen')
    if lle:
        lle['points']=[{key:value for key,value in row.items() if key!='equilibrium'} |
            {'validation':row.get('equilibrium',{}).get('validation',{}).get('passed')}
            for row in lle['points']]
    def bounded(candidate,include_graph=False):
        row={key:value for key,value in candidate.items() if key not in {'graph','graph_check','error'}}
        if include_graph and candidate.get('graph'):
            row['graph']={'units':[{key:value for key,value in unit.items() if value is not None}
                for unit in candidate['graph']['units']],**{key:value for key,value in candidate['graph'].items() if key!='units'}}
        if candidate.get('error'):
            error=candidate['error']
            row['error']=error if len(error)<1000 else error[:450]+' [full error in ledger] '+error[-450:]
        return row
    result['previous_candidates']=[bounded(row,index==len(context.get('previous_candidates',[]))-1)
        for index,row in enumerate(context.get('previous_candidates',[]))][-3:]
    latest=result.get('latest_measured_process')
    if latest:
        measured=[row for row in latest['candidates'] if row.get('actual_execution')]
        result['latest_measured_process']=({key:value for key,value in latest.items() if key!='candidates'} |
            {'candidates':[bounded(measured[-1],include_graph=True)] if measured else []})
    result['prior_autonomous_failures']=[{key:value for key,value in attempt.items() if key!='candidates'} |
        {'candidates':[bounded(row) for row in attempt.get('candidates',[])[-2:]]}
        for attempt in result.get('prior_autonomous_failures',[])[-2:]]
    result['available_computational_initializations']=result.get('available_computational_initializations',[])[-3:]
    for entry in result['available_computational_initializations']:
        entry['actual_outputs']={name:{key:value for key,value in port.items() if key in
            {'flow_mol_s','mole_fractions','temperature_K'}} for name,port in entry['actual_outputs'].items()}
    result['context_policy']='Measured values and original targets retained. Repetitive graphs, native stack traces and auxiliary metadata omitted. Complete evidence remains in the run ledger.'
    if result.get('revision_base'):
        result['previous_candidates']=[{key:value for key,value in row.items() if key!='graph'}
            for row in result['previous_candidates']]
    return result
