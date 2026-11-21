"""Independent algebraic invariants for preliminary equipment artifacts."""
import math


def equipment_checks(native, column, auxiliary, options):
    checks={}
    if column:
        theoretical=native['request']['equilibrium_stages']-1
        efficiency=column['overall_efficiency_estimate']
        checks['tray_efficiency_count']=(0<efficiency<=1 and column['actual_trays_estimate']*efficiency>=theoretical)
        checks['height_geometry']=abs(column['active_height_m']-(column['actual_trays_estimate']-1)*options.tray_spacing_m)<1e-8
        diameter=column['diameter_m']; area=math.pi*diameter**2/4
        net=area-column['geometry']['downcomer_area_m2'] if column.get('tray_type')=='F1_valve_34g_39mm' else area*(1-options.downcomer_area_fraction)
        by_stage={p['stage_index_including_condenser']:p for p in native['outputs']['stage_profiles']}
        closure=[]
        for row in column['tray_results']:
            p=by_stage[row['stage']];v=p['vapor_properties']
            q=p['vapor_flow_mol_s']*v['molecular_weight_kg_kmol']/1000/v['density_kg_m3']
            closure.append(abs(row['operating_velocity_m_s']*net-q)/q<1e-8)
        checks['column_vapor_continuity']=all(closure)
        if column.get('tray_type')=='F1_valve_34g_39mm':
            layouts=column['valve_layouts']
            checks['valve_count_area_geometry']=all(
                layout['valve_count']==len(layout['centers_m'])
                and abs(layout['hole_area_m2']-layout['valve_count']*math.pi*options.f1.hole_diameter_m**2/4)<1e-10
                for layout in layouts.values())
            checks['valves_outside_downcomer_and_wall_exclusions']=all(
                x*x+y*y <= (column['diameter_m']/2-options.f1.edge_clearance_m-options.f1.hole_diameter_m/2)**2+1e-10
                and abs(x)<=column['diameter_m']/2-column['geometry']['downcomer_width_m']-options.f1.disengagement_strip_m-options.f1.hole_diameter_m/2+1e-10
                for layout in layouts.values() for x,y in layout['centers_m'])
    if auxiliary:
        o=native['outputs']
        checks['nozzle_continuity']=all(abs(math.pi*r['minimum_internal_diameter_m']**2/4*r['velocity_limit_m_s']
                                            -r['flow_m3_s'])/r['flow_m3_s']<1e-8 for r in auxiliary['nozzles'])
        checks['condenser_UA_duty']=abs(auxiliary['condenser']['area_m2']*options.condenser_U_W_m2_K
            *auxiliary['condenser']['LMTD_K']/options.area_margin/1000-o['condenser_duty_kW'])/o['condenser_duty_kW']<1e-8
        checks['reboiler_UA_duty']=abs(auxiliary['reboiler']['area_m2']*options.reboiler_U_W_m2_K
            *auxiliary['reboiler']['driving_temperature_K']/options.area_margin/1000-o['reboiler_duty_kW'])/o['reboiler_duty_kW']<1e-8
        power=auxiliary['feed_pump']['shaft_power_kW']
        pump=auxiliary['feed_pump']
        cold=pump.get('cold_property_record',{}).get('outputs')
        head=pump['required_head_m'] if cold else options.pump_total_head_m
        eta=options.pump.efficiency if cold else options.pump_efficiency
        expected=o['feed']['mass_flow_kg_s']*9.80665*head/eta/1000
        checks['pump_hydraulic_power']=abs(power-expected)/expected<1e-8
        if cold or 'liquid_properties' in o['feed']:
            rho=cold['density_kg_m3'] if cold else o['feed']['liquid_properties']['density_kg_m3']
            expected_volume=o['feed']['mass_flow_kg_s']/rho*3600
            checks['feed_pump_actual_feed_volume']=abs(auxiliary['feed_pump']['flow_m3_h']-expected_volume)/expected_volume<1e-8
        if cold:
            pc=options.pump;m=o['feed']['mass_flow_kg_s'];g=9.80665
            checks['pump_pressure_head']=abs(sum(pump['pressure_contributions'].values())-head*cold['density_kg_m3']*g)<1e-6
            npsha=(pc.storage_pressure_Pa-cold['bubble_pressure_Pa'])/(cold['density_kg_m3']*g)+pc.storage_liquid_level_above_pump_m-pump['suction_pipe']['head_m_of_local_liquid']
            checks['NPSHa']=npsha>0 and abs(npsha-pump['NPSH_available_m'])<1e-8
            checks['NPSH_required_margin']=pc.npsh_required_m is None or npsha>=pc.npsh_required_m+pc.npsh_margin_m
            heat=pump['feed_heater'];z=pump['feed_nozzle_elevation_estimate_m']
            residual=m*cold['specific_enthalpy_kJ_kg']+power+heat['duty_kW']+m*g*pc.storage_liquid_level_above_pump_m/1000-(m*o['feed']['specific_enthalpy_kJ_kg']+m*g*z/1000+m*pump['heated_riser_pipe']['velocity_m_s']**2/2000)
            checks['feed_conditioning_energy']=heat['duty_kW']>=0 and abs(residual)<1e-7
            if 'area_m2' in heat:
                checks['feed_heater_UA_duty']=abs(heat['area_m2']*heat['assumed_U_W_m2_K']*heat['LMTD_K']/options.area_margin/1000-heat['duty_kW'])<1e-7
                checks['feed_heater_utility_duty']=abs(auxiliary['utilities']['feed_heater_steam_kg_s']*auxiliary['utility_property_record']['outputs']['steam_latent_heat_kJ_kg']-heat['duty_kW'])<1e-7
        utility=auxiliary['utility_property_record']['outputs']
        checks['cooling_water_enthalpy_duty']=abs(auxiliary['utilities']['cooling_water_kg_s']
            *utility['cooling_enthalpy_rise_kJ_kg']-o['condenser_duty_kW'])/o['condenser_duty_kW']<1e-8
        checks['steam_enthalpy_duty']=abs(auxiliary['utilities']['steam_kg_s']
            *utility['steam_latent_heat_kJ_kg']-o['reboiler_duty_kW'])/o['reboiler_duty_kW']<1e-8
    return {'passed':bool(checks) and all(checks.values()),'checks':checks,
            'scope':'independent continuity, geometry, efficiency counting, UA, power and utility enthalpy invariants; not vendor or full hydraulic validation'}
