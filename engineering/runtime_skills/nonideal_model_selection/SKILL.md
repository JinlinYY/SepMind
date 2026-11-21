---
skill_id: nonideal_model_selection
version: '1.0'
title: 非理想物系模型选择
owner: thermodynamics
applies_to: nonideal
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, pair_coverage, operating_domain]
hypothesis: 有来源的非理想液相模型可以作为待验证假设，理想液相模型不足以承担本任务。
---
先识别组分、相态和压力，逐项查看模型卡的组分覆盖、参数来源和范围。记录被排除的候选及原因。只有合格候选才能进入数值检验；此时的结论是“允许检验”，不是物性已经正确。
