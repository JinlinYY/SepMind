---
skill_id: azeotropic_route_review
version: '1.0'
title: 共沸约束与路线审查
owner: thermodynamics
applies_to: any
gates: [G1]
tools: [assess_separation_feasibility]
checks: [target_interval, azeotropic_boundary, alternative_data_requirements]
hypothesis: 普通单塔可在已核验的目标组成区间内完成所请求的富集。
---
根据真实 VLE 求模型共沸边界，检查原料与产品所在的组成区间。不能因全物系存在共沸就否定所有目标，也不能跨过边界继续逐板。路线被反证时提出待验证的替代概念，明确溶剂、相平衡或设备数据需求。
