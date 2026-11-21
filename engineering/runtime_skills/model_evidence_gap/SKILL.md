---
skill_id: model_evidence_gap
version: '1.0'
title: 模型证据缺口识别
owner: thermodynamics
applies_to: unsupported
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, missing_model_evidence]
hypothesis: 当前模型目录可能没有足够证据支持所请求物系，需要先确认缺口。
---
查询实际实现和模型卡，列明缺少的参数、关联式或适用范围。不得把候选模型名写成已支持能力；没有合格模型时停止数值设计并说明所需证据。
