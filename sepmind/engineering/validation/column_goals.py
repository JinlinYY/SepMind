"""Review process goals independently of a solver's chosen D/R/N settings."""
import math
from typing import Literal
from pydantic import Field
from ..schemas import Contract
from sepmind.simulation.mixture import CandidateColumnRequest, mixture_card


class ColumnProductGoal(Contract):
    goal_id: str=Field(min_length=1)
    product: Literal['distillate','bottoms']
    component_id: str
    quantity: Literal['mass_fraction','recovery']
    minimum: float=Field(gt=0,le=1)
    source_id: str=Field(min_length=1)


def review_column_goals(native, expected_feed, goals):
    """Recompute component closure and goals from the actual port vectors.

    Goal satisfaction here is conditional on the candidate model, not a grant
    of thermodynamic qualification or a complete-flowsheet success.
    """
    expected_feed=CandidateColumnRequest.model_validate(expected_feed)
    goals=[ColumnProductGoal.model_validate(g) for g in goals]
    if not goals or len({g.goal_id for g in goals})!=len(goals):
        raise ValueError('Distinct explicit unit goals required')
    card,digest=mixture_card(expected_feed.property_card_id)
    ids=card['component_order'];mw=card['molecular_weights_g_mol']
    if any(g.component_id not in ids for g in goals):raise ValueError('Unknown goal component')
    actual=CandidateColumnRequest.model_validate(native['request'])
    frozen=('property_card_id','feed_mole_fractions','feed_molar_flow_mol_s','pressure_pa','feed_temperature_K','bottom_pressure_pa')
    if any(getattr(actual,k)!=getattr(expected_feed,k) for k in frozen):
        raise ValueError('Frozen feed or model changed')
    if native.get('intermediate_not_physical_result',True) or native.get('parameter_sha256')!=digest:
        raise ValueError('Full physical model and matching parameter evidence required')
    streams=native['outputs'];vectors={}
    mass_flow_errors=[]
    for port in ('feed','distillate','bottoms'):
        s=streams[port];xs=s['mole_fractions'];flow=s['flow_mol_s']
        if (len(xs)!=len(ids) or not math.isfinite(flow) or flow<=0
            or any(not math.isfinite(x) or x<0 or x>1 for x in xs) or abs(sum(xs)-1)>1e-7):
            raise ValueError('Invalid native product vector')
        vectors[port]=[flow*x for x in xs]
        mass_expected=sum(a*b for a,b in zip(vectors[port],mw))/1000
        mass_reported=s['mass_flow_kg_s']
        if not math.isfinite(mass_reported) or mass_reported<=0:raise ValueError('Invalid native mass flow')
        mass_flow_errors.append(abs(mass_reported-mass_expected)/mass_expected)
    expected=[expected_feed.feed_molar_flow_mol_s*x for x in expected_feed.feed_mole_fractions]
    scale=expected_feed.feed_molar_flow_mol_s
    feed_error=max(abs(a-b) for a,b in zip(vectors['feed'],expected))/scale
    closure=max(abs(f-d-b) for f,d,b in zip(expected,vectors['distillate'],vectors['bottoms']))/scale
    heat={p:streams[p]['mass_flow_kg_s']*streams[p]['specific_enthalpy_kJ_kg'] for p in vectors}
    qc=streams['condenser_duty_kW'];qr=streams['reboiler_duty_kW']
    energy=abs(heat['feed']+qr-heat['distillate']-heat['bottoms']-qc)/max(abs(qc),abs(qr),1)
    numerical=(all(math.isfinite(x) for x in (closure,feed_error,energy))
               and max(closure,feed_error)<=1e-4 and energy<=1e-4 and max(mass_flow_errors)<=1e-4)
    rows=[]
    for g in goals:
        i=ids.index(g.component_id);v=vectors[g.product]
        if g.quantity=='recovery':
            if expected[i]<=0:raise ValueError('Recovery denominator is zero')
            value=v[i]/expected[i]
        else:value=v[i]*mw[i]/sum(a*b for a,b in zip(v,mw))
        rows.append(g.model_dump()|{'computed':value,'passed':math.isfinite(value) and value>=g.minimum})
    return {'conditional_unit_goals_passed':numerical and all(g['passed'] for g in rows),
            'component_balance_relative_residual':closure,'feed_error_relative':feed_error,
            'maximum_mass_mole_conversion_error':max(mass_flow_errors),
            'energy_balance_relative_residual':energy,'numerical_passed':numerical,'goals':rows,
            'design_admitted':False,'whole_process_completed':False,
            'scope':'Conditional unit-design experiment; property, phase-stability and whole-flowsheet qualification remain separate'}


def review_candidate_stage_equilibrium(native, backend):
    """Use native pure correlations and a separate NRTL implementation.

    This diagnostic is restricted to the explicitly ideal-vapor ABE card. It
    excludes the total condenser from vapor-liquid equilibrium, but includes
    every liquid phase in a finite multistart tangent-plane screen.
    """
    import numpy as np
    from sepmind.simulation.mixture import MixtureProbeRequest
    from .extraction import independent_lngamma
    from ..thermo.lle import NRTLModel, stability_screen
    request=CandidateColumnRequest.model_validate(native['request'])
    card,digest=mixture_card(request.property_card_id)
    if native.get('intermediate_not_physical_result',True) or native.get('parameter_sha256')!=digest:
        raise ValueError('Cannot review a homotopy intermediate as physical equilibrium')
    profiles=native['outputs']['stage_profiles']
    if len(profiles)!=request.equilibrium_stages+1:raise ValueError('Missing complete native profiles')
    pure=backend.mixture_probe(MixtureProbeRequest(property_card_id=request.property_card_id,points=[
        {'point_id':str(i),'mole_fractions':s['liquid_mole_fractions'],
         'temperature_K':s['temperature_K'],'pressure_Pa':s['pressure_Pa'],'specification':'pure_properties'}
        for i,s in enumerate(profiles) if i>0]))
    mapped={p['point_id']:p for p in pure['points']}
    if len(mapped)!=len(profiles)-1:raise ValueError('Native pure-property point coverage mismatch')
    model=NRTLModel(card);rows=[]
    for i,s in enumerate(profiles):
        row={'stage':i,'liquid_stability_screen':stability_screen(model,s['liquid_mole_fractions'],s['temperature_K'])}
        if i>0:
            p=mapped[str(i)]
            if not p.get('executed'):raise ValueError('Native pure-property evaluation failed')
            x=np.array(s['liquid_mole_fractions']);y=np.array(s['vapor_mole_fractions'])
            gamma=np.exp(independent_lngamma(x,s['temperature_K'],card))
            pv=np.array(p['native_vapor_pressures_Pa_at_reference_T'])
            active=(x>1e-12)|(y>1e-12)
            if not active.any():raise ValueError('No active stage components')
            if min(x[active])<=0 or min(y[active])<=0:raise ValueError('Unmatched active phase components')
            row['maximum_log_fugacity_residual']=float(max(abs(np.log((x*gamma*pv/s['pressure_Pa'])[active]/y[active]))))
        rows.append(row)
    maximum=max(r.get('maximum_log_fugacity_residual',0.) for r in rows)
    minimum_tpd=min(r['liquid_stability_screen']['minimum_tpd'] for r in rows)
    return {'passed':maximum<=1e-3 and minimum_tpd>=-1e-6,'maximum_log_fugacity_residual':maximum,
            'minimum_liquid_tpd':minimum_tpd,'stages':rows,'native_pure_property_evidence':pure,
            'design_admitted':False,'scope':'Candidate ideal-vapor NRTL stage check and finite liquid-stability screening; no global or experimental qualification'}
