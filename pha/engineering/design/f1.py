"""F1 heavy-valve teaching design from native phase loads and sourced fits.

This is process/hydraulic preliminary sizing, not a manufacturer performance
guarantee. CF, when supplied, remains a separately identified chart parameter;
the Fair capacity factor is never substituted for that different coefficient.
"""
import math
from scipy.optimize import brentq

F1_SOURCE='https://qikan.lpec.sinopec.com/lyjsygc50/attached/file/20210623/20210623103937_474.pdf'
G=9.80665


def dry_head(hole_velocity,liquid_density,vapor_density):
    if min(liquid_density,vapor_density)<=0 or hole_velocity<0:
        raise ValueError('MODEL_OUT_OF_RANGE: invalid F1 dry-head inputs')
    critical=(19.9*2*G/(5.34*vapor_density))**(1/1.825)
    opened=hole_velocity>=critical
    head=(5.34*hole_velocity**2*vapor_density/(2*G*liquid_density) if opened
          else 19.9*hole_velocity**.175/liquid_density)
    return head,critical,'fully_open' if opened else 'partly_open'


def geometry(diameter,options):
    radius=diameter/2
    theta=math.asin(options.weir_length_diameter_ratio)
    width=radius*(1-math.cos(theta))
    dc=radius**2*(theta-math.sin(theta)*math.cos(theta))
    area=math.pi*radius**2
    return {'diameter_m':diameter,'area_m2':area,'downcomer_area_m2':dc,
            'downcomer_width_m':width,'net_area_m2':area-dc,
            'bubbling_area_m2':area-2*dc,'liquid_path_length_m':diameter-2*width,
            'weir_length_m':diameter*options.weir_length_diameter_ratio}


def valve_layout(g,options,pitch):
    f=options.f1
    # Hole edges remain outside the wall/disengagement exclusion zones.
    usable_radius=g['diameter_m']/2-f.edge_clearance_m-f.hole_diameter_m/2
    half_width=g['diameter_m']/2-g['downcomer_width_m']-f.disengagement_strip_m-f.hole_diameter_m/2
    row_pitch=pitch*math.sqrt(3)/2
    if min(usable_radius,half_width)<=0:return None
    points=[]
    for iy in range(-math.ceil(usable_radius/row_pitch),math.ceil(usable_radius/row_pitch)+1):
        y=iy*row_pitch
        for ix in range(-math.ceil(usable_radius/pitch)-1,math.ceil(usable_radius/pitch)+2):
            x=(ix+.5*(iy%2))*pitch
            if abs(x)<=half_width and x*x+y*y<=usable_radius**2:
                points.append([x,y])
    count=len(points)
    if count==0:return None
    holes=count*math.pi*f.hole_diameter_m**2/4
    return {'valve_count':count,'hole_area_m2':holes,'opening_fraction_total_area':holes/g['area_m2'],
            'pitch_m':pitch,'row_pitch_m':row_pitch,'hole_diameter_m':f.hole_diameter_m,
            'valve_mass_g':f.valve_mass_g,'centers_m':points,
            'layout':'staggered triangular lattice, explicitly clipped to the usable tray region',
            'geometry':g}


def rate_tray(p,g,layout,options,load=1.):
    f=options.f1;l=p['liquid_properties'];v=p['vapor_properties']
    rl,rv=l['density_kg_m3'],v['density_kg_m3']
    ql=p['liquid_flow_mol_s']*l['molecular_weight_kg_kmol']/1000/rl*load
    qv=p['vapor_flow_mol_s']*v['molecular_weight_kg_kmol']/1000/rv*load
    if min(ql,qv,rv,l['surface_tension_N_m'])<=0 or rl<=rv:
        raise ValueError('MODEL_OUT_OF_RANGE: F1 requires positive two-phase flows and liquid/vapor density difference')
    flv=ql/qv*math.sqrt(rl/rv)
    cs=.0105+8.127e-4*(options.tray_spacing_m*1000)**.755*math.exp(-1.463*flv**.842)
    uf=cs*(l['surface_tension_N_m']*1000/20)**.2*math.sqrt((rl-rv)/rv)
    uh=qv/layout['hole_area_m2'];factor=uh*math.sqrt(rv)
    crest=.00284*f.francis_E*(3600*ql/g['weir_length_m'])**(2/3)
    clear=options.weir_height_m+crest
    hc,critical,opening=dry_head(uh,rl,rv)
    he=f.aeration_factor*clear
    hp=hc+he # F1 capillary head is explicitly neglected in this teaching model.
    exit_area=min(g['downcomer_area_m2'],g['weir_length_m']*options.downcomer_clearance_m)
    hd=.153*(ql/exit_area)**2
    backup=hp+hd+clear
    residence=g['downcomer_area_m2']*options.tray_spacing_m/ql
    checks={'flooding':qv/g['net_area_m2']/uf<=options.max_flood_fraction,
            'minimum_valve_hole_factor':factor>=f.minimum_hole_factor,
            'minimum_weir_crest':crest>=f.minimum_weir_crest_m,
            'downcomer_backup':backup<.5*(options.tray_spacing_m+options.weir_height_m),
            'downcomer_residence':residence>=f.minimum_downcomer_residence_s}
    result={'stage':p['stage_index_including_condenser'],'diameter_m':g['diameter_m'],
            'liquid_volumetric_flow_m3_s':ql,'vapor_volumetric_flow_m3_s':qv,
            'flow_parameter_mass_basis':flv,'capacity_factor_m_s':cs,'flood_velocity_m_s':uf,
            'operating_velocity_m_s':qv/g['net_area_m2'],'fraction_of_flood':qv/g['net_area_m2']/uf,
            'hole_velocity_m_s':uh,'hole_factor':factor,'critical_hole_velocity_m_s':critical,
            'valve_opening_regime':opening,'weir_crest_m':crest,'dry_head_m':hc,
            'aerated_liquid_head_m':he,'tray_pressure_drop_Pa':hp*rl*G,
            'downcomer_exit_head_m':hd,'downcomer_backup_m':backup,
            'downcomer_residence_s':residence,'valve_count':layout['valve_count'],'checks':checks}
    if f.entrainment_capacity_m_s is not None:
        # The empirical 1.36 coefficient has units m^-1 under this SI convention.
        index=(qv*math.sqrt(rv/(rl-rv))+1.36*ql*g['liquid_path_length_m'])/(f.property_factor*f.entrainment_capacity_m_s*g['bubbling_area_m2'])
        second=qv*math.sqrt(rv/(rl-rv))/(.78*f.property_factor*f.entrainment_capacity_m_s*g['area_m2'])
        result['entrainment_indices']={'crossflow':index,'total_area':second}
        result['entrainment_index']=max(index,second)
        result['entrainment_CF_source_id']=f.entrainment_source_id
        checks['entrainment_chart_criterion']=max(index,second)<=min(f.entrainment_max_index,.7 if g['diameter_m']<.9 else .8)
    else:
        result['entrainment_status']='CF chart not supplied; Fair flooding and F0 are screens, not an entrainment-rate validation'
    return result


def load_window(p,g,layout,options):
    f=options.f1;r=rate_tray(p,g,layout,options)
    lower=max(f.minimum_hole_factor/r['hole_factor'],(f.minimum_weir_crest_m/r['weir_crest_m'])**1.5)
    upper=min(3.,options.max_flood_fraction/r['fraction_of_flood'],
              r['downcomer_residence_s']/f.minimum_downcomer_residence_s)
    permitted=.5*(options.tray_spacing_m+options.weir_height_m)
    if rate_tray(p,g,layout,options,upper)['downcomer_backup_m']>=permitted:
        upper=brentq(lambda scale:rate_tray(p,g,layout,options,scale)['downcomer_backup_m']-permitted,1e-6,upper)
    if 'entrainment_index' in r:
        upper=min(upper,min(f.entrainment_max_index,.7 if g['diameter_m']<.9 else .8)/r['entrainment_index'])
    return lower,upper


def performance_chart(p,g,layout,options):
    f=options.f1;r=rate_tray(p,g,layout,options);l=p['liquid_properties'];v=p['vapor_properties']
    rl,rv=l['density_kg_m3'],v['density_kg_m3']
    liquid_max=g['downcomer_area_m2']*options.tray_spacing_m/f.minimum_downcomer_residence_s
    liquid_min=(f.minimum_weir_crest_m/(.00284*f.francis_E))**1.5*g['weir_length_m']/3600
    vapor_min=f.minimum_hole_factor*layout['hole_area_m2']/math.sqrt(rv)
    points=[]
    for j in range(1,32):
        ql=liquid_max*j/31
        # Fair gas capacity at this liquid load, not a substituted F1 CF value.
        def fair_limit(qv):
            flv=ql/qv*math.sqrt(rl/rv)
            cs=.0105+8.127e-4*(options.tray_spacing_m*1000)**.755*math.exp(-1.463*flv**.842)
            uf=cs*(l['surface_tension_N_m']*1000/20)**.2*math.sqrt((rl-rv)/rv)
            return qv/g['net_area_m2']-options.max_flood_fraction*uf
        vmax=brentq(fair_limit,1e-10,max(100.,r['vapor_volumetric_flow_m3_s']*100))
        crest=.00284*f.francis_E*(3600*ql/g['weir_length_m'])**(2/3)
        clear=options.weir_height_m+crest
        hd=.153*(ql/min(g['downcomer_area_m2'],g['weir_length_m']*options.downcomer_clearance_m))**2
        available=.5*(options.tray_spacing_m+options.weir_height_m)-hd-(1+f.aeration_factor)*clear
        _,critical,_=dry_head(1.,rl,rv)
        hc_critical=dry_head(critical,rl,rv)[0]
        if available<=0:backup_v=0.
        elif available<hc_critical:backup_v=(available*rl/19.9)**(1/.175)*layout['hole_area_m2']
        else:backup_v=math.sqrt(available*2*G*rl/(5.34*rv))*layout['hole_area_m2']
        point={'liquid_flow_m3_s':ql,'fair_capacity_vapor_max_m3_s':vmax,
               'downcomer_backup_vapor_max_m3_s':backup_v,'minimum_vapor_m3_s':vapor_min}
        if f.entrainment_capacity_m_s is not None:
            limit=min(f.entrainment_max_index,.7 if g['diameter_m']<.9 else .8)
            cross=max(0.,(limit*f.property_factor*f.entrainment_capacity_m_s*g['bubbling_area_m2']-1.36*ql*g['liquid_path_length_m'])*math.sqrt((rl-rv)/rv))
            total=limit*.78*f.property_factor*f.entrainment_capacity_m_s*g['area_m2']*math.sqrt((rl-rv)/rv)
            point['entrainment_vapor_max_m3_s']=min(cross,total)
        points.append(point)
    return {'representative_equilibrium_stage':p['stage_index_including_condenser'],
            'operating_point':{'liquid_flow_m3_s':r['liquid_volumetric_flow_m3_s'],'vapor_flow_m3_s':r['vapor_volumetric_flow_m3_s']},
            'liquid_min_m3_s':liquid_min,'liquid_max_m3_s':liquid_max,'points':points,
            'scope':'fixed representative phase properties; preliminary load-performance slice, not a dynamic operating guarantee'}


def size_f1_column(record,options,maximum_diameter_m=6.):
    if not 0.5<=maximum_diameter_m<=15.:raise ValueError('Explicit preliminary diameter search bound must remain within0.5..15 m')
    from .equipment import tray_efficiency, FAIR_SOURCE
    efficiency=tray_efficiency(record)
    rows=[p for p in record['outputs']['stage_profiles'] if 'liquid_properties' in p]
    feed=record['request']['feed_stage'];f=options.f1
    initial_sections={name:[p for p in rows if (p['stage_index_including_condenser']<feed)==(name=='rectifying')]
                      for name in ('rectifying','stripping')}
    sections={}
    # A single valve count cannot satisfy both F0 limits when qV*sqrt(rhoV)
    # varies too much. Refine the internal zoning using that physical criterion.
    minimum_design=max(f.minimum_design_hole_factor,
                       f.minimum_hole_factor/options.minimum_load_fraction if options.minimum_load_fraction else 0.)
    allowed_span=f.maximum_hole_factor/minimum_design*.95
    if allowed_span<=1:
        raise ValueError('INPUT_UNDERDETERMINED: requested F1 minimum-load range conflicts with nominal hole-factor limits')
    def load_factor(p):
        v=p['vapor_properties']
        return p['vapor_flow_mol_s']*v['molecular_weight_kg_kmol']/1000/math.sqrt(v['density_kg_m3'])
    for name,group in initial_sections.items():
        zones=[];current=[]
        for p in group:
            factors=[load_factor(t) for t in current+[p]]
            if current and max(factors)/min(factors)>allowed_span:
                zones.append(current);current=[]
            current.append(p)
        if current:zones.append(current)
        for i,zone in enumerate(zones):sections[name if len(zones)==1 else f'{name}_{i+1}']=zone
    attempts=[];selected=None
    for step in range(5,round(maximum_diameter_m*10)+1):
        diameter=step/10;g=geometry(diameter,options);layouts={};results=[];windows=[]
        for name,group in sections.items():
            if not group:continue
            found=None
            for j in range(31):
                pitch=f.minimum_pitch_m+(f.maximum_pitch_m-f.minimum_pitch_m)*j/30
                layout=valve_layout(g,options,pitch)
                if not layout or not .04<=layout['opening_fraction_total_area']<=.15:continue
                ratings=[rate_tray(p,g,layout,options) for p in group]
                minimum=[rate_tray(p,g,layout,options,options.minimum_load_fraction) for p in group] if options.minimum_load_fraction else []
                if all(all(r['checks'].values()) and minimum_design<=r['hole_factor']<=f.maximum_hole_factor for r in ratings) and all(all(r['checks'].values()) for r in minimum):
                    found=(layout,ratings);break
            if found is None:break
            layouts[name]=found[0];results+=found[1]
            windows += [load_window(p,g,found[0],options) for p in group]
        ok=len(layouts)==sum(bool(group) for group in sections.values())
        attempts.append({'diameter_m':diameter,'passed_available_checks':ok,
                         'sections_with_feasible_layout':list(layouts)})
        if ok:
            selected=(g,layouts,results,windows);break
    if selected is None:
        return {'passed':False,'candidates':attempts,
                'reason':f'No F1 shell/layout satisfies the declared nominal and minimum-load criteria within0.5..{maximum_diameter_m}m; revise explicit geometry/load assumptions.'}
    g,layouts,results,windows=selected
    lower=max(w[0] for w in windows);upper=min(w[1] for w in windows)
    charts={}
    for name,group in sections.items():
        if group:
            worst=max(group,key=lambda p:rate_tray(p,g,layouts[name],options)['fraction_of_flood'])
            charts[name]=performance_chart(worst,g,layouts[name],options)
    height=(efficiency['actual_trays_estimate']-1)*options.tray_spacing_m
    pressure=sum(r['tray_pressure_drop_Pa'] for r in results)/len(results)*efficiency['actual_trays_estimate']/1000
    unresolved=['pressure-profile feedback requires additional qualified VLE domains',
                '34 g F1 fit, aeration and minimum-hole-factor criteria require vendor/experimental confirmation',
                'mechanical/support details and manufacturer performance are not selected']
    if f.entrainment_capacity_m_s is None:unresolved.insert(0,'F1 entrainment CF chart parameter/source is missing; no invented CF or entrainment rate')
    else:unresolved.insert(0,'CF chart readings are source-reported teaching assumptions, not independently qualified capacity data for the revised geometry')
    return {'passed':True,**efficiency,'tray_type':'F1_valve_34g_39mm','diameter_m':g['diameter_m'],
            'active_height_m':height,'estimated_total_height_m':height+options.top_disengagement_m+options.bottom_sump_m,
            'estimated_column_pressure_drop_kPa':pressure,
            'estimated_bottom_pressure_kPa':record['request']['pressure_pa']/1000+pressure,
            'geometry':{**options.model_dump(),**g,'downcomer_fraction_origin':'exact circular-segment geometry from weir chord; independent of the sieve-only area-fraction input'},
            'valve_layouts':layouts,'tray_results':results,'candidates':attempts,
            'zoning_policy':{'criterion':'native qV*sqrt(rhoV) span versus nominal/minimum-load F0 limits',
                             'maximum_span_ratio':allowed_span,'zone_count':len(sections),
                             'stage_zones':{name:[p['stage_index_including_condenser'] for p in group] for name,group in sections.items()}},
            'load_window':{'minimum_relative_load':lower,'maximum_relative_load':upper,
                           'operating_elasticity_estimate':upper/lower,'properties_held_fixed':True,
                           'user_minimum_load_constraint':options.minimum_load_fraction,
                           'no_unstated_turndown_guarantee':True},
            'load_performance_charts':charts,
            'completed_checks':['explicit valve lattice and opening area','F1 partial/full opening and dry/wet pressure head',
                                'Fair flooding screen','minimum F0 criterion','minimum weir crest',
                                'downcomer backup and residence','load-performance boundaries'],
            'unresolved_checks':unresolved,'hydraulic_operating_window_fully_validated':False,
            'sources':[F1_SOURCE,FAIR_SOURCE],
            'assumptions':['F1 capillary pressure head neglected','teaching F0 threshold and aeration factor',
                           'uniform-pressure native phase properties; no measured weeping/entrainment-rate guarantee']}
