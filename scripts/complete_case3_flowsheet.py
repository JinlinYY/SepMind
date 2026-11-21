"""Bounded, real source-informed sulfolane LLX/wash/recovery/decanter recycle.

Uses typed native DWSIM columns/properties/decanter and independently re-flashed
NRTL extraction stages. No source purity or recovery factor fills a stream.
This is a research calculation, outside production property admission.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from separation.tools.mixture import mixture_card,MixtureProbeRequest
from separation.tools.multifeed import MultiFeedColumnRequest,MultiFeedDwsimBackend
from pha.engineering.thermo.lle import NRTLModel,flash_lle,stability_screen
from pha.engineering.design.extraction import contact
from pha.engineering.design.extraction_simultaneous import extraction_simultaneous
from pha.engineering.design.recycle import converge_component_recycle
from pha.engineering.validation.multifeed import review_multifeed_column
from pha.engineering.validation.initialization import material_consistent_profile
from scripts.run_case5_native import run

def read(path):return json.loads(path.read_text(encoding='utf8'))
def save(path,value):path.write_text(json.dumps(value,indent=2),encoding='utf8')
def port_vector(port):return port['flow_mol_s']*3.6*np.asarray(port['mole_fractions'])
def port_heat(port):return port['mass_flow_kg_s']*port['specific_enthalpy_kJ_kg']
FIELDS=('temperature_K','liquid_flow_mol_s','vapor_flow_mol_s','liquid_mole_fractions','vapor_mole_fractions')

class Case3:
    def __init__(self,folder,sf,extraction_temperature_K=293.15,pressure_drops_kPa=(0.,0.)):
        self.folder=folder;folder.mkdir(parents=True,exist_ok=True);self.sf=sf;self.index=0
        self.temperature_K=float(extraction_temperature_K)
        self.pressure_drops_kPa=tuple(float(v) for v in pressure_drops_kPa)
        if len(self.pressure_drops_kPa)!=2 or any(not 0<=v<=10 for v in self.pressure_drops_kPa):raise ValueError('Declared research pressure-drop sensitivity outside0..10kPa')
        if not 293.15<=self.temperature_K<=315.:raise ValueError('Research extraction temperature outside declared 293.15..315 K')
        self.backend=MultiFeedDwsimBackend(timeout_s=100)
        card,self.lle_digest=mixture_card('mch_toluene_sulfolane_lle_brouwer2021');self.model=NRTLModel(card)
        self.vle_card,self.vle_digest=mixture_card('mch_toluene_sulfolane_vle_brouwer2021')
        z=np.array([.6,.4,0.,0.]);self.fresh=z*100000/(z@self.model.mw)
        self.solvent_target=sf*sum(self.fresh)
        self.water_target=self.solvent_target*self.model.mw[2]*.01/self.model.mw[3]
        self.main=read(ROOT/'output/engineering/case3_molar_extraction_20261110/N8_molarSF3.5.json')['raw']
        self.wash=read(ROOT/'output/engineering/case3_water_wash_20261110/wash_N2.json')['raw']
        self.c1=read(ROOT/'output/engineering/case3_native_recovery_20261110/C1_N7.json')
        self.c2=read(ROOT/'output/engineering/case3_repair_20261110/revised_draw_balanced.json')
        dec=read(ROOT/'output/engineering/case3_repair_20261110/seeded_decanter.json')['points'][0]
        org,aq=sorted(dec['phases'],key=lambda p:-p['composition'][1])
        vapor_total=self.c2['outputs']['overhead_vapor']['flow_mol_s']*3.6
        organic=vapor_total*org['molar_fraction']*np.asarray(org['composition'])
        aqueous=vapor_total*aq['molar_fraction']*np.asarray(aq['composition'])
        solv=port_vector(self.c2['outputs']['bottoms']);solv*=self.solvent_target/solv[2]
        water=aqueous*self.water_target/aqueous[3]*.999
        self.initial=np.r_[solv,water,port_vector(self.c1['outputs']['distillate']),.6*organic]
        self.ledger=[];self.last=None

    def references(self,items):
        q=MixtureProbeRequest(property_card_id=self.vle_card['model_id'],points=[dict(point_id=k,mole_fractions=(v/sum(v)).tolist(),
            temperature_K=t,pressure_Pa=p,specification='pure_properties') for k,(v,t,p) in items.items()])
        raw=self.backend.mixture_probe(q);save(self.folder/f'{self.index:02d}_properties_{len(items)}.json',raw)
        result={}
        for row in raw['points']:
            if not row.get('executed'):raise ValueError('Native liquid-reference property failed: '+str(row))
            v,t,p=items[row['point_id']];hm=row['native_liquid_specific_enthalpy_kJ_kg']*row['native_liquid_molecular_weight_kg_kmol']/1000
            result[row['point_id']]=dict(heat_kW=float(sum(v)/3.6*hm),h_kJ_kg=row['native_liquid_specific_enthalpy_kJ_kg'],
                rho=row['native_liquid_density_kg_m3'],mass_kg_s=float(sum(v)/3.6*row['native_liquid_molecular_weight_kg_kmol']/1000))
        return result

    def lle(self,feed,solvent,old,n,carrier,label):
        profiles=copy.deepcopy(old['profiles']);old_f=np.asarray(old['feed_kmol_h']);old_s=np.asarray(old['solvent_kmol_h'])
        factor=(sum(feed)+sum(solvent))/(sum(old_f)+sum(old_s))
        single=None
        if len(profiles[0]['raffinate_kmol_h'])==3:single=contact(self.model,feed+solvent,self.temperature_K,100000.,carrier,require_qualified=False)
        for row in profiles:
            for key in ('raffinate_kmol_h','extract_kmol_h'):
                row[key]=(np.asarray(row[key])*factor).tolist()
                if single is not None:
                    phase=single[0 if key=='raffinate_kmol_h' else 1]
                    row[key].append(float(phase[3]/sum(phase)*sum(row[key])))
        raw=extraction_simultaneous(self.model,feed,solvent,self.temperature_K,100000.,n,carrier,profiles,require_qualified=False,max_evaluations=600)
        save(self.folder/f'{self.index:02d}_{label}.json',raw)
        return raw

    def column(self,old,feeds,draw,label):
        data=copy.deepcopy(old['request']);profile=[{k:row[k] for k in FIELDS} for row in old['outputs']['stage_profiles']]
        factor=sum(f['flow_mol_s'] for f in feeds)/sum(f['flow_mol_s'] for f in data['feeds'])
        water=sum(f['flow_mol_s']*f['mole_fractions'][3] for f in feeds)/sum(f['flow_mol_s'] for f in feeds)
        for row in profile:
            row['liquid_flow_mol_s']*=factor;row['vapor_flow_mol_s']*=factor
            for key in ('liquid_mole_fractions','vapor_mole_fractions'):
                if row[key][3]==0 and water>0:
                    row[key]=[(1-water)*v for v in row[key]];row[key][3]=water
        data.update(feeds=feeds,distillate_flow_mol_s=float(draw),initial_profile=profile,
            bottom_pressure_pa=8000.+1000*self.pressure_drops_kPa[0 if label=='C1' else 1],
            initial_estimate_source_evidence_id=old['evidence_id'],purpose='design_candidate',
            numerical_solver='sparse_trust_region',numerical_jacobian_policy='balanced_reduced',solver_tolerance=1e-9,
            solver_iteration_limit=60,solver_attempt_limit=1,save_path=str(self.folder/f'{self.index:02d}_{label}.dwxmz'))
        request=MultiFeedColumnRequest.model_validate(data)
        if request.column_mode=='total_condenser':
            projected,audit=material_consistent_profile(request)
            save(self.folder/f'{self.index:02d}_{label}.initialization.json',audit)
            request=MultiFeedColumnRequest.model_validate(data|dict(initial_profile=projected))
        raw=run(request,self.backend,self.folder/f'{self.index:02d}_{label}.json')
        if not raw.get('outputs'):raise ValueError('Native '+label+' failed; see retained unit record')
        review=review_multifeed_column(raw,self.backend);save(self.folder/f'{self.index:02d}_{label}.review.json',review)
        if not all(review[k] for k in ('numerical_passed','stage_equilibrium_passed','independent_finite_liquid_screen_passed')):
            raise ValueError('Independent '+label+' review failed')
        return raw

    def unit_map(self,guess):
        self.index+=1;solv_rec,water_rec,hc_rec,reflux=guess.reshape(4,4)
        sm=self.solvent_target-solv_rec[2];wm=self.water_target-water_rec[3]
        if min(sm,wm)<-1e-9:raise ValueError('Circulation exceeded: purge or changed setpoint required')
        sm=max(float(sm),0.);wm=max(float(wm),0.)
        solvent=solv_rec+np.array([0.,0.,sm,0.]);water=water_rec+np.array([0.,0.,0.,wm]);feed=self.fresh+hc_rec
        self.main=self.lle(feed,solvent,self.main,8,0,'main_LLX')
        raff=np.asarray(self.main['raffinate_kmol_h']);extract=np.asarray(self.main['extract_kmol_h'])
        self.wash=self.lle(raff,water,self.wash,2,0,'water_wash')
        mch=np.asarray(self.wash['raffinate_kmol_h']);wash_extract=np.asarray(self.wash['extract_kmol_h'])
        refs=self.references(dict(extract=(extract,self.temperature_K,100000.),wash_extract=(wash_extract,self.temperature_K,100000.),reflux=(reflux,298.15,8000.)))
        def feed_row(label,v,t,stage,reference,eid):
            return dict(feed_id=label,flow_mol_s=float(sum(v)/3.6),mole_fractions=(v/sum(v)).tolist(),temperature_K=t,
                        stage_index=stage,specific_enthalpy_kJ_kg=reference['h_kJ_kg'],source_evidence_id=eid)
        f1=feed_row('Actual_main_extract',extract,self.temperature_K,1,refs['extract'],f'case3:{self.index}:main_LLX')
        self.c1=self.column(self.c1,[f1],(extract[0]+.5*extract[1])/3.6,'C1')
        bottom=self.c1['outputs']['bottoms'];bvec=port_vector(bottom)
        f2=[feed_row('Actual_organic_reflux',reflux,298.15,0,refs['reflux'],f'case3:{self.index}:organic_tear'),
            dict(feed_id='Actual_C1_bottoms',flow_mol_s=bottom['flow_mol_s'],mole_fractions=bottom['mole_fractions'],
                 temperature_K=bottom['temperature_K'],specific_enthalpy_kJ_kg=bottom['specific_enthalpy_kJ_kg'],stage_index=1,source_evidence_id=self.c1['evidence_id']),
            feed_row('Actual_water_wash_extract',wash_extract,self.temperature_K,5,refs['wash_extract'],f'case3:{self.index}:water_wash')]
        fc=sum(f['flow_mol_s']*np.asarray(f['mole_fractions']) for f in f2)
        # A declared operating candidate, not an imposed recovery/result. The
        # original draw based on assumed solute recoveries failed native MESH.
        draw=float(sum(fc)-fc[2]+max(.003,3e-6*fc[2]))
        self.c2=self.column(self.c2,f2,draw,'C2')
        vapor=self.c2['outputs']['overhead_vapor'];vvec=port_vector(vapor)
        q=MixtureProbeRequest(property_card_id=self.model.card['model_id'],phase_policy='direct_lle',lle_initialization='independent_gibbs',points=[
            dict(point_id='actual_C2_condensate',mole_fractions=vapor['mole_fractions'],temperature_K=298.15,pressure_Pa=8000.,specification='TP')])
        native=self.backend.mixture_probe(q);save(self.folder/f'{self.index:02d}_decanter.json',native);dec=native['points'][0]
        if not dec['converged'] or len(dec['phases'])!=2 or not dec.get('ideal_vapor_screen_passed'):raise ValueError('Decanter split/vapor stability not accepted')
        independent=flash_lle(self.model,vapor['mole_fractions'],298.15,8000.,require_qualified=False)
        native_phases=sorted(dec['phases'],key=lambda p:-p['composition'][1]);ind_phases=sorted(independent['phases'],key=lambda p:-p['composition'][1])
        for a,b in zip(native_phases,ind_phases):
            if max(abs(np.asarray(a['composition'])-b['composition']))>1e-6 or abs(a['molar_fraction']-b['fraction'])>1e-6:
                raise ValueError('Native/independent decanter disagreement')
        org,aq=native_phases;organic=sum(vvec)*org['molar_fraction']*np.asarray(org['composition']);aqueous=sum(vvec)*aq['molar_fraction']*np.asarray(aq['composition'])
        new_reflux=.6*organic;tol=.4*organic;new_solv=port_vector(self.c2['outputs']['bottoms']);new_hc=port_vector(self.c1['outputs']['distillate'])
        returned=np.r_[new_solv,aqueous,new_hc,new_reflux]
        record=dict(iteration=self.index,input_component_kmol_h=guess.tolist(),returned_component_kmol_h=returned.tolist(),
            solvent_makeup_kmol_h=sm,water_makeup_kmol_h=wm,product_MCH_kmol_h=mch.tolist(),product_TOL_kmol_h=tol.tolist(),
            MCH_mass_fraction=float(mch[0]*self.model.mw[0]/(mch@self.model.mw)),TOL_mass_fraction=float(tol[1]*self.model.mw[1]/(tol@self.model.mw)),
            unit_evidence_ids=[self.c1['evidence_id'],self.c2['evidence_id'],native['evidence_id']],
            C1_reboiler_kW=self.c1['outputs']['reboiler_duty_kW'],C2_reboiler_kW=self.c2['outputs']['reboiler_duty_kW'])
        self.ledger.append(record);save(self.folder/'iteration_ledger.json',self.ledger)
        self.last=dict(record=record,feed=feed,solvent=solvent,water=water,raff=raff,extract=extract,wash_extract=wash_extract,mch=mch,tol=tol,
                       new_solv=new_solv,new_hc=new_hc,aqueous=aqueous,new_reflux=new_reflux,reflux=reflux,org=org,aq=aq,organic=organic)
        print(json.dumps(dict(iteration=self.index,MCH=record['MCH_mass_fraction'],TOL=record['TOL_mass_fraction'])),flush=True)
        return dict(validated=True,recycle_component_flows=returned.tolist(),iteration=self.index)

    def finalize(self,recycle):
        l=self.last;r=l['record'];sm=r['solvent_makeup_kmol_h'];wm=r['water_makeup_kmol_h']
        smv=np.array([0.,0.,sm,0.]);wmv=np.array([0.,0.,0.,wm])
        # Native reference enthalpies preserve a single explicit ideal-caloric
        # convention across the phase-specific equilibrium parameter sets.
        items={k:(l[k],self.temperature_K,100000.) for k in ('feed','solvent','water','raff','extract','wash_extract','mch','new_solv','new_hc','aqueous')}
        items.update(fresh=(self.fresh,293.15,100000.),sm=(np.array([0.,0.,1.,0.]),self.temperature_K,100000.),
                     wm=(np.array([0.,0.,0.,1.]),self.temperature_K,100000.),tol=(l['tol'],298.15,100000.))
        tear=np.asarray(r['input_component_kmol_h']).reshape(4,4)
        for name,v in zip(('input_solv','input_water','input_hc'),tear[:3]):items[name]=(v,self.temperature_K,100000.)
        ref=self.references(items)
        hin=ref['fresh']['heat_kW']+sm*ref['sm']['heat_kW']+wm*ref['wm']['heat_kW']
        hout=ref['mch']['heat_kW']+ref['tol']['heat_kW']
        horg=sum(l['organic'])/3.6*float(np.asarray(l['org']['composition'])@self.model.mw)/1000*l['org']['specific_enthalpy_kJ_kg_unqualified']
        haq=sum(l['aqueous'])/3.6*float(np.asarray(l['aq']['composition'])@self.model.mw)/1000*l['aq']['specific_enthalpy_kJ_kg_unqualified']
        # Use native phase molecular masses: source-card mass metadata differs
        # slightly in rounding, so reconstruct phase heat from actual native
        # liquid-reference evaluations at the condenser temperature instead.
        phases=self.references(dict(org=(l['organic'],298.15,8000.),aq=(l['aqueous'],298.15,8000.)))
        horg=phases['org']['heat_kW'];haq=phases['aq']['heat_kW']
        eta=.75;dp=92000.;pumps={}
        for name,stream in [('hc',self.c1['outputs']['distillate']),('solvent',self.c2['outputs']['bottoms'])]:
            pumps[name]=stream['mass_flow_kg_s']/stream['liquid_properties']['density_kg_m3']*(100000.-stream['pressure_Pa'])/eta/1000
        pumps['water']=phases['aq']['mass_kg_s']/l['aq']['density_kg_m3']*dp/eta/1000
        pumps['TOL_product']=.4*phases['org']['mass_kg_s']/l['org']['density_kg_m3']*dp/eta/1000
        cooling=dict(C1_condenser=self.c1['outputs']['condenser_duty_kW'],
            C2_condenser=port_heat(self.c2['outputs']['overhead_vapor'])-horg-haq,
            HC_conditioner=port_heat(self.c1['outputs']['distillate'])+pumps['hc']-ref['new_hc']['heat_kW'],
            solvent_conditioner=port_heat(self.c2['outputs']['bottoms'])+pumps['solvent']-ref['new_solv']['heat_kW'],
            water_conditioner=haq+pumps['water']-ref['aqueous']['heat_kW'],
            # Part of shaft work raises the liquid enthalpy on compression.
            # Only W - deltaH is rejected to hold the product at 298.15 K.
            TOL_isothermal_pump=pumps['TOL_product']+.4*horg-ref['tol']['heat_kW'])
        qe=ref['raff']['heat_kW']+ref['extract']['heat_kW']-ref['feed']['heat_kW']-ref['solvent']['heat_kW']
        qw=ref['mch']['heat_kW']+ref['wash_extract']['heat_kW']-ref['raff']['heat_kW']-ref['water']['heat_kW']
        mixing=dict(feed=ref['feed']['heat_kW']-ref['fresh']['heat_kW']-ref['input_hc']['heat_kW'],
                    solvent=ref['solvent']['heat_kW']-ref['input_solv']['heat_kW']-sm*ref['sm']['heat_kW'],
                    water=ref['water']['heat_kW']-ref['input_water']['heat_kW']-wm*ref['wm']['heat_kW'])
        qr=r['C1_reboiler_kW']+r['C2_reboiler_kW'];qc=sum(cooling.values());work=sum(pumps.values())
        energy=abs(hin+qr+qe+qw+sum(mixing.values())+work-hout-qc)/max(abs(qr),abs(qc),1.)
        incoming=self.fresh+smv+wmv;outgoing=l['mch']+l['tol'];mass=float(max(abs(incoming-outgoing))/sum(self.fresh))
        goals=r['MCH_mass_fraction']>=.9985 and r['TOL_mass_fraction']>=.9985
        numerical=mass<=1e-6 and energy<=1e-6 and recycle['converged']
        return dict(status='numerically_closed_preliminary_flowsheet' if numerical and goals else 'off_spec_or_failed_review',
            full_numerical_flowsheet_passed=bool(numerical and goals),production_design_admitted=False,
            scope='Controlled source-informed research correction; native DWSIM columns/properties/seeded decanter and independent NRTL LLE stages. Not blind autonomous design or one self-contained native GUI flowsheet.',
            original_targets=dict(MCH_mass_fraction_minimum=.9985,TOL_mass_fraction_minimum=.9985),
            MCH_mass_fraction=r['MCH_mass_fraction'],TOL_mass_fraction=r['TOL_mass_fraction'],molar_solvent_fresh_feed_ratio=self.sf,
            extraction_temperature_K=self.temperature_K,
            declared_column_pressure_drop_kPa=self.pressure_drops_kPa,
            component_closure_relative=mass,energy_closure_relative=float(energy),recycle=recycle,
            fresh_sulfolane_kg_h=float(sm*self.model.mw[2]),fresh_water_kg_h=float(wm*self.model.mw[3]),
            total_reboiler_kW=qr,total_cooling_kW=qc,pump_power_kW=pumps,individual_cooling_kW=cooling,
            isothermal_mixing_duty_kW=mixing,
            isothermal_extraction_duty_kW=dict(main=qe,wash=qw),external_input_component_kmol_h=incoming.tolist(),external_output_component_kmol_h=outgoing.tolist(),
            unit_evidence_ids=r['unit_evidence_ids'],model_ids=[self.model.card['model_id'],self.vle_card['model_id']],
            parameter_sha256=[self.lle_digest,self.vle_digest],
            assumptions=['NRTL phase-specific source tables; common native ideal-caloric approximation, not validated excess-enthalpy/energy design.',
                f'E1 8 stages, wash 2 stages at{self.temperature_K}K/100kPa; C1 7 stages plus total condenser R0.3; C2 8 stages with external condenser at8kPa.',
                'Organic reflux fraction0.6 (R1.5). Wash-water component circulation mass1wt% of main sulfolane circulation.',
                f'Condensate298.15K; return streams{self.temperature_K}K; three isothermal mixer duties explicitly evaluated; incompressible pump efficiency0.75 explicitly assumed.',
                'No exchanger heat-recovery optimization, validated hydraulic/equipment rating or plant-operation claim.'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'output/engineering/case3_closed_attempt_20261110')
    parser.add_argument('--sf',type=float,default=5.5);parser.add_argument('--iterations',type=int,default=30)
    parser.add_argument('--extraction-temperature',type=float,default=293.15,help='Declared LLX/wash/return temperature K; historical293.15 K needs an independent solid-phase warning')
    parser.add_argument('--c1-pressure-drop',type=float,default=0.)
    parser.add_argument('--c2-pressure-drop',type=float,default=0.)
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--review-only',action='store_true')
    args=parser.parse_args();runner=Case3(args.output.resolve(),args.sf,args.extraction_temperature,(args.c1_pressure_drop,args.c2_pressure_drop))
    if args.resume:
        previous=read(args.resume/'iteration_ledger.json')[-1];k=previous['iteration']
        runner.initial=np.asarray(previous['returned_component_kmol_h'])
        runner.main=read(args.resume/f'{k:02d}_main_LLX.json');runner.wash=read(args.resume/f'{k:02d}_water_wash.json')
        runner.c1=read(args.resume/f'{k:02d}_C1.json');runner.c2=read(args.resume/f'{k:02d}_C2.json')
    save(runner.folder/'basis_snapshot.json',dict(fresh_component_kmol_h=runner.fresh.tolist(),molar_solvent_fresh_feed_ratio=runner.sf,
        extraction_temperature_K=runner.temperature_K,
        declared_column_pressure_drop_kPa=runner.pressure_drops_kPa,
        sulfolane_component_circulation_kmol_h=runner.solvent_target,water_component_circulation_kmol_h=runner.water_target,
        original_targets=dict(MCH_mass_fraction_minimum=.9985,TOL_mass_fraction_minimum=.9985),
        numerical_seed_parent=str(args.resume) if args.resume else 'Retained independently reviewed source-informed unit calculations',
        production_admitted=False))
    upper=np.full(16,np.inf);upper[2]=runner.solvent_target;upper[7]=runner.water_target
    try:
        if args.review_only:
            if not args.resume:raise ValueError('Retained raw unit run required for review-only')
            original=read(args.resume/'flowsheet_result.json')
            if original['parameter_sha256']!=[runner.lle_digest,runner.vle_digest]:raise ValueError('Changed model evidence')
            if original['molar_solvent_fresh_feed_ratio']!=runner.sf:raise ValueError('Review-only cannot change the saved solvent circulation basis; run the complete flow instead')
            if original.get('extraction_temperature_K',293.15)!=runner.temperature_K:raise ValueError('Review-only cannot change the saved extraction temperature')
            if tuple(original.get('declared_column_pressure_drop_kPa',(0.,0.)))!=runner.pressure_drops_kPa:raise ValueError('Review-only cannot change pressure profile')
            cycle=original['recycle']
            if not cycle['converged']:raise ValueError('Saved recycle did not converge')
            runner.index=k
            for name,native in [('C1',runner.c1),('C2',runner.c2)]:
                review=review_multifeed_column(native,runner.backend);save(runner.folder/f'{k:02d}_{name}.review.json',review)
                if not all(review[a] for a in ('numerical_passed','stage_equilibrium_passed','independent_finite_liquid_screen_passed')):raise ValueError('Saved unit review failed')
            dec=read(args.resume/f'{k:02d}_decanter.json')['points'][0]
            if not dec['converged'] or not dec['ideal_vapor_screen_passed'] or len(dec['phases'])!=2:raise ValueError('Saved decanter not accepted')
            org,aq=sorted(dec['phases'],key=lambda p:-p['composition'][1]);v=port_vector(runner.c2['outputs']['overhead_vapor'])
            organic=sum(v)*org['molar_fraction']*np.asarray(org['composition']);aqueous=sum(v)*aq['molar_fraction']*np.asarray(aq['composition'])
            tear=np.asarray(previous['input_component_kmol_h']).reshape(4,4)
            runner.last=dict(record=previous,feed=runner.fresh+tear[2],solvent=tear[0]+[0.,0.,previous['solvent_makeup_kmol_h'],0.],
                water=tear[1]+[0.,0.,0.,previous['water_makeup_kmol_h']],raff=np.asarray(runner.main['raffinate_kmol_h']),extract=np.asarray(runner.main['extract_kmol_h']),
                wash_extract=np.asarray(runner.wash['extract_kmol_h']),mch=np.asarray(previous['product_MCH_kmol_h']),tol=.4*organic,
                new_solv=port_vector(runner.c2['outputs']['bottoms']),new_hc=port_vector(runner.c1['outputs']['distillate']),
                aqueous=aqueous,new_reflux=.6*organic,reflux=tear[3],org=org,aq=aq,organic=organic)
            save(runner.folder/'review_parent.json',dict(raw_run=str(args.resume.resolve()),last_actual_iteration=k,unit_evidence_ids=previous['unit_evidence_ids']))
        else:
            cycle=converge_component_recycle(runner.unit_map,runner.initial,relative_tolerance=1e-8,max_iterations=args.iterations,
                        damping=1.,acceleration='bounded_wegstein',upper_bounds=upper)
        result=runner.finalize(cycle)
    except Exception as exc:result=dict(status='blocked',full_numerical_flowsheet_passed=False,error=str(exc),iterations_attempted=runner.index)
    save(runner.folder/'flowsheet_result.json',result);print(json.dumps(result,indent=2),flush=True)
    return 0 if result['full_numerical_flowsheet_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
