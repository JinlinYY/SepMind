---
skill_id: lle_model
version: '1.0'
owner: thermodynamics
gates: [G2, G1]
tools: [qualify_lle_model, screen_extraction_phase_split]
checks: [qualified_parameter_hash, measured_tieline_checks, model_domain, lower_gibbs_split, activity_equality, finite_tpd_screen]
hypothesis: A source-checked LLE model predicts two numerical liquid phases under the explicit operating assumptions.
---
Use the retained qualification, exact component order and parameter convention. Reject failed candidate models; do not reuse VLE-only parameters as validated LLE data. Report finite stability sampling and dilute-tail extrapolation. LLE qualification does not approve vapour association, VLE, enthalpy or transport. Reject homogeneous contacts as failed extraction candidates, never fabricate two phases.
