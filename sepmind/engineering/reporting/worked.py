"""Readable calculation appendix rendered exclusively from accepted artifacts."""


def calculation_appendix(state):
    verified=state.artifacts.get('verify_and_refine_column')
    if not verified or not verified.validation.get('passed'):return []
    n=verified.data['selected_simulation'];o=n['outputs']
    lines=['','## Calculated streams and worked equations','','The values come from the accepted DWSIM result. Compositions are shown as light-component mole fractions.','',
           '| Stream | Flow (kg/s) | Temperature (K) | Light-component mole fraction | Specific enthalpy (kJ/kg) |',
           '| --- | ---: | ---: | ---: | ---: |']
    for key,label in [('feed','Saturated feed'),('distillate','Distillate'),('bottoms','Bottoms')]:
        s=o[key]
        lines.append(f"| {label} | {s['mass_flow_kg_s']:.6g} | {s['temperature_K']:.6g} | {s['mole_fractions'][0]:.8g} | {s['specific_enthalpy_kJ_kg']:.7g} |")
    lines += ['',r'Energy balance $\dot m_Fh_F+Q_R=\dot m_Dh_D+\dot m_Bh_B+Q_C$.',
              f"Condenser duty {o['condenser_duty_kW']:.5g} kW and reboiler duty {o['reboiler_duty_kW']:.5g} kW."]
    c=state.artifacts.get('estimate_column_equipment')
    if c and c.validation.get('passed'):
        d=c.data
        lines += ['',r'Estimated overall tray efficiency $E_o=0.492(\alpha\mu_{L,\mathrm{cP}})^{-0.245}$. ',
                  r'$N_a=\lceil(N_{eq}-1)/E_o\rceil$, excluding the partial reboiler.',
                  f"The mean property factor of {d['mean_alpha_mu_cP']:.6g} gives an efficiency of {d['overall_efficiency_estimate']:.5g}, an estimated tray count of {d['actual_trays_estimate']}, and a diameter of {d['diameter_m']:.3g} m."]
        if d.get('valve_layouts'):
            lines += ['',r'F1 dry-tray head for partial lift $h_c=19.9u_0^{0.175}/\rho_L$ and full lift $h_c=5.34u_0^2\rho_V/(2g\rho_L)$.',
                      r'Valve hole area $A_0=n\pi d_0^2/4$ and kinetic energy factor $F_0=u_0\sqrt{\rho_V}$. Dry-tray head is in meters of liquid. The correlations use SI values.']
            for name,layout in d['valve_layouts'].items():
                lines.append(f"- {name},{layout['valve_count']} heavy F1 valves (39 mm, 34 g), pitch {layout['pitch_m']*1000:.3g} mm, total hole area {layout['hole_area_m2']:.5g} m².")
            w=d['load_window']
            lines += [f"Estimated total tray pressure drop {d['estimated_column_pressure_drop_kPa']:.5g} kPa. Relative load range at fixed properties {100*w['minimum_relative_load']:.3g}%–{100*w['maximum_relative_load']:.3g}%. Including pressure drop in the rigorous column remains an open check."]
    a=state.artifacts.get('estimate_auxiliary_equipment')
    if a and a.validation.get('passed'):
        d=a.data;p=d['feed_pump']
        lines += ['',r'Heat transfer area $A=QM_A/(U\Delta T_{lm})$ and utility flow $\dot m=Q/\Delta h$. U and the area margin are stated assumptions. IAPWS supplies the water and steam enthalpies.']
        if p.get('cold_property_record'):
            h=p['feed_heater']
            lines += ['',r'Pipe pressure loss from Darcy–Weisbach $\Delta P=(fL/d+\sum K)\rho u^2/2$. The Colebrook equation gives the turbulent friction factor.',
                      r'$P_{shaft}=\dot m gH/\eta$. $NPSH_a=(P_s-P_{bubble})/(\rho_cg)+z_s-h_{f,s}$.',
                      f"Cold feed pump flow {p['flow_m3_h']:.5g} m³/h, required head {p['required_head_m']:.5g} m, shaft power {p['shaft_power_kW']:.5g} kW, NPSHa {p['NPSH_available_m']:.5g} m.", 
                      r'Preheat duty from the open-system balance between the cold tank and feed inlet $Q_H=\dot m(h_F-h_c)+\dot m g\Delta z+\dot m\Delta(u^2)/2-P_{shaft}$.',
                      f"Preheat duty {h['duty_kW']:.5g} kW, preliminary area {h.get('area_m2',0):.5g} m². Pump selection requires NPSHr and vendor curves."]
    lines += ['', 'See each tool record for its equations, validity range, and assumptions.']
    return lines
