---
skill_id: rigorous_counterexample_redesign
version: '2.0'
title: 严格塔计算反证与有界修正
owner: process_advisor
applies_to: any
gates: [G4]
tools: [verify_and_refine_column]
checks: [fixed_user_constraints, native_mesh_solution, strict_product_targets, independent_closure, bounded_redesign, preserve_counterexamples]
hypothesis: CMO筛查方案须经严格塔计算检验；不达标时增加接触级并重新配置进料位置可在有界搜索内改善分离。
---
固定原料、压力和馏出量，产品组成只能是模拟输出。先计算原始方案；若纯度或回收率不达标，保留反证，调用同一后端的相平衡曲线重新求最小回流、级数和进料位置，并提供可追溯的数值初值；不得假设不同实现的同名模型预测完全一致。若回流比是Agent自主选择，可比较有界的更高回流比；若用户给定R或R/Rmin，则严格保持约束。只接受严格满足原目标且物料能量闭合的结果。数值初值不是模拟结果，改变求解器不等于改变物理方案。达到预算或级数限制仍不达标必须停止，不放宽目标。当前均压平衡级验证不代表实际塔板、水力学或压降反馈已验证。

当后端最小回流比与初筛相差超过10%时，在已验证的同一后端相平衡/焓曲线上升级为能量耦合逐级守恒射击模型，检查正内流量、逐级物料/能量/平衡残差后，只把结果作为严格塔的数值初值。该初值不得替代DWSIM实际收敛及原产品指标检查。
