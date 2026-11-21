---
skill_id: ideal_model_review
version: '1.1'
title: 理想性假设审查
owner: thermodynamics
applies_to: ideal
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, explicit_ideality, pair_coverage]
hypothesis: 已支持物系在明确理想性假设下，或苯／甲苯通过测量筛查且明确接受有限研究外推时，可以进入理想相平衡数值检验。
---
检查理想性是否明确给定，不能把缺少二元参数当作理想性的证据。区分纯物性关联式的有效性与混合物理想性是否得到实验支持。不满足条件时请求证据，不能自动退化为 Raoult。

苯／甲苯研究适配例外必须同时满足 CAS 白名单、106.325±0.025 kPa 项目压力守卫、research_scope_low_pressure_vle 标记和独立测量 P-x-T 筛查。其测量温度仅覆盖 333.15/353.15 K；塔底温度区域属于明确外推，不能声称整个塔的物性已由实验验证。
