"""Teaching feed conditioning, Bernoulli/Colebrook duty and NPSH/curve checks."""
import math
from scipy.optimize import brentq
import numpy as np

G=9.80665
SOURCE='https://www.energy.gov/sites/prod/files/2014/05/f16/pump.pdf'


def pipe_loss(mass_flow,density,viscosity,diameter,length,roughness,minor_K):
    if min(mass_flow,density,viscosity,diameter)<=0 or min(length,roughness,minor_K)<0:
        raise ValueError('MODEL_OUT_OF_RANGE: invalid pipe flow/geometry/properties')
    if roughness>=diameter:
        raise ValueError('MODEL_OUT_OF_RANGE: roughness exceeds pipe bore')
    velocity=mass_flow/density/(math.pi*diameter**2/4)
    reynolds=density*velocity*diameter/viscosity
    if reynolds<2000:
        friction=64/reynolds;regime='laminar'
    elif reynolds<4000:
        raise ValueError('REQUIRES_REVIEW: transition flow has no qualified friction model in this teaching slice')
    else:
        friction=brentq(lambda f:1/math.sqrt(f)+2*math.log10(roughness/(3.7*diameter)+2.51/(reynolds*math.sqrt(f))),.002,.2)
        regime='turbulent_Colebrook'
    pressure=(friction*length/diameter+minor_K)*density*velocity**2/2
    return {'inner_diameter_m':diameter,'length_m':length,'velocity_m_s':velocity,
            'Re':reynolds,'Darcy_friction_factor':friction,'regime':regime,
            'pressure_drop_Pa':pressure,'head_m_of_local_liquid':pressure/(density*G),
            'roughness_m':roughness,'minor_K':minor_K}


def select_curve(flow_m3_h,required_head,npsha,density,options):
    candidates=[]
    for curve in options.curves:
        row={'model':curve.model,'source_id':curve.source_id}
        if not curve.flow_m3_h[0]<=flow_m3_h<=curve.flow_m3_h[-1]:
            row.update(status='rejected',reason='required flow lies outside the provided curve; no extrapolation')
        else:
            head=float(np.interp(flow_m3_h,curve.flow_m3_h,curve.head_m))
            eta=float(np.interp(flow_m3_h,curve.flow_m3_h,curve.efficiency)) if curve.efficiency else options.efficiency
            npshr=float(np.interp(flow_m3_h,curve.flow_m3_h,curve.npsh_required_m)) if curve.npsh_required_m else None
            power=density*G*flow_m3_h/3600*head/eta/1000
            reasons=[]
            if head<required_head:reasons.append('insufficient head at required flow')
            if npshr is None:reasons.append('NPSHr curve missing')
            elif npsha<npshr+options.npsh_margin_m:reasons.append('NPSH margin failed')
            if curve.motor_power_kW is not None and curve.motor_power_kW<power*options.motor_margin:
                reasons.append('motor margin failed')
            row.update(status='rejected' if reasons else 'hydraulic_candidate',head_m=head,
                       shaft_power_kW=power,npsh_required_m=npshr,reasons=reasons,
                       control_valve_excess_head_m=max(0.,head-required_head),
                       scope='hydraulic curve match with throttling; chemical/material/vendor suitability remains unverified')
        candidates.append(row)
    viable=[r for r in candidates if r['status']=='hydraulic_candidate']
    return {'candidates':candidates,'selected_hydraulic_candidate':min(viable,key=lambda r:r['shaft_power_kW']) if viable else None,
            'chemical_suitability_verified':False,'vendor_selection_verified':False}


def feed_conditioning(native,column,cold_record,options):
    cold=cold_record['outputs'];feed=native['outputs']['feed'];mass=feed['mass_flow_kg_s']
    hot=feed['liquid_properties'];pc=options.pump
    rc,mu=cold['density_kg_m3'],cold['viscosity_Pa_s']
    q=mass/rc;qh=mass/hot['density_kg_m3']
    ds=pc.suction_inner_diameter_m or math.sqrt(4*q/(math.pi*pc.suction_velocity_limit_m_s))
    dd=pc.discharge_inner_diameter_m or math.sqrt(4*q/(math.pi*pc.discharge_velocity_limit_m_s))
    dh=pc.hot_feed_inner_diameter_m or math.sqrt(4*qh/(math.pi*pc.discharge_velocity_limit_m_s))
    # Actual tray number is an empirical estimate, not a Murphree conversion.
    elevation=(column['actual_trays_estimate']-column['actual_feed_tray_estimate'])*options.tray_spacing_m+options.bottom_sump_m
    suction=pipe_loss(mass,rc,mu,ds,pc.suction_length_m,pc.roughness_m,pc.suction_minor_K)
    discharge=pipe_loss(mass,rc,mu,dd,pc.discharge_cold_length_m,pc.roughness_m,pc.discharge_minor_K)
    riser=pipe_loss(mass,hot['density_kg_m3'],hot['viscosity_Pa_s'],dh,elevation+pc.heated_riser_extra_length_m,pc.roughness_m,pc.hot_riser_minor_K)
    request=native['request'];pb=request.get('bottom_pressure_pa') or request['pressure_pa']
    nozzle_pressure=request['pressure_pa']+(pb-request['pressure_pa'])*request['feed_stage']/request['equilibrium_stages']
    contributions={'destination_minus_storage_pressure_Pa':nozzle_pressure-pc.storage_pressure_Pa,
        'hot_riser_static_Pa':hot['density_kg_m3']*G*elevation,
        'storage_static_credit_Pa':-rc*G*pc.storage_liquid_level_above_pump_m,
        'suction_friction_Pa':suction['pressure_drop_Pa'],'cold_discharge_friction_Pa':discharge['pressure_drop_Pa'],
        'hot_riser_friction_Pa':riser['pressure_drop_Pa'],'heater_pressure_drop_Pa':pc.heater_pressure_drop_Pa,
        'feed_nozzle_kinetic_Pa':hot['density_kg_m3']*riser['velocity_m_s']**2/2}
    pressure=sum(contributions.values());head=max(0.,pressure/(rc*G))
    shaft=mass*G*head/(pc.efficiency*1000)
    npsha=(pc.storage_pressure_Pa-cold['bubble_pressure_Pa'])/(rc*G)+pc.storage_liquid_level_above_pump_m-suction['head_m_of_local_liquid']
    npshcheck=(npsha>=pc.npsh_required_m+pc.npsh_margin_m) if pc.npsh_required_m is not None else None
    sensible=mass*(feed['specific_enthalpy_kJ_kg']-cold['specific_enthalpy_kJ_kg'])
    # Open-system energy balance under the explicitly adiabatic line/pump model.
    potential=mass*G*(elevation-pc.storage_liquid_level_above_pump_m)/1000
    kinetic=mass*riser['velocity_m_s']**2/2000  # Quiescent storage free surface is inlet boundary.
    heater=sensible+potential+kinetic-shaft
    residual=mass*cold['specific_enthalpy_kJ_kg']+shaft+heater+mass*G*pc.storage_liquid_level_above_pump_m/1000-(mass*feed['specific_enthalpy_kJ_kg']+mass*G*elevation/1000+mass*riser['velocity_m_s']**2/2000)
    selection=select_curve(q*3600,head,npsha,rc,pc)
    passed=pressure>0 and heater>=0 and npsha>0 and npshcheck is not False and abs(residual)<1e-7
    return {'passed':passed,'flow_m3_h':q*3600,'shaft_power_kW':shaft,'required_head_m':head,
            'suggested_minimum_motor_kW':shaft*pc.motor_margin,
            'NPSH_available_m':npsha,'NPSH_required_m':pc.npsh_required_m,
            'NPSH_verified':npshcheck is True,'NPSH_status':'required curve/input missing' if npshcheck is None else 'passed' if npshcheck else 'failed',
            'feed_nozzle_elevation_estimate_m':elevation,'pressure_contributions':contributions,
            'suction_pipe':suction,'cold_discharge_pipe':discharge,'heated_riser_pipe':riser,
            'feed_heater':{'duty_kW':heater,'sensible_enthalpy_rise_kW':sensible,
                           'energy_residual_kW':residual,'inlet_temperature_K':cold['temperature_K'],
                           'target_temperature_K':feed['temperature_K'],
                           'assumptions':['adiabatic pump/lines; shaft work enters fluid','estimated nozzle elevation; kinetic and potential terms included']},
            'cold_property_record':cold_record,'curve_selection':selection,'catalog_selected':False,
            'input_assumptions':pc.model_dump(),'source':SOURCE,
            'scope':'cold storage -> pump -> heater -> heated riser -> saturated column feed; conditional teaching design',
            'limitations':['Cold-state property adequacy needs separate validation from the column VLE.',
                           'Pipe bores, roughness, lengths, K factors and heater pressure loss are explicit teaching assumptions.',
                           'No manufacturer/material/chemical-compatibility selection without verified curves/data.']}
