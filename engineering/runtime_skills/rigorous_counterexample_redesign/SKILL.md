---
skill_id: rigorous_counterexample_redesign
version: '2.0'
title: Rigorous column counterevidence and bounded revision
owner: process_advisor
applies_to: any
gates: [G4]
tools: [verify_and_refine_column]
checks: [fixed_user_constraints, native_mesh_solution, strict_product_targets, independent_closure, bounded_redesign, preserve_counterexamples]
hypothesis: Candidates from constant molar overflow screening require rigorous verification. More contact stages and an adjusted feed location can improve a failed design within the search bounds.
---
Hold the feed, pressure, and distillate draw fixed. Obtain product compositions from simulation. Evaluate the initial candidate and retain any failed purity or recovery check. Resample equilibrium with the same backend, recompute minimum reflux, stages, and feed location, and record the initialization. When reflux is adjustable, evaluate higher values within the permitted range. Preserve supplied R and R/Rmin constraints. Accept only designs that meet the original targets and close material and energy balances. Stop at budget or stage limits. The uniform-pressure equilibrium-stage calculation leaves actual trays, hydraulics, and pressure-drop feedback open.

When backend minimum reflux differs from screening by more than 10%, use the verified equilibrium and enthalpy curves from that backend for an energy-coupled stagewise shooting calculation. Verify positive internal flows and stage material, energy, and equilibrium residuals. Use the result only to initialize the rigorous calculation and check DWSIM convergence and original product specifications independently.
