---
skill_id: model_evidence_gap
version: '1.0'
title: Identify missing property evidence
owner: thermodynamics
applies_to: unsupported
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, missing_model_evidence]
hypothesis: The registered model catalogue may lack evidence for the requested mixture.
---
Inspect the implementation and model cards. List missing parameters, correlations, and applicability ranges. Confirm model support before reporting it. Pause numerical design when no qualified model exists and specify the evidence needed.
