"""True isothermal equilibrium contacts and bounded liquid-liquid cascades.

Stage exits come from phase equilibrium, never from a supplied recovery/purity.
Countercurrent circulation is solved on individual component flows.
"""
import numpy as np
from ..thermo.lle import flash_lle


def stream_to_molar(stream,model):
    if stream.flow is None or not stream.composition:raise ValueError('INPUT_UNDERDETERMINED: source feed flow/composition required')
    vector=np.array([stream.composition.get(c,0.) for c in model.order])
    if set(stream.composition)-set(model.order):raise ValueError('MODEL_COMPONENT_MISMATCH: a species may not be silently dropped')
    if abs(sum(vector)-1)>1e-8:raise ValueError('SOURCE_COMPOSITION_NONCLOSURE')
    mole=vector if stream.composition_basis=='mole_fraction' else (vector/model.mw)/sum(vector/model.mw)
    total=stream.flow if stream.flow_unit=='kmol/h' else stream.flow/float(mole@model.mw)
    return total*mole


def contact(model,component_in,T,P,carrier_index,stability=True,*,require_qualified=True):
    if type(require_qualified) is not bool:raise ValueError('INVALID_QUALIFICATION_POLICY')
    f=np.asarray(component_in,dtype=float)
    if not np.isfinite(f).all() or min(f)<0 or sum(f)<=0:raise ValueError('INVALID_FLOW: finite nonnegative component flows required')
    result=flash_lle(model,f/sum(f),T,P,check_stability=stability,require_qualified=require_qualified)
    if result['phase_count']!=2:raise ValueError('FEAS_NO_TWO_LIQUIDS: this contact is homogeneous under the admitted model')
    phases=sorted(result['phases'],key=lambda p:-p['composition'][carrier_index])
    R=sum(f)*phases[0]['fraction']*np.array(phases[0]['composition'])
    E=sum(f)*phases[1]['fraction']*np.array(phases[1]['composition'])
    return R,E,result


def extraction_cascade(model,feed,solvent,T,P,stages,carrier_index,solute_index,solvent_index,
                       configuration='countercurrent',max_iterations=80,*,require_qualified=True):
    if type(require_qualified) is not bool:raise ValueError('INVALID_QUALIFICATION_POLICY')
    model.check_domain(T,P,require_qualified=require_qualified)
    if type(stages) is not int or not 1<=stages<=30:raise ValueError('INVALID_STAGES')
    feed=np.asarray(feed,dtype=float);solvent=np.asarray(solvent,dtype=float)
    if feed.shape!=(len(model.order),) or solvent.shape!=feed.shape or not np.isfinite(feed).all() or not np.isfinite(solvent).all() or min(feed)<0 or min(solvent)<0 or sum(feed)*sum(solvent)<=0:
        raise ValueError('INVALID_FLOW: two source-consistent feed vectors required')
    if any(type(i) is not int or not 0<=i<len(feed) for i in (carrier_index,solute_index,solvent_index)) or len({carrier_index,solute_index,solvent_index})!=3:
        raise ValueError('INVALID_COMPONENT_ROLES')
    if feed[solute_index]<=0:raise ValueError('INVALID_FLOW: positive feed solute is required for recovery')
    if type(max_iterations) is not int or not 1<=max_iterations<=300:raise ValueError('INVALID_ITERATION_BUDGET')
    scale=float(sum(feed)+sum(solvent))
    profiles=[];iteration_trace=[]
    if configuration=='crosscurrent':
        raff=feed.copy();extract=np.zeros_like(feed)
        for k in range(stages):
            inlet=raff+solvent/stages
            raff,e,flash=contact(model,inlet,T,P,carrier_index,require_qualified=require_qualified)
            extract+=e
            profiles.append({'stage':k+1,'inlet_kmol_h':inlet.tolist(),'raffinate_kmol_h':raff.tolist(),'extract_kmol_h':e.tolist(),'equilibrium':flash})
        iterations=1
    elif configuration=='countercurrent':
        # Explicit numerical guesses only; not physical outputs.
        R=np.tile(feed,(stages,1));E=np.tile(solvent,(stages,1))
        for iteration in range(max_iterations):
            old_R=R.copy();old_E=E.copy()
            for i in range(stages):
                incoming=(feed if i==0 else R[i-1])+(solvent if i==stages-1 else E[i+1])
                r,e,_=contact(model,incoming,T,P,carrier_index,stability=False,require_qualified=require_qualified)
                R[i]=.65*r+.35*R[i];E[i]=.65*e+.35*E[i]
            change=float(max(np.max(abs(R-old_R)),np.max(abs(E-old_E)))/scale)
            closure=max(float(max(abs((feed if i==0 else R[i-1])+(solvent if i==stages-1 else E[i+1])-R[i]-E[i]))/scale) for i in range(stages))
            iteration_trace.append({'iteration':iteration+1,'maximum_component_flow_change':change,'maximum_stage_closure':closure})
            if max(change,closure)<1e-9:break
        else:raise ValueError(f'EXTRACTION_CASCADE_NONCONVERGENCE: {max_iterations} iterations; no stage output accepted')
        # Recompute each final equilibrium; verify it against converged adjacent
        # component streams, not only an overall solvent total.
        for i in range(stages):
            incoming=(feed if i==0 else R[i-1])+(solvent if i==stages-1 else E[i+1])
            r,e,flash=contact(model,incoming,T,P,carrier_index,stability=True,require_qualified=require_qualified)
            residual=max(float(max(abs(r-R[i]))),float(max(abs(e-E[i]))))/scale
            if residual>1e-7:raise ValueError('EXTRACTION_CASCADE_RECHECK_FAILED: final equilibrium differs from the converged component flows')
            profiles.append({'stage':i+1,'inlet_kmol_h':incoming.tolist(),'raffinate_kmol_h':R[i].tolist(),'extract_kmol_h':E[i].tolist(),'equilibrium':flash})
        raff,extract=R[-1],E[0];iterations=iteration+1
    else:raise ValueError('UNSUPPORTED_EXTRACTION_CONFIGURATION')
    residual=float(max(abs(feed+solvent-raff-extract))/scale)
    mass_residual=float(abs((feed+solvent-raff-extract)@model.mw)/((feed+solvent)@model.mw))
    if max(residual,mass_residual)>1e-7:raise ValueError('EXTRACTION_CLOSURE_FAILED')
    # Feed can contain solute recycled from upstream; specify the extraction
    # endpoint relative to the supplied feed, not a fabricated overall recovery.
    solute_recovery=float((extract[solute_index]-solvent[solute_index])/feed[solute_index])
    return {'configuration':configuration,'stages':stages,'iterations':iterations,
            'property_qualification_required':require_qualified,
            'model_admitted_for_LLE':'LLE' in model.card.get('admitted_phases',[]),
            'feed_kmol_h':feed.tolist(),'solvent_kmol_h':solvent.tolist(),
            'extract_kmol_h':extract.tolist(),'raffinate_kmol_h':raff.tolist(),
            'extract_mass_flow_kg_h':float(extract@model.mw),'raffinate_mass_flow_kg_h':float(raff@model.mw),
            'extract_mass_fractions':(extract*model.mw/(extract@model.mw)).tolist(),
            'raffinate_mass_fractions':(raff*model.mw/(raff@model.mw)).tolist(),
            'solute_extraction_recovery':solute_recovery,
            'solvent_in_raffinate_kg_h':float(raff[solvent_index]*model.mw[solvent_index]),
            'carrier_component_id':model.order[carrier_index],
            'solute_component_id':model.order[solute_index],
            'solvent_component_id':model.order[solvent_index],
            'carrier_coextraction_kg_h':float(extract[carrier_index]*model.mw[carrier_index]),
            'water_coextraction_kg_h':float(extract[carrier_index]*model.mw[carrier_index]) if model.order[carrier_index]=='7732-18-5' else None,
            'profiles':profiles,'iteration_trace':iteration_trace,
            'validation':{'passed':True,'component_relative_residual':residual,'mass_relative_residual':mass_residual},
            'limits':['Isothermal equilibrium contacts, no mass-transfer efficiency or extractor sizing.',
                      'No downstream solvent recovery, recycle closure or energy balance is implied.',
                      'Dilute outlet compositions extend beyond the measured ternary tie-line endpoints; preliminary model extrapolation must be reported.']}
