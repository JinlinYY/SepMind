---
skill_id: topology_independent_review
version: '1.0'
title: Independently verify flowsheets using raw numerical records
owner: expert_review
applies_to: any
gates: [G8]
tools: [review_topology]
checks: [frozen_requirements, phase_residual, material_energy_closure, original_product_targets]
hypothesis: Raw port outputs, phase equilibrium, and overall balances can support numerical acceptance of the candidate.
---
Read native records and verify their hashes. Independently calculate component, mass, enthalpy, and connection residuals for each unit and the process boundary.
Check original purity, recovery, variable limits, and property assumptions. Retain failed checks and document the scope.
Record the numerical acceptance scope separately from experimental property and equipment qualification.
