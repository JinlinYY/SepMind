"""Readable calculation appendix rendered exclusively from accepted artifacts."""


def calculation_appendix(state):
    verified=state.artifacts.get('verify_and_refine_column')
    if not verified or not verified.validation.get('passed'):return []
    n=verified.data['selected_simulation'];o=n['outputs']
    lines=['','## 实际物流与计算过程','','以下数值来自本次接受的 DWSIM 结果；组成按轻组分摩尔分数列出。','',
           '| 物流 | 流量 kg/s | 温度 K | 轻组分摩尔分数 | 比焓 kJ/kg |',
           '| --- | ---: | ---: | ---: | ---: |']
    for key,label in [('feed','饱和进料'),('distillate','塔顶产品'),('bottoms','塔底产品')]:
        s=o[key]
        lines.append(f"| {label} | {s['mass_flow_kg_s']:.6g} | {s['temperature_K']:.6g} | {s['mole_fractions'][0]:.8g} | {s['specific_enthalpy_kJ_kg']:.7g} |")
    lines += ['',r'能量守恒：$\dot m_Fh_F+Q_R=\dot m_Dh_D+\dot m_Bh_B+Q_C$。',
              f"本次冷凝负荷 {o['condenser_duty_kW']:.5g} kW，再沸负荷 {o['reboiler_duty_kW']:.5g} kW。"]
    c=state.artifacts.get('estimate_column_equipment')
    if c and c.validation.get('passed'):
        d=c.data
        lines += ['',r'整体板效率估计：$E_o=0.492(\alpha\mu_{L,\mathrm{cP}})^{-0.245}$；',
                  r'$N_a=\lceil(N_{eq}-1)/E_o\rceil$，扣除部分再沸器。',
                  f"代入平均物性因子 {d['mean_alpha_mu_cP']:.6g} 得效率 {d['overall_efficiency_estimate']:.5g}，实际塔板估计 {d['actual_trays_estimate']}，塔径 {d['diameter_m']:.3g} m。"]
        if d.get('valve_layouts'):
            lines += ['',r'F1 干板液柱压头：部分开启 $h_c=19.9u_0^{0.175}/\rho_L$；完全开启 $h_c=5.34u_0^2\rho_V/(2g\rho_L)$。',
                      r'阀孔面积 $A_0=n\pi d_0^2/4$，阀孔动能因子 $F_0=u_0\sqrt{\rho_V}$。干板头以 m 液柱计；关联式采用 SI 数值。']
            for name,layout in d['valve_layouts'].items():
                lines.append(f"- {name}：{layout['valve_count']} 个 39 mm / 34 g F1 重阀；阀中心距 {layout['pitch_m']*1000:.3g} mm；阀孔总面积 {layout['hole_area_m2']:.5g} m²。")
            w=d['load_window']
            lines += [f"估计塔板总压降 {d['estimated_column_pressure_drop_kPa']:.5g} kPa；固定物性下相对负荷范围 {100*w['minimum_relative_load']:.3g}%–{100*w['maximum_relative_load']:.3g}%。压降尚未反馈至严格塔。"]
    a=state.artifacts.get('estimate_auxiliary_equipment')
    if a and a.validation.get('passed'):
        d=a.data;p=d['feed_pump']
        lines += ['',r'换热面积 $A=QM_A/(U\Delta T_{lm})$；公用工程流量 $\dot m=Q/\Delta h$。U 与面积余量是显式教学假设，水/汽焓差由 IAPWS 计算。']
        if p.get('cold_property_record'):
            h=p['feed_heater']
            lines += ['',r'管路采用 Darcy–Weisbach：$\Delta P=(fL/d+\sum K)\rho u^2/2$，湍流摩擦因子由 Colebrook 方程求解。',
                      r'$P_{shaft}=\dot m gH/\eta$；$NPSH_a=(P_s-P_{bubble})/(\rho_cg)+z_s-h_{f,s}$。',
                      f"冷态泵流量 {p['flow_m3_h']:.5g} m³/h，所需扬程 {p['required_head_m']:.5g} m，轴功率 {p['shaft_power_kW']:.5g} kW，NPSHa {p['NPSH_available_m']:.5g} m。", 
                      r'预热器按整个冷储罐至进料口的开放系统能量平衡：$Q_H=\dot m(h_F-h_c)+\dot m g\Delta z+\dot m\Delta(u^2)/2-P_{shaft}$。',
                      f"预热负荷 {h['duty_kW']:.5g} kW，初步面积 {h.get('area_m2',0):.5g} m²；缺少 NPSHr/厂家曲线时不作具体型号确认。"]
    lines += ['', '公式来源、适用域与假设见各工具记录以及 [方法说明](docs/engineering/M4_IMPLEMENTATION.md)。本附录不扩大工具的适用范围。']
    return lines
