---
skill_id: parameter_evidence_audit
version: '1.0'
title: 参数与实验依据审查
owner: thermodynamics
applies_to: any
gates: [G2]
tools: [resolve_property_parameters]
checks: [parameter_provenance, experimental_reference, declared_limitations]
hypothesis: 参数方向、单位、来源及独立参考检验足以支持声明范围内的条件性计算。
---
检查 CAS 顺序、参数方程、单位、来源哈希和实际范围。对具有独立实验数据的模型执行参考检验。来源未公开拟合区间时保留缺口，项目保护窗不能冒充文献拟合区间；不通过参考检验的模型不得传播到设计阶段。
