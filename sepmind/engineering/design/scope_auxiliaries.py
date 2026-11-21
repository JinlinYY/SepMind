"""Fixed-H01-depth auxiliary estimates from actual accepted native streams."""
import math
from .equipment import lmtd


def preliminary_auxiliaries(native_columns,utilities,policy):
    rows=[]
    for name,native in native_columns.items():
        outputs=native['outputs'];qr=outputs['reboiler_duty_kW'];qc=outputs['condenser_duty_kW']
        ts=utilities['cooling_water']['outputs']['steam_saturation_K']
        latent=utilities['cooling_water']['outputs']['steam_latent_heat_kJ_kg']
        tb=outputs['bottoms']['temperature_K'];tc=outputs['distillate']['temperature_K']
        approach=ts-tb;reboiler=dict(duty_kW=qr,process_temperature_K=tb,steam_temperature_K=ts,
            approach_K=approach,passed=approach>=policy['minimum_approach_K'])
        if reboiler['passed']:
            reboiler.update(preliminary_area_m2=qr*1000/(policy['reboiler_U_W_m2_K']*approach)*policy['area_margin'],
                steam_kg_s=qr/latent)
        selected=None
        for key in ['cooling_water','chilled_water']:
            if tc-policy[key]['outlet_K']>=policy['minimum_approach_K']:selected=key;break
        condenser=dict(duty_kW=qc,reference_temperature_K=tc,passed=selected is not None)
        checks={}
        if selected:
            water=utilities[selected]['outputs'];temp=policy[selected]
            delta=lmtd(tc-temp['inlet_K'],tc-temp['outlet_K'])
            area=qc*1000/(policy['condenser_U_W_m2_K']*delta)*policy['area_margin']
            flow=qc/water['cooling_enthalpy_rise_kJ_kg']
            condenser.update(utility=selected,LMTD_K=delta,preliminary_area_m2=area,water_kg_s=flow)
            checks['condenser_UA']=abs(area*policy['condenser_U_W_m2_K']*delta/policy['area_margin']/1000-qc)<=1e-8*max(qc,1.)
            checks['coolant_enthalpy']=abs(flow*water['cooling_enthalpy_rise_kJ_kg']-qc)<=1e-8*max(qc,1.)
        if reboiler['passed']:
            checks['reboiler_UA']=abs(reboiler['preliminary_area_m2']*policy['reboiler_U_W_m2_K']*approach/policy['area_margin']/1000-qr)<=1e-8*max(qr,1.)
            checks['steam_enthalpy']=abs(reboiler['steam_kg_s']*latent-qr)<=1e-8*max(qr,1.)
        nozzles=[]
        for label in ['distillate','bottoms']:
            port=outputs[label];properties=port.get('liquid_properties')
            if properties:
                volume=port['mass_flow_kg_s']/properties['density_kg_m3'];velocity=1.
            else:
                volume=port['flow_mol_s']*8.314462618*port['temperature_K']/port['pressure_Pa'];velocity=20.
            diameter=math.sqrt(4*volume/(math.pi*velocity))
            nozzles.append(dict(stream=label,actual_volume_m3_s=volume,design_velocity_m_s=velocity,
                minimum_internal_diameter_m=diameter,nominal_pipe_selected=False))
        checks['nozzle_continuity']=all(abs(math.pi*n['minimum_internal_diameter_m']**2/4*n['design_velocity_m_s']-n['actual_volume_m3_s'])<1e-10 for n in nozzles)
        rows.append(dict(unit=name,reboiler=reboiler,condenser=condenser,nozzles=nozzles,checks=checks,
            passed=reboiler['passed'] and condenser['passed'] and all(checks.values())))
    return dict(passed=bool(rows) and all(row['passed'] for row in rows),units=rows,policy=policy,
        scope='Same endpoint/U/velocity assumptions as fixed H01. Preliminary utilities, area and bore estimates; no vendor, full mixture, packing, pressure-drop or economic optimization qualification.')
