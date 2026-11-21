---
skill_id: topology_independent_review
version: '1.0'
title: 原始数值记录的独立流程验收
owner: expert_review
applies_to: any
gates: [G8]
tools: [review_topology]
checks: [frozen_requirements, phase_residual, material_energy_closure, original_product_targets]
hypothesis: 原始端口、相平衡和全流程衡算共同支持当前候选的数值验收。
---
重读原生记录及其哈希。独立计算单元和外部边界的组分、质量、焓及连接残差，
检查原始纯度、回收率、变量和物性假设。保留失败与适用范围。有限理想物系的
数值验收范围与完整物性实验及设备资格分别记录。
