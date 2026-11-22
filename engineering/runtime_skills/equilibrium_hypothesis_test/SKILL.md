---
skill_id: equilibrium_hypothesis_test
version: '1.0'
title: Phase-equilibrium hypothesis test
owner: thermodynamics
applies_to: any
gates: [G1]
tools: [calculate_binary_vle]
checks: [fugacity_closure, composition_closure, source_domain]
hypothesis: The selected model can yield a solution at the specified conditions that satisfies its phase-equilibrium equations and composition closure.
---
Run the bubble-point calculation and independently recalculate fugacity and composition residuals. Assess numerical convergence, model consistency, and experimental accuracy separately. Record the failed check and block downstream use when residual, feed-state, or validity conditions fail.
