"""Independent port balances and stage residuals for conditional multifeed runs."""
import math
import numpy as np
from sepmind.simulation.multifeed import MultiFeedColumnRequest
from sepmind.simulation.mixture import mixture_card,MixtureProbeRequest
from ..thermo.unifac_candidate import UNIFACCandidateModel
from ..thermo.lle import stability_screen,NRTLModel


def review_multifeed_column(native,backend):
    request=MultiFeedColumnRequest.model_validate(native['request'])
    external_condenser=request.column_mode=='reboiled_absorber'
    card,digest=mixture_card(request.property_card_id)
    if native.get('parameter_sha256')!=digest:raise ValueError('Changed property evidence')
    outputs=native['outputs'];feeds=outputs['feeds'];n=len(card['component_order'])
    if len(feeds)!=len(request.feeds):raise ValueError('Missing independent feed ports')
    scale=request.feed_molar_flow_mol_s
    inlet=np.zeros(n);input_heat=0.;feed_error=0.;mass_errors=[]
    def vector(s):
        x=np.asarray(s['mole_fractions']);flow=s['flow_mol_s']
        if len(x)!=n or not np.isfinite(x).all() or min(x)<0 or abs(sum(x)-1)>1e-7 or not math.isfinite(flow) or flow<=0:
            raise ValueError('Invalid physical port vector')
        calculated_mass=flow*float(x@np.asarray(card['molecular_weights_g_mol']))/1000
        reported_mass=s['mass_flow_kg_s']
        if not math.isfinite(reported_mass) or reported_mass<=0:raise ValueError('Invalid port mass flow')
        mass_errors.append(abs(reported_mass-calculated_mass)/calculated_mass)
        return flow*x
    for actual,expected in zip(feeds,request.feeds):
        v=vector(actual);inlet+=v
        feed_error=max(feed_error,max(abs(v-expected.flow_mol_s*np.array(expected.mole_fractions)))/scale)
        if not card['temperature_guard_K'][0]<=actual['temperature_K']<=card['temperature_guard_K'][1]:
            raise ValueError('Native feed flash temperature outside the model guard')
        if expected.specific_enthalpy_kJ_kg is None:
            feed_error=max(feed_error,abs(actual['temperature_K']-expected.temperature_K)/expected.temperature_K)
        if expected.specific_enthalpy_kJ_kg is not None:
            feed_error=max(feed_error,abs(actual['specific_enthalpy_kJ_kg']-expected.specific_enthalpy_kJ_kg)/max(abs(expected.specific_enthalpy_kJ_kg),1.))
        input_heat+=actual['mass_flow_kg_s']*actual['specific_enthalpy_kJ_kg']
    d=vector(outputs['distillate']);b=vector(outputs['bottoms'])
    closure=float(max(abs(inlet-d-b))/scale)
    heatout=sum(outputs[k]['mass_flow_kg_s']*outputs[k]['specific_enthalpy_kJ_kg'] for k in ['distillate','bottoms'])
    qc=outputs['condenser_duty_kW'];qr=outputs['reboiler_duty_kW']
    energy=abs(input_heat+qr-heatout-qc)/max(abs(qc),abs(qr),1.)
    profiles=outputs['stage_profiles']
    if len(profiles)!=request.equilibrium_stages+(not external_condenser):raise ValueError('Incomplete stage coverage')
    spec_error=abs(outputs['distillate']['flow_mol_s']-request.distillate_flow_mol_s)/request.distillate_flow_mol_s
    if not external_condenser:spec_error=max(spec_error,abs(profiles[0]['liquid_flow_mol_s']/outputs['distillate']['flow_mol_s']-request.reflux_ratio)/request.reflux_ratio)
    probe=backend.mixture_probe(MixtureProbeRequest(property_card_id=request.property_card_id,points=[
        dict(point_id=str(i),mole_fractions=s['liquid_mole_fractions'],temperature_K=s['temperature_K'],
             pressure_Pa=s['pressure_Pa'],specification='pure_properties') for i,s in enumerate(profiles)]))
    groups=card.get('standard_UNIFAC_groups') or [{9:5,17:1},{9:5,11:1},{1:1,2:5,3:1}]
    independent=NRTLModel(card) if card['model']=='NRTL' else UNIFACCandidateModel(card|{'standard_UNIFAC_groups':groups})
    rows=[]
    for i,(s,p) in enumerate(zip(profiles,probe['points'])):
        if not p.get('executed'):raise ValueError('Stage property evaluation failed')
        row={'stage_index':i,'independent_liquid_tpd':stability_screen(independent,s['liquid_mole_fractions'],s['temperature_K'])['minimum_tpd']}
        if card['model']!='NRTL':row['independent_original_UNIFAC_liquid_tpd']=row['independent_liquid_tpd']
        if i>0 or external_condenser:
            x=np.asarray(s['liquid_mole_fractions']);y=np.asarray(s['vapor_mole_fractions'])
            f=x*np.asarray(p['native_liquid_fugacity_coefficients_at_reference_state'])
            active=(x>1e-12)|(y>1e-12)
            if min(f[active])<=0 or min(y[active])<=0:raise ValueError('Active phase component missing')
            row['maximum_log_fugacity_residual']=float(max(abs(np.log(f[active]/y[active]))))
        rows.append(row)
    equilibrium=max(r.get('maximum_log_fugacity_residual',0.) for r in rows)
    tpd=min(r['independent_liquid_tpd'] for r in rows)
    return dict(numerical_passed=max(feed_error,closure,energy,spec_error,*mass_errors)<=1e-4,
        stage_equilibrium_passed=equilibrium<=1e-3,independent_finite_liquid_screen_passed=tpd>=-1e-6,
        component_closure_relative=closure,energy_closure_relative=energy,feed_error_relative=feed_error,
        maximum_mass_mole_conversion_error=max(mass_errors),
        maximum_specification_relative_error=spec_error,
        maximum_log_fugacity_residual=equilibrium,minimum_independent_liquid_tpd=tpd,stages=rows,
        property_probe_evidence_id=probe['evidence_id'],design_admitted=False,
        independent_liquid_model=card['model'],
        scope='Independent residual arithmetic using native fugacity; separate source-model finite TPD screen. Neither is experimental property qualification or complete-process approval.')
