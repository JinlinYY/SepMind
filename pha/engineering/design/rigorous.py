"""Bounded, evidence-driven redesign using native DWSIM fixed-design columns.

The first CMO design remains an immutable screening artifact. Each rejected
MESH solution is retained; compositions are outputs, never simulator specs.
"""
import json
import math
from dataclasses import asdict
from pathlib import Path

from separation.tools.dwsim import DwsimBackend, RigorousColumnRequest, BinaryVLERequest

COMPOUNDS = {'71-43-2':'Benzene', '108-88-3':'Toluene', '67-56-1':'Methanol',
             '7732-18-5':'Water', '64-17-5':'Ethanol',
             '142-82-5':'n-Heptane', '111-84-2':'n-Nonane'}


def warm_start(record, count, feed, reflux):
    """Interpolate a converged counterexample, retaining separate tower sections.

    These are explicitly numerical initial guesses, not new physical results.
    """
    import numpy as np
    profiles=record['outputs']['stage_profiles']
    old=record['request']; old_n=old['equilibrium_stages']; old_feed=old['feed_stage']
    coordinates=[i*old_feed/feed if i<=feed else old_feed+(i-feed)*(old_n-old_feed)/(count-feed)
                 for i in range(count+1)]
    fields={key:np.interp(coordinates,list(range(old_n+1)),[p[key] for p in profiles])
            for key in ('temperature_K','liquid_flow_mol_s','vapor_flow_mol_s')}
    for name,phase in (('liquid_light_fraction','liquid_mole_fractions'),('vapor_light_fraction','vapor_mole_fractions')):
        fields[name]=np.interp(coordinates,list(range(old_n+1)),[p[phase][0] for p in profiles])
    D=old['distillate_flow_mol_s']
    result=[]
    for i in range(count+1):
        row={key:float(values[i]) for key,values in fields.items()}
        row['vapor_flow_mol_s']*= (reflux+1)/(old['reflux_ratio']+1)
        if i<count:
            row['liquid_flow_mol_s']+=D*(reflux-old['reflux_ratio'])
        result.append(row)
    return result


def product_checks(record, basis, expected_reflux=None):
    """Recompute closure and strict specifications from raw stream results."""
    o = record['outputs']
    f, d, b = [o[k] for k in ('feed', 'distillate', 'bottoms')]
    F, D, B = [s['flow_mol_s'] for s in (f, d, b)]
    residual = max(abs(F*f['mole_fractions'][i]-D*d['mole_fractions'][i]
                       -B*b['mole_fractions'][i])/F for i in range(2))
    recovery = D*d['mole_fractions'][0]/(F*f['mole_fractions'][0])
    h_in = f['mass_flow_kg_s']*f['specific_enthalpy_kJ_kg']+o['reboiler_duty_kW']
    h_out = sum(s['mass_flow_kg_s']*s['specific_enthalpy_kJ_kg'] for s in (d, b))+o['condenser_duty_kW']
    energy_residual = abs(h_in-h_out)/max(o['condenser_duty_kW'],o['reboiler_duty_kW'],1)
    targets = {'distillate':d['mole_fractions'][0] >= basis.target.distillate_mole_fraction}
    if basis.target.bottoms_mole_fraction is not None:
        targets['bottoms'] = b['mole_fractions'][0] <= basis.target.bottoms_mole_fraction
    if basis.target.key_component_recovery is not None:
        targets['recovery'] = recovery >= basis.target.key_component_recovery
    physical = (all(math.isfinite(v) for v in (F,D,B,h_in,h_out,residual,recovery))
        and min(F,D,B,o['condenser_duty_kW'],o['reboiler_duty_kW']) > 0
        and all(all(0<=x<=1 for x in s['mole_fractions'])
                and abs(sum(s['mole_fractions'])-1)<1e-7 for s in (f,d,b)))
    from .binary import material_balance
    expected=material_balance(basis)
    request=record['request']
    fixed_inputs = (abs(F-expected['F_kmol_h']/3.6)/F<=1e-7
        and abs(D-expected['D_kmol_h']/3.6)/F<=1e-7
        and abs(f['mole_fractions'][0]-basis.feed.composition[0])<=1e-8
        and abs(request['pressure_pa']-basis.feed.pressure_kPa*1000)<=1e-5
        and request['equilibrium_stages']<=basis.column.max_stages)
    fixed_r=basis.column.reflux_ratio
    if basis.column.reflux_multiplier is not None:
        if expected_reflux is None:
            raise ValueError('DATA_PARAMETER_MISSING: independent review requires the screened R/Rmin operating reflux')
        fixed_r=expected_reflux
    if fixed_r is not None:
        fixed_inputs &= abs(request['reflux_ratio']-fixed_r)<=1e-8*max(fixed_r,1)
    mass_residual=abs(f['mass_flow_kg_s']-d['mass_flow_kg_s']-b['mass_flow_kg_s'])/f['mass_flow_kg_s']
    closure = physical and residual <= 1e-4 and abs(F-D-B)/F <= 1e-6 and mass_residual<=1e-4 and energy_residual <= 1e-4
    return {'passed':bool(closure and fixed_inputs and all(targets.values())), 'strict_targets':targets,
            'frozen_user_inputs_preserved':bool(fixed_inputs),'total_mass_relative_residual':mass_residual,
            'physical':physical, 'material_and_energy_closure':bool(closure),
            'component_residual_relative_to_feed':residual,
            'energy_residual_relative_to_duty':energy_residual, 'light_recovery':recovery,
            'specification_tolerance_relaxation':0.0}


def native_vle_candidates(backend,basis,balance,names,package,reflux,fixed_reflux,folder,screening_minimum=None):
    """Re-seed synthesis from measured backend disagreement, not guessed stages."""
    import numpy as np
    from scipy.interpolate import PchipInterpolator
    from .binary import minimum_reflux, stages
    # The inverse equilibrium solver brackets on [0,1], including intermediate
    # trial points outside the target interval. Cover the whole binary domain.
    enthalpies=package=='NRTL'
    xs=tuple(sorted({float(x) for x in np.linspace(1e-6,1-1e-6,301 if enthalpies else 201)}
                    | ({float(x) for x in np.geomspace(1e-6,.05,51)} if enthalpies else set())
                    | {balance['xB'],balance['xD'],balance['zF']}))
    record=backend.binary_vle(BinaryVLERequest(names,package,basis.feed.pressure_kPa*1000,xs,enthalpies))
    path=folder/'native_vle.json'
    path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    ys=[p['y'][0] for p in record['points']]
    ts=[p['temperature_k'] for p in record['points']]
    if any(y<=x for x,y in zip(xs,ys) if balance['xB']<=x<=balance['xD']) or any(a>=b for a,b in zip(ys,ys[1:])):
        raise ValueError('NATIVE_VLE_CONFLICT: backend does not support the admitted monotone enrichment interval; model/route review required')
    # Pure-component x=y endpoints are exact identities, not invented property
    # values. No endpoint temperature is supplied or used in this CMO screen.
    yfit=PchipInterpolator([0.,*xs,1.],[0.,*ys,1.],extrapolate=False)
    tfit=PchipInterpolator(xs,ts,extrapolate=False)
    class NativeEquilibrium:
        def point(self,x,pressure):
            y=float(yfit(x))
            if not math.isfinite(y):
                raise ValueError('MODEL_OUT_OF_RANGE: native VLE interpolation cannot extrapolate')
            return {'x':[x,1-x],'y':[y,1-y]}
    equilibrium=NativeEquilibrium()
    minimum=minimum_reflux(equilibrium,basis,balance)
    gap=abs(minimum['minimum_reflux_ratio']/screening_minimum-1) if screening_minimum and screening_minimum>0 else None
    refine_energy=enthalpies and gap is not None and gap>.1
    screens=[];candidates=[]; initial_profiles={};energy_checks=[]
    ratios=[reflux] if fixed_reflux else [reflux*f for f in (1.,1.15,1.3,1.5,2.)]
    for r in ratios:
        effective=basis.model_copy(deep=True)
        effective.column.reflux_multiplier=None
        effective.column.reflux_ratio=r
        effective.assumptions=list(set(effective.assumptions+['constant_molar_overflow']))
        try:
            screen=stages(equilibrium,effective,balance,minimum)
            screens.append({'status':'computed','reflux_ratio':r,
                'equilibrium_stages':screen['theoretical_stages_rounded_up'],
                'feed_stage':screen['feed_stage_from_top']})
            # Add two contacts in each section to account for CMO/MESH deviation;
            # this is an initial design margin, never a performance claim.
            N=screen['theoretical_stages_rounded_up']; feed=screen['feed_stage_from_top']
            margins=(4,8,12,16,24,32) if fixed_reflux else (4,)
            source_x=[balance['xD']]+[step['x'] for step in screen['steps'][:-1]]+[balance['xB']]
            source_x=[max(balance['xB'],min(balance['xD'],x)) for x in source_x]
            for k in margins:
                count,location=N+k,min(N+k-1,feed+k//2)
                candidate=(count,location,r);candidates.append(candidate)
                coordinates=[i*feed/location if i<=location else feed+(i-location)*(N-feed)/(count-location)
                             for i in range(count+1)]
                xi=np.interp(coordinates,list(range(N+1)),source_x)
                D,F,B=[balance[key]/3.6 for key in ('D_kmol_h','F_kmol_h','B_kmol_h')]
                profile=[]
                for i,x in enumerate(xi):
                    profile.append({'temperature_K':float(tfit(x)),
                        'liquid_flow_mol_s':B if i==count else r*D+(F if i>=location else 0.),
                        'vapor_flow_mol_s':0. if i==0 else (r+1)*D,
                        'liquid_light_fraction':float(x),
                        'vapor_light_fraction':balance['xD'] if i==0 else float(yfit(x))})
                initial_profiles[f'{count}:{location}:{r:.12g}']=profile
                if refine_energy:
                    from .enthalpy_seed import coupled_initial_profile
                    coupled=coupled_initial_profile(record['points'],balance,r,count,location)
                    energy_checks.append({'equilibrium_stages':count,'feed_stage':location,'reflux_ratio':r,
                                          **{key:value for key,value in coupled.items() if key!='profile'}})
                    if coupled['status']=='initial_guess':
                        initial_profiles[f'{count}:{location}:{r:.12g}']=coupled['profile']
        except ValueError as exc:
            screens.append({'status':'rejected','reflux_ratio':r,'reason':str(exc)})
    result = {'source_evidence_id':record['evidence_id'],'evidence_file':str(path),
            'minimum_reflux':minimum,'screens':screens,'candidates':candidates,
            'initial_profiles':initial_profiles,
            'relative_minimum_reflux_disagreement':gap,
            'initialization_model':'native_enthalpy_coupled_shooting' if refine_energy else 'native_VLE_CMO',
            'enthalpy_initialization_checks':energy_checks,
            'initial_profile_scope':'numerical guesses from native VLE, upgraded to energy-coupled stage balances when indicated; not native MESH performance',
            'interpolation':'201 interior grid points plus exact target/feed points and mathematical pure-component x=y endpoints; PCHIP with no extrapolation',
            'meaning':'same-backend equilibrium reinitialization after CMO/MESH counterevidence; not independent experimental proof'}
    result['resynthesis_file']=str(folder/'native_vle_resynthesis.json')
    (folder/'native_vle_resynthesis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def refine_column(basis, balance, screening, output_dir, backend=None):
    backend = backend or DwsimBackend(timeout_s=180)
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    n = math.ceil(screening['theoretical_stages_fractional'])
    feed = int(screening['feed_stage_from_top'])
    r = float(screening['reflux_ratio'])
    names = tuple(COMPOUNDS[c.cas or c.canonical_id] for c in basis.components)
    from ..thermo import selected_model
    package = 'NRTL' if selected_model(basis)=='NRTL' else "Raoult's Law"
    attempts = []
    previous = None
    # Preserve operating R or R/Rmin whenever the user supplied either. Otherwise
    # reflux is a design variable, allowed to change after stage-only failures.
    fixed_reflux = basis.column.reflux_ratio is not None or basis.column.reflux_multiplier is not None
    candidates = [(n,min(n-1,feed),r)]
    native_screen = None
    # The queue is expanded from the SAME backend's VLE after a counterexample,
    # rather than assuming the initial CMO model and native MESH are identical.
    for index,(count,location,reflux) in enumerate(candidates):
        if count > min(basis.column.max_stages,300):
            continue
        request = RigorousColumnRequest(names,package,basis.feed.pressure_kPa*1000,
            balance['F_kmol_h']/3.6,balance['zF'],balance['D_kmol_h']/3.6,
            reflux,count,location, save_path=str(folder/f'candidate-{index:02d}.dwxmz'),
            solver_preference='simultaneous_correction' if package=='NRTL' else 'default', include_profiles=True,
            initial_profile=native_screen['initial_profiles'].get(f'{count}:{location}:{reflux:.12g}') if native_screen else None,
            initial_estimate_source_evidence_id=native_screen['source_evidence_id'] if native_screen else None)
        row = {'candidate_id':f'mesh-{index:02d}', 'equilibrium_stages':count,
               'feed_stage':location, 'reflux_ratio':reflux, 'reason':'test CMO design' if index==0
               else 'prior rigorous solution failed; add stages/feed alternatives or increase unconstrained reflux',
               'user_reflux_constraint_preserved':fixed_reflux,
               'equilibrium_stage_limit':basis.column.max_stages}
        request_file=folder/f'candidate-{index:02d}.request.json'
        request_file.write_text(json.dumps(asdict(request),indent=2),encoding='utf-8')
        row['request_file']=str(request_file)
        try:
            record = backend.rigorous_column(request)
            previous = record
            checks = product_checks(record,basis,r)
            path = folder/f'candidate-{index:02d}.json'
            path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            row.update(status='accepted' if checks['passed'] else 'rejected',
                       validation=checks,evidence_file=str(path),evidence_id=record['evidence_id'],
                       outputs={k:record['outputs'][k] for k in ('distillate','bottoms','light_recovery',
                                  'condenser_duty_kW','reboiler_duty_kW')})
        except (RuntimeError,TimeoutError) as exc:
            record = None
            row.update(status='solver_failed',error=str(exc)[:4000])
        attempts.append(row)
        # Write incremental audit even if a later native worker fails.
        (folder/'redesign_history.json').write_text(json.dumps(attempts,indent=2),encoding='utf-8')
        if row['status']=='accepted':
            return {'passed':True,'selected_candidate':row,'attempts':attempts,
                'selected_simulation':record,'policy':'bounded stage/feed then unconstrained reflux redesign; first strict feasible candidate',
                'global_optimality_proven':False,'pressure_drop_included':False,
                'native_equilibrium_screen':{k:v for k,v in native_screen.items() if k!='initial_profiles'} if native_screen else None}
        if index==0:
            try:
                native_screen = native_vle_candidates(backend,basis,balance,names,package,r,fixed_reflux,folder,
                                                     screening.get('minimum_reflux_ratio'))
            except (RuntimeError,TimeoutError,ValueError) as exc:
                native_screen={'error':str(exc),'evidence_file':str(folder/'native_vle.json'),
                               'meaning':'backend equilibrium disagreement or numerical failure requires review; no guessed replacement stages'}
                break
            candidates.extend(native_screen['candidates'])
    return {'passed':False,'attempts':attempts,'selected_candidate':None,
            'termination':'bounded candidates exhausted or user stage limit reached',
            'constraints_relaxed':False,'native_equilibrium_screen':{k:v for k,v in native_screen.items() if k!='initial_profiles'} if native_screen else None}


def energy_balance(record):
    o = record['outputs']
    rows = {k:{'mass_flow_kg_s':o[k]['mass_flow_kg_s'],
               'specific_enthalpy_kJ_kg':o[k]['specific_enthalpy_kJ_kg'],
               'enthalpy_flow_kW':o[k]['mass_flow_kg_s']*o[k]['specific_enthalpy_kJ_kg']}
            for k in ('feed','distillate','bottoms')}
    qr,qc = o['reboiler_duty_kW'],o['condenser_duty_kW']
    residual = rows['feed']['enthalpy_flow_kW']+qr-rows['distillate']['enthalpy_flow_kW']-rows['bottoms']['enthalpy_flow_kW']-qc
    relative = abs(residual)/max(qr,qc,1)
    return {'passed':relative<=1e-4 and min(qr,qc)>0,'streams':rows,
            'condenser_duty_kW':qc,'reboiler_duty_kW':qr,
            'residual_kW':residual,'relative_residual':relative,
            'equation':'F*hF + QR = D*hD + B*hB + QC',
            'heat_loss_kW':0,'source_evidence_id':record['evidence_id'],
            'scope':'native equilibrium-stage enthalpy balance at uniform specified pressure; no exchanger rating'}
