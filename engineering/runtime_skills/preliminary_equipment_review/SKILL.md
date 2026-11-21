---
skill_id: preliminary_equipment_review
version: '2.1'
title: 初步设备估算及适用范围审查
owner: process_advisor
applies_to: any
gates: [G6, G7]
tools: [estimate_column_equipment, estimate_auxiliary_equipment]
checks: [native_transport_properties, referenced_correlations, explicit_estimated_geometry, continuity, utility_approach, unresolved_checks_retained]
hypothesis: 严格塔的真实负荷和物性可支持带有明确假设的初步塔体及附属设备估算。
---
以真实逐级负荷和传递物性计算整体板效率估计、塔径、板间距、液泛率、压降、降液管及负荷扫描。整体效率不得当作Murphree效率。换热面积依赖明确假设的U和真实IAPWS水/汽焓差，检查温差交叉。管径按内径连续性计算。进料泵按独立冷态物性、Bernoulli与Colebrook计算扬程、功率和NPSHa；预热器按冷储罐至饱和进料的焓、轴功和位能守恒计算。泵的NPSHr、厂家曲线缺失时保留未验证；不得混用热进料密度与冷储罐工况，也不得冒充已选定具体型号。保留漏液、夹带、压降反馈、机械及厂家校核缺口，不能将完成部分筛查描述为完整水力学验证。

教学模式默认F1重阀：按39mm孔径、34g阀片的关联式区分部分/全部开启；精确计算堰弦与弓形降液管，实际排列阀孔并校核开孔率。CF是单独的原案例读图参数，不能用Fair容量系数替代；保留原文CF冲突并采用有注明来源的教学假设。若内流量/密度跨度过大，可按F0约束细分内件区域。未给定调负荷要求时应计算操作范围，不能虚构必须满足60%负荷的用户要求。
