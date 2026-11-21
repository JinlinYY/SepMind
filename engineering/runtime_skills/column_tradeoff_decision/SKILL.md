---
skill_id: column_tradeoff_decision
version: '1.0'
title: 回流比与级数方案权衡
owner: process_advisor
applies_to: any
gates: [G4]
tools: [estimate_minimum_reflux, explore_reflux_candidates, select_process_design, calculate_mccabe_thiele_stages]
checks: [computed_candidates_only, stage_feasibility, numerical_counterexamples, explicit_method_assumptions]
hypothesis: 在方法近似成立时，可以从通过计算的候选中选取满足目标的初步方案。
---
先求最小回流比，再比较真实计算得到的候选。保留不能收敛或超过级数约束的失败候选作为反证。只选择可行候选，复算最终逐板结果。内部汽相流量只是筛查指标，不得称为已计算热负荷或经济最优。
