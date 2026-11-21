---
skill_id: counterevidence_recovery
version: '1.0'
title: 计算反证诊断与后续动作
owner: expert_review
applies_to: failure
gates: [G1, G2, G4]
tools: []
checks: [failure_type, evidence_preservation, qualified_recovery_only]
hypothesis: 可以根据实际失败类型确定允许的后续动作，同时保留失败证据。
---
模型越界时请求相应范围的证据；共沸目标被反证时拒绝当前普通单塔路线；参考检验失败时重新审查模型与参数。候选数值失败只能在已计算可行候选中修正选择。修复建议与实际已执行的修复必须分开记录，不得降级到无证据模型来获得成功状态。
