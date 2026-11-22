---
skill_id: counterevidence_recovery
version: '1.0'
title: Diagnose failed checks and select a next action
owner: expert_review
applies_to: failure
gates: [G1, G2, G4]
tools: []
checks: [failure_type, evidence_preservation, qualified_recovery_only]
hypothesis: The observed failure type identifies permitted next actions and the evidence that must be retained.
---
For an out-of-range model, request evidence for the operating range. If an azeotropic boundary refutes the target, reject the current single-column route. Reassess the model and parameters after a reference check fails. Recover from failed numerical candidates by selecting from calculated feasible candidates. Record proposed and executed repairs separately. Keep the model qualification requirements during recovery.
