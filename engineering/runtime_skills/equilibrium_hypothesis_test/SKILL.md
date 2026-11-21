---
skill_id: equilibrium_hypothesis_test
version: '1.0'
title: 相平衡假设检验
owner: thermodynamics
applies_to: any
gates: [G1]
tools: [calculate_binary_vle]
checks: [fugacity_closure, composition_closure, source_domain]
hypothesis: 当前模型在给定工况下能求得满足自身相平衡方程和组成闭合的解。
---
执行真实泡点计算，独立复算逸度与组成残差。区分数值收敛、模型自洽与实验准确性；三者不能相互替代。若残差、热状态或范围不成立，记录反证并禁止使用该结果继续设计。
