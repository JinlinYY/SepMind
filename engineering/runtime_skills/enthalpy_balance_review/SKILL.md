---
skill_id: enthalpy_balance_review
version: '1.0'
title: 焓基能量衡算与负荷校核
owner: process_advisor
applies_to: any
gates: [G5]
tools: [calculate_energy_balance]
checks: [native_stream_enthalpies, duty_sign_conventions, independent_energy_closure, no_fabricated_latent_heat]
hypothesis: 同一物性方法计算的真实流股焓与塔负荷应满足整体能量守恒。
---
读取通过产品目标检查的严格塔流股，采用kg/s和kJ/kg计算焓流kW。以冷凝移热和再沸供热均为正数，独立复算FhF+QR=DhD+BhB+QC，记录残差及无散热假设。不得把热负荷等同于换热器面积或设备选型完成。
