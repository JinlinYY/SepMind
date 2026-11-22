---
skill_id: column_tradeoff_decision
version: '1.0'
title: Reflux and equilibrium stage trade-offs
owner: process_advisor
applies_to: any
gates: [G4]
tools: [estimate_minimum_reflux, explore_reflux_candidates, select_process_design, calculate_mccabe_thiele_stages]
checks: [computed_candidates_only, stage_feasibility, numerical_counterexamples, explicit_method_assumptions]
hypothesis: Feasible calculated candidates can support a preliminary selection under the stated approximations.
---
Compute the minimum reflux ratio and compare calculated candidates. Retain nonconvergent candidates and those above the stage limit as failed evidence. Select from feasible candidates and recalculate the final stage profile. Internal vapor flow is a screening proxy. Heat duties and economic optimality require separate calculations.
