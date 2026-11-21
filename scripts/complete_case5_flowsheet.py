"""Real native two-column/conditioner/makeup recycle, with bounded iteration.

Reference geometry and fixed D/R are stated inputs, never an autonomous-design
claim. All products are calculated. No recovery factor or source product is
inserted into a physical stream.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from separation.tools.multifeed import MultiFeedColumnRequest,MultiFeedDwsimBackend
from separation.tools.mixture import MixtureProbeRequest
from pha.engineering.validation.multifeed import review_multifeed_column
from pha.engineering.design.recycle import converge_component_recycle
from pha.engineering.validation.initialization import material_consistent_profile
from scripts.run_case5_native import run

FIELDS=('temperature_K','liquid_flow_mol_s','vapor_flow_mol_s','liquid_mole_fractions','vapor_mole_fractions')

def warm(native):
    return [{k:r[k] for k in FIELDS} for r in native['outputs']['stage_profiles']]

def checked(native,backend,path):
    if not native.get('outputs'):raise ValueError('Native unit failed: '+str(path))
    review=review_multifeed_column(native,backend)
    path.write_text(json.dumps(review,indent=2),encoding='utf8')
    if not all(review[k] for k in ('numerical_passed','stage_equilibrium_passed','independent_finite_liquid_screen_passed')):
        raise ValueError('Independent unit review failed: '+str(path))
    return review

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'output/engineering/case5_closed_flowsheet_20261110')
    parser.add_argument('--review-existing',action='store_true',help='Recheck retained final native units and actual tear ledger; never rerun or invent a unit')
    parser.add_argument('--seed-folder',type=Path)
    parser.add_argument('--recovery-reflux',type=float)
    parser.add_argument('--recovery-distillate',type=float)
    parser.add_argument('--extractive-reflux',type=float)
    parser.add_argument('--c1-pressure-drop',type=float,default=0.,help='Explicit hydraulic sensitivity kPa; uses separate unqualified versioned card')
    parser.add_argument('--c2-pressure-drop',type=float,default=0.)
    args=parser.parse_args();folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=True)
    if min(args.c1_pressure_drop,args.c2_pressure_drop)<0 or max(args.c1_pressure_drop,args.c2_pressure_drop)>80:raise ValueError('Pressure sensitivity outside0..80kPa')
    backend=MultiFeedDwsimBackend(timeout_s=150)
    seeds=ROOT/'output/engineering/case5_balanced_newton_20261110'
    current=[json.loads((seeds/(n+'.json')).read_text(encoding='utf8')) for n in ('C1_N39','C2_N19')]
    if args.seed_folder:
        previous=json.loads((args.seed_folder/'iteration_ledger.json').read_text(encoding='utf8'))[-1]['iteration']
        current=[json.loads((args.seed_folder/f'{previous:02d}_{name}.json').read_text(encoding='utf8')) for name in ('C1','C2')]
    index=0;ledger=[]
    solvent_total=50.
    def unit_map(recycle):
        nonlocal index,current
        index+=1;makeup=solvent_total-float(sum(recycle))
        if makeup<0:raise ValueError('Recycle exceeds specified solvent circulation; a purge decision is required')
        solvent=recycle+np.array([makeup,0.,0.]);c1data=current[0]['request'].copy()
        if max(args.c1_pressure_drop,args.c2_pressure_drop)>0:
            c1data.update(property_card_id='mch_toluene_phenol_hydraulic_sensitivity_v2',bottom_pressure_pa=101325.+1000*args.c1_pressure_drop)
        c1data['feeds']=[dict(f) for f in c1data['feeds']]
        if args.extractive_reflux is not None:c1data['reflux_ratio']=args.extractive_reflux
        c1data['feeds'][0].update(flow_mol_s=solvent_total,mole_fractions=(solvent/solvent_total).tolist(),
            temperature_K=373.,source_evidence_id=f'case5:tear_iteration_{index}')
        c1data.update(purpose='design_candidate',initial_profile=warm(current[0]),initial_estimate_source_evidence_id=current[0]['evidence_id'],
            numerical_solver='sparse_trust_region',numerical_jacobian_policy='balanced_reduced',solver_tolerance=1e-10,
            solver_attempt_limit=1,solver_iteration_limit=40,save_path=str(folder/f'{index:02d}_C1.dwxmz'))
        c1request=MultiFeedColumnRequest.model_validate(c1data)
        profile,audit=material_consistent_profile(c1request)
        (folder/f'{index:02d}_C1.initialization.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
        c1request=MultiFeedColumnRequest.model_validate(c1data|dict(initial_profile=profile))
        c1=run(c1request,backend,folder/f'{index:02d}_C1.json')
        r1=checked(c1,backend,folder/f'{index:02d}_C1.review.json')
        bottom=c1['outputs']['bottoms'];c2data=current[1]['request'].copy()
        if max(args.c1_pressure_drop,args.c2_pressure_drop)>0:
            c2data.update(property_card_id='mch_toluene_phenol_hydraulic_sensitivity_v2',bottom_pressure_pa=101325.+1000*args.c2_pressure_drop)
        c2data['feeds']=[dict(c2data['feeds'][0],flow_mol_s=bottom['flow_mol_s'],mole_fractions=bottom['mole_fractions'],
            temperature_K=bottom['temperature_K'],specific_enthalpy_kJ_kg=bottom['specific_enthalpy_kJ_kg'],source_evidence_id=c1['evidence_id'])]
        if args.recovery_reflux is not None:c2data['reflux_ratio']=args.recovery_reflux
        if args.recovery_distillate is not None:c2data['distillate_flow_mol_s']=args.recovery_distillate
        c2data.update(purpose='design_candidate',initial_profile=warm(current[1]),initial_estimate_source_evidence_id=current[1]['evidence_id'],
            numerical_solver='sparse_trust_region',numerical_jacobian_policy='balanced_reduced',solver_tolerance=1e-10,
            solver_attempt_limit=1,solver_iteration_limit=40,save_path=str(folder/f'{index:02d}_C2.dwxmz'))
        c2request=MultiFeedColumnRequest.model_validate(c2data)
        profile,audit=material_consistent_profile(c2request)
        (folder/f'{index:02d}_C2.initialization.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
        c2request=MultiFeedColumnRequest.model_validate(c2data|dict(initial_profile=profile))
        c2=run(c2request,backend,folder/f'{index:02d}_C2.json')
        r2=checked(c2,backend,folder/f'{index:02d}_C2.review.json')
        current=[c1,c2];returned=c2['outputs']['bottoms'];v=returned['flow_mol_s']*np.array(returned['mole_fractions'])
        record=dict(iteration=index,input_recycle_component_mol_s=recycle.tolist(),return_component_mol_s=v.tolist(),
                    makeup_mol_s=makeup,c1_evidence_id=c1['evidence_id'],c2_evidence_id=c2['evidence_id'])
        ledger.append(record);(folder/'iteration_ledger.json').write_text(json.dumps(ledger,indent=2),encoding='utf8')
        return dict(validated=True,recycle_component_flows=v.tolist(),makeup_mol_s=makeup,
                    input_recycle_component_mol_s=recycle.tolist(),unit_evidence_ids=[c1['evidence_id'],c2['evidence_id']])
    initial=current[1]['outputs']['bottoms']
    try:
        if args.review_existing:
            saved=json.loads((folder/'iteration_ledger.json').read_text(encoding='utf8'))
            if len(saved)<2:raise ValueError('Both accepted iteration and independent re-evaluation required')
            trace=[]
            for entry in saved:
                a=np.asarray(entry['input_recycle_component_mol_s']);b=np.asarray(entry['return_component_mol_s'])
                residual=float(max(abs(a-b))/max(sum(a),sum(b),1e-12))
                trace.append(dict(iteration=entry['iteration'],maximum_component_relative_residual=residual))
            if max(t['maximum_component_relative_residual'] for t in trace[-2:])>1e-9:
                raise ValueError('Saved iterations do not independently establish recycle closure')
            index=saved[-1]['iteration'];current=[json.loads((folder/f'{index:02d}_{name}.json').read_text(encoding='utf8')) for name in ('C1','C2')]
            for name,native in zip(('C1','C2'),current):checked(native,backend,folder/f'{index:02d}_{name}.review.json')
            recycle=dict(converged=True,component_flows=saved[-1]['input_recycle_component_mol_s'],trace=trace,
                         iterations=len(saved)-1,unit_map_result=dict(makeup_mol_s=saved[-1]['makeup_mol_s']))
        else:
            recycle=converge_component_recycle(unit_map,initial['flow_mol_s']*np.array(initial['mole_fractions']),
                        relative_tolerance=1e-9,max_iterations=12,damping=1.)
        c1,c2=current;makeup=recycle['unit_map_result']['makeup_mol_s']
        probe=backend.mixture_probe(MixtureProbeRequest(property_card_id=c1['property_card_id'],points=[
            dict(point_id='fresh_phenol',mole_fractions=[1.,0.,0.],temperature_K=373.,pressure_Pa=101325.,specification='TP')]))
        (folder/'makeup_property.json').write_text(json.dumps(probe,indent=2),encoding='utf8')
        point=probe['points'][0]
        if not point['converged'] or len(point['phases'])!=1 or point['phases'][0]['native_phase_index']==2:raise ValueError('Fresh solvent enthalpy is not resolved as a single liquid')
        hm=point['phases'][0]['specific_enthalpy_kJ_kg_unqualified']
        def vector(stream):return stream['flow_mol_s']*np.asarray(stream['mole_fractions'])
        def heat(stream):return stream['mass_flow_kg_s']*stream['specific_enthalpy_kJ_kg']
        fresh=c1['outputs']['feeds'][1];solv=c1['outputs']['feeds'][0]
        products=[c1['outputs']['distillate'],c2['outputs']['distillate']];bottom=c2['outputs']['bottoms']
        from separation.tools.mixture import mixture_card
        card,_=mixture_card(c1['property_card_id']);mw=np.asarray(card['molecular_weights_g_mol'])
        makeup_heat=float(makeup*mw[0]/1000*hm)
        conditioner=heat(bottom)+makeup_heat-heat(solv) # positive heat removed, including mixing
        inlet=vector(fresh)+np.array([makeup,0.,0.]);outlet=sum((vector(p) for p in products))
        mass=float(max(abs(inlet-outlet))/sum(inlet))
        qc=sum(c['outputs']['condenser_duty_kW'] for c in current);qr=sum(c['outputs']['reboiler_duty_kW'] for c in current)
        energy=abs(heat(fresh)+makeup_heat+qr-qc-conditioner-sum(heat(p) for p in products))/max(qr,qc,1.)
        c2in=c2['outputs']['feeds'][0]
        constraints=[dict(id='C1_bottom_MCH_mole_fraction',value=c1['outputs']['bottoms']['mole_fractions'][2],maximum=.0001),
                     dict(id='C2_top_phenol_mole_fraction',value=products[1]['mole_fractions'][0],maximum=.001),
                     dict(id='C2_bottom_toluene_recovery_fraction',value=vector(bottom)[1]/vector(c2in)[1],maximum=.001)]
        for row in constraints:
            row['value']=float(row['value']);row['passed']=bool(row['value']<=row['maximum'])
        loss=float(sum(vector(p)[0] for p in products));makeup_error=abs(loss-makeup)/max(makeup,1e-12)
        numerical=bool(mass<=1e-7 and energy<=1e-7 and makeup_error<=1e-5)
        result=dict(status='numerically_closed_preliminary_flowsheet' if numerical and all(r['passed'] for r in constraints) else 'off_spec',
            full_numerical_flowsheet_passed=numerical and all(r['passed'] for r in constraints),
            production_design_admitted=False,property_qualification='predictive_UNIFAC; no independent experimental qualification',
            flowsheet='Fresh hydrocarbon + cooled phenol recycle/makeup -> C1; C1 bottoms -> C2; C2 bottoms -> conditioner/makeup -> C1',
            original_source_constraints=constraints,recycle=recycle,component_closure_relative=float(mass),energy_closure_relative=float(energy),
            fresh_phenol_mol_s=makeup,fresh_phenol_kg_h=float(makeup*mw[0]*3.6),external_phenol_loss_mol_s=float(loss),
            makeup_loss_relative_residual=makeup_error,conditioner_heat_removed_kW=conditioner,
            total_reboiler_duty_kW=qr,total_condenser_duty_kW=qc,
            declared_pressure_drop_kPa=[args.c1_pressure_drop,args.c2_pressure_drop],
            upstream_feed_delivery_pressure_Pa=fresh['pressure_Pa'],
            external_feeds=[fresh,dict(component_order=card['component_order'],flow_mol_s=makeup,mole_fractions=[1.,0.,0.],temperature_K=373.,specific_enthalpy_kJ_kg=hm)],
            external_products=products,unit_evidence_ids=[c['evidence_id'] for c in current],
            acceptance_criteria=dict(component_relative=1e-7,energy_relative=1e-7,makeup_loss_relative=1e-5,recycle_component_relative=1e-9),
            assumptions=[f'373 K fresh phenol; declared pressure drops{[args.c1_pressure_drop,args.c2_pressure_drop]}kPa; equilibrium stages; conditioner includes mixing heat.',
                         'Any elevated feed-delivery pressure requires separately calculated upstream pump/heater; this column-loop boundary does not include that preparation section.',
                         'Source geometry is reused. Product draws/reflux are declared operating candidates, including any explicit revisions; not a blind autonomous optimum.',
                         'No plant-operation validation or mechanical equipment sizing.'])
    except Exception as exc:
        result=dict(status='blocked',full_numerical_flowsheet_passed=False,error=str(exc),iterations_attempted=index)
    (folder/'flowsheet_result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('recycle','external_feeds','external_products')},indent=2),flush=True)
    return 0 if result['full_numerical_flowsheet_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
