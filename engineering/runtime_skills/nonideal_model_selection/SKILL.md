---
skill_id: nonideal_model_selection
version: '1.0'
title: Select a model for a nonideal mixture
owner: thermodynamics
applies_to: nonideal
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, pair_coverage, operating_domain]
hypothesis: A nonideal liquid-phase model with traceable parameters can be tested as a candidate when an ideal liquid model lacks support.
---
Identify the components, phases, and pressure. Review each model card for component coverage, parameter provenance, and validity. Record the excluded candidates and reasons. Admit only qualified candidates to numerical testing and record their status as admitted for testing.
