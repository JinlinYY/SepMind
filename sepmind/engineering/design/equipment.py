"""Sourced preliminary tray estimates and explicit-assumption equipment sizing.

No mechanical rating, manufacturer selection or pressure-feedback certification.
Numerical properties originate in the accepted native column, never in the LLM.
"""
import math

FAIR_SOURCE='https://ris.utwente.nl/ws/portalfiles/portal/312139600/processes_11_01131.pdf'
EFFICIENCY_SOURCE='https://www.sulzer.com/en/-/media/files/products/separation-technology/articles/distillation_trays_that_operate_beyond_the_limits_of_gravity.pdf'
HYDRAULICS_SOURCE='https://archive.nptel.ac.in/content/storage2/courses/103103027/module7/lec2/2.html'


def equipment_policy_for(basis):
    """Explicit teaching assumptions; user-supplied equipment inputs take priority."""
    from ..schemas import EquipmentBasis,F1ValveBasis
    if basis.equipment is not None:
        return basis.equipment,'explicit frozen equipment basis'
    settings={'cooling_inlet_K':293.15,'cooling_outlet_K':308.15}
    origin='agent-proposed teaching assumptions; not site or vendor data'
    if basis.design_id in ('case-1b','case-3'):
        settings.update(condenser_U_W_m2_K=800.,steam_pressure_Pa=351325.)
        origin='source-reported teaching cooling temperatures/U; 0.25 MPa gauge steam normalized to absolute; native IAPWS temperature replaces inconsistent source saturation temperature'
    cf={'case-1a':(.105,'case-1a PDF pp.29-30 report 0.125/0.13; p.34 uses 0.105; conservative conflicting-source teaching assumption'),
        'case-1b':(.126,'case-1b DOCX: entrainment chart reads CF=0.126 in both sections'),
        'case-2':(.105,'case-2 DOCX chapter 7.2: source chart read CF=0.105'),
        'case-3':(.097,'case-3 PDF pp.37-39: rectifying 0.101, stripping 0.097; conservative common teaching coefficient')}
    if basis.design_id in cf:
        value,source=cf[basis.design_id]
        settings['f1']=F1ValveBasis(entrainment_capacity_m_s=value,entrainment_source_id=source)
    if basis.design_id=='case-2':
        settings.update(cooling_outlet_K=313.15,f1=F1ValveBasis(francis_E=1.02,
            entrainment_capacity_m_s=.105,entrainment_source_id=cf['case-2'][1]))
        origin='source-reported 20–40 C teaching cooling water and Francis E=1.02; remaining assumptions are proposed explicitly'
    if basis.design_id in ('case-1b','case-3'):
        settings['weir_length_diameter_ratio']=.6
    elif basis.design_id=='case-1a':
        settings['weir_length_diameter_ratio']=.65
    return EquipmentBasis(**settings),origin


def tray_efficiency(record):
    """O'Connell overall efficiency estimate; NOT Murphree stage efficiency."""
    rows=[p for p in record['outputs']['stage_profiles'] if 'liquid_properties' in p]
    if not rows:
        raise ValueError('DATA_PARAMETER_MISSING: native tray transport properties are required')
    override=record.get('sizing_efficiency_assumption')
    if override is not None:
        e=override.get('value');source=override.get('source')
        if not isinstance(e,(int,float)) or not 0<e<=1 or not source:
            raise ValueError('Explicit efficiency assumption and provenance required')
        n=record['request']['equilibrium_stages'];actual=math.ceil((n-1)/e)
        return dict(passed=True,overall_efficiency_estimate=e,actual_trays_estimate=actual,
            actual_feed_tray_estimate=min(actual,math.ceil((record['request']['feed_stage']-1)/e)+1),
            source=source,partial_reboiler_excluded_from_tray_efficiency=True,murphree_efficiency_imposed=False,
            assumption_origin='declared preliminary overall efficiency, not measured or an OConnell prediction',
            limitations=['Stage efficiency requires system-specific mass-transfer evidence; native MESH still uses equilibrium stages.'])
    factors=[]
    pair=record.get('sizing_key_pair_indices')
    if len(rows[0]['liquid_mole_fractions'])>2 and pair is None:
        raise ValueError('INPUT_UNDERDETERMINED: multicomponent efficiency requires explicit light/heavy keys')
    for p in rows:
        if pair is None:
            x,y=p['liquid_mole_fractions'][0],p['vapor_mole_fractions'][0]
            alpha=y*(1-x)/(x*(1-y))
        else:
            i,j=pair;x=p['liquid_mole_fractions'];y=p['vapor_mole_fractions']
            if i==j or min(x[i],x[j],y[i],y[j])<=0:raise ValueError('MODEL_OUT_OF_RANGE: positive distinct key fractions required')
            alpha=(y[i]/x[i])/(y[j]/x[j])
        mu=p['liquid_properties']['viscosity_Pa_s']*1000
        if alpha<=1 or mu<=0:
            raise ValueError('MODEL_OUT_OF_RANGE: OConnell requires positive viscosity and alpha > 1')
        factors.append(alpha*mu)
    # Explicit stage-log-mean averaging policy (an estimate, not a fitted law).
    factor=math.exp(sum(math.log(v) for v in factors)/len(factors))
    efficiency=.492*factor**(-.245)
    if not 0<efficiency<=1:
        raise ValueError('MODEL_OUT_OF_RANGE: unphysical overall efficiency; do not silently clip')
    req=record['request']; n=req['equilibrium_stages']
    n_actual=math.ceil((n-1)/efficiency)
    return {'passed':True,'overall_efficiency_estimate':efficiency,
        'actual_trays_estimate':n_actual,
        'actual_feed_tray_estimate':min(n_actual,math.ceil((req['feed_stage']-1)/efficiency)+1),
        'equation':'Eo = 0.492 * (alpha * mu_cP)^(-0.245); N_actual = ceil((N_equilibrium-1)/Eo)',
        'averaging_policy':'geometric mean of native tray alpha*mu; empirical estimate only',
        'mean_alpha_mu_cP':factor,'stage_factor_range':[min(factors),max(factors)],
        'partial_reboiler_excluded_from_tray_efficiency':True,
        'murphree_efficiency_imposed':False,'source':EFFICIENCY_SOURCE,
        'limitations':['Empirical preliminary estimate; no measured tray efficiency for these mixtures.',
                       'Overall efficiency must not be supplied as a Murphree stage efficiency to DWSIM.']}


def hydraulic_row(p, diameter, options, load=1.):
    l,v=p['liquid_properties'],p['vapor_properties']
    rl,rv=l['density_kg_m3'],v['density_kg_m3']
    lm=p['liquid_flow_mol_s']*l['molecular_weight_kg_kmol']/1000*load
    vm=p['vapor_flow_mol_s']*v['molecular_weight_kg_kmol']/1000*load
    if min(lm,vm,rv,l['surface_tension_N_m'])<=0 or rl<=rv:
        raise ValueError('MODEL_OUT_OF_RANGE: positive two-phase loads and density difference required')
    flv=lm/vm*math.sqrt(rv/rl)
    ts=options.tray_spacing_m
    if options.weir_height_m > .15*ts:
        raise ValueError('MODEL_OUT_OF_RANGE: Fair capacity screen requires weir height <= 15% tray spacing')
    # Source A3 uses spacing in mm. Keep the source's 0.755 exponent;
    # do not silently substitute another published fit (e.g. 0.775).
    cs=.0105+8.127e-4*(ts*1000)**.755*math.exp(-1.463*flv**.842)
    uf=cs*(l['surface_tension_N_m']*1000/20)**.2*math.sqrt((rl-rv)/rv)
    area=math.pi*diameter**2/4
    downcomer=area*options.downcomer_area_fraction
    net=area-downcomer
    active=area-2*downcomer
    holes=active*options.hole_area_fraction
    ql,qv=lm/rl,vm/rv
    un,uh=qv/net,qv/holes
    weir=options.weir_length_diameter_ratio*diameter
    crest=.75*(ql/weir)**(2/3)  # NPTEL 7.4: mm -> m
    hd=.051*(uh/options.orifice_coefficient)**2*rv/rl # NPTEL 7.8 mm -> m
    hr=.0125*1000/rl # NPTEL 7.10: 12500/rho_L mm -> m
    ht=hd+options.weir_height_m+crest+hr
    clearance_area=min(downcomer,weir*options.downcomer_clearance_m)
    hdc=.166*(ql/clearance_area)**2 # NPTEL 7.12: 166 mm -> m
    backup=ht+options.weir_height_m+crest+hdc
    residence=downcomer*ts/ql # NPTEL 7.14 downcomer volume over one tray spacing
    result = {'stage':p['stage_index_including_condenser'],'diameter_m':diameter,
        'flow_parameter_mass_basis':flv,'capacity_factor_m_s':cs,
        'flood_velocity_m_s':uf,'operating_velocity_m_s':un,'fraction_of_flood':un/uf,
        'vapor_volumetric_flow_m3_s':qv,'liquid_volumetric_flow_m3_s':ql,
        'hole_velocity_m_s':uh,'weir_crest_m':crest,'dry_head_m':hd,'residual_head_m':hr,
        'tray_pressure_drop_Pa':ht*rl*9.80665,'downcomer_backup_m':backup,
        'downcomer_residence_s':residence,
        'checks':{'flooding':un/uf<=options.max_flood_fraction,
                  'downcomer_backup':backup<.5*(ts+options.weir_height_m),
                  'downcomer_residence':residence>=3}}
    coefficient=options.weeping_coefficient
    if coefficient is not None:
        depth=(options.weir_height_m+crest)*1000
        if not coefficient.clear_liquid_depth_min_mm <= depth <= coefficient.clear_liquid_depth_max_mm:
            raise ValueError('MODEL_OUT_OF_RANGE: liquid depth outside supplied weeping K2 chart interval')
        umin=(coefficient.K2-.9*(25.4-options.hole_diameter_mm))/math.sqrt(rv)
        if umin<=0:
            raise ValueError('MODEL_OUT_OF_RANGE: supplied K2 gives a nonpositive weep-point velocity')
        minimum_hole_velocity=uh*(options.minimum_load_fraction or 1.)/load
        result['weeping']={'minimum_hole_velocity_m_s':minimum_hole_velocity,
                           'weep_point_velocity_m_s':umin,'K2_source':coefficient.source_id,
                           'clear_liquid_depth_mm':depth,'source':HYDRAULICS_SOURCE.replace('2.html','1.html')}
        result['checks']['weeping_at_declared_minimum_load']=minimum_hole_velocity>=umin
    else:
        result['weeping_status']='needs_input: source-qualified K2 versus clear liquid depth chart'
    return result


def size_column(record, options):
    if options.tray_type == 'F1_valve':
        from .f1 import size_f1_column
        return size_f1_column(record,options)
    rows=[p for p in record['outputs']['stage_profiles'] if 'liquid_properties' in p]
    efficiency=tray_efficiency(record)
    candidates=[]; accepted=None
    # Enumerate nominal diameters, then recompute every tray, not just average loads.
    for step in range(5,101):
        diameter=step/10
        results=[hydraulic_row(p,diameter,options) for p in rows]
        ok=all(all(r['checks'].values()) for r in results)
        candidates.append({'diameter_m':diameter,'passed_available_checks':ok,
            'max_flood_fraction':max(r['fraction_of_flood'] for r in results),
            'max_backup_m':max(r['downcomer_backup_m'] for r in results),
            'min_residence_s':min(r['downcomer_residence_s'] for r in results)})
        if ok:
            accepted=results;break
    if accepted is None:
        return {'passed':False,'candidates':candidates,'reason':'No diameter passed flooding/downcomer screens within 0.5..10.0 m'}
    envelope=[]
    for load in (.5,.6,.7,.8,.9,1.,1.1,1.2):
        r=[hydraulic_row(p,diameter,options,load) for p in rows]
        envelope.append({'relative_load':load,'passes_available_checks':all(all(t['checks'].values()) for t in r),
                         'max_flood_fraction':max(t['fraction_of_flood'] for t in r),
                         'max_backup_m':max(t['downcomer_backup_m'] for t in r),
                         'min_residence_s':min(t['downcomer_residence_s'] for t in r),
                         'weeping_checked':options.weeping_coefficient is not None})
    active_height=(efficiency['actual_trays_estimate']-1)*options.tray_spacing_m
    # Section/tray pressure-drop estimate; requires a new thermo qualification
    # before it may be fed back to the existing narrow-pressure model cards.
    pressure_drop=sum(r['tray_pressure_drop_Pa'] for r in accepted)/len(accepted)*efficiency['actual_trays_estimate']
    return {'passed':True,'diameter_m':diameter,**efficiency,
        'tray_type':'sieve_candidate','active_height_m':active_height,
        'estimated_total_height_m':active_height+options.top_disengagement_m+options.bottom_sump_m,
        'estimated_column_pressure_drop_kPa':pressure_drop/1000,
        'estimated_bottom_pressure_kPa':record['request']['pressure_pa']/1000+pressure_drop/1000,
        'geometry':options.model_dump(),'tray_results':accepted,'candidates':candidates,
        'load_envelope_available_checks':envelope,
        'completed_checks':['Fair flooding screen','dry/wet tray pressure-drop estimate',
                            'downcomer backup','downcomer residence','overall efficiency estimate'],
        'unresolved_checks':['sieve weeping and entrainment correlation/chart qualification',
                             'pressure-profile feedback with qualified VLE data',
                             'vendor tray performance and mechanical design'],
        'hydraulic_operating_window_fully_validated':False,
        'sources':[FAIR_SOURCE,HYDRAULICS_SOURCE,HYDRAULICS_SOURCE.replace('2.html','3.html'),EFFICIENCY_SOURCE]}


def lmtd(a,b):
    if min(a,b)<=0:
        raise ValueError('UTILITY_APPROACH: terminal temperature crossover or zero approach')
    return a if abs(a-b)<1e-10 else (a-b)/math.log(a/b)


def size_auxiliaries(record, options, utility_record):
    o=record['outputs']; rows=o['stage_profiles']
    top=next(p for p in rows if 'liquid_properties' in p)
    last=next(p for p in reversed(rows) if 'liquid_properties' in p)
    tc=o['distillate']['temperature_K']; tb=o['bottoms']['temperature_K']
    dtc=lmtd(tc-options.cooling_outlet_K,tc-options.cooling_inlet_K)
    utility=utility_record['outputs']
    dtr=utility['steam_saturation_K']-tb
    if min(tc-options.cooling_outlet_K,dtr)<options.minimum_approach_K:
        raise ValueError('UTILITY_APPROACH: insufficient cooling or heating temperature approach')
    qc,qr=o['condenser_duty_kW'],o['reboiler_duty_kW']
    cooling=qc/utility['cooling_enthalpy_rise_kJ_kg']
    steam=qr/utility['steam_latent_heat_kJ_kg']
    condenser_area=qc*1000/(options.condenser_U_W_m2_K*dtc)*options.area_margin
    reboiler_area=qr*1000/(options.reboiler_U_W_m2_K*dtr)*options.area_margin
    nozzles=[]
    for name,flow,velocity in (
        ('overhead_vapor',top['vapor_flow_mol_s']*top['vapor_properties']['molecular_weight_kg_kmol']/1000/top['vapor_properties']['density_kg_m3'],options.vapor_nozzle_velocity_m_s),
        ('reflux',record['request']['reflux_ratio']*o['distillate']['mass_flow_kg_s']/o['distillate']['liquid_properties']['density_kg_m3'],options.liquid_nozzle_velocity_m_s),
        ('distillate',o['distillate']['mass_flow_kg_s']/o['distillate']['liquid_properties']['density_kg_m3'],options.liquid_nozzle_velocity_m_s),
        ('bottoms',o['bottoms']['mass_flow_kg_s']/o['bottoms']['liquid_properties']['density_kg_m3'],options.liquid_nozzle_velocity_m_s)):
        nozzles.append({'stream':name,'flow_m3_s':flow,'velocity_limit_m_s':velocity,
                        'minimum_internal_diameter_m':math.sqrt(4*flow/(math.pi*velocity)),
                        'pipe_schedule_selected':False})
    density=o['feed']['liquid_properties']['density_kg_m3']
    q=o['feed']['mass_flow_kg_s']/density
    power=o['feed']['mass_flow_kg_s']*9.80665*options.pump_total_head_m/(options.pump_efficiency*1000)
    return {'passed':True,'condenser':{'duty_kW':qc,'LMTD_K':dtc,'area_m2':condenser_area},
        'reboiler':{'duty_kW':qr,'driving_temperature_K':dtr,'area_m2':reboiler_area},
        'utilities':{'cooling_water_kg_s':cooling,'steam_kg_s':steam},'nozzles':nozzles,
        'feed_pump':{'flow_m3_h':q*3600,'assumed_total_head_m':options.pump_total_head_m,
                     'shaft_power_kW':power,'suggested_minimum_motor_kW':power*options.motor_margin,
                     'NPSH_verified':False,'catalog_selected':False,
                     'scope':'hot-feed hydraulic estimate; not a cold-storage feed-pump selection'},
        'input_assumptions':options.model_dump(), 'utility_property_record':utility_record,
        'unresolved_checks':['exchanger multicomponent temperature profile, detailed thermal/hydraulic rating',
                             'utility properties and U require site/vendor confirmation',
                             'pump suction layout, friction calculation, NPSHa/NPSHr and catalog curves',
                             'pipe material, wall thickness, pressure drop, standards and vendor selection'],
        'scope':'assumption-based preliminary areas, utilities, nozzle bore and pump power; no vendor selection'}
