---
skill_id: enthalpy_balance_review
version: '1.0'
title: Enthalpy balance and duty verification
owner: process_advisor
applies_to: any
gates: [G5]
tools: [calculate_energy_balance]
checks: [native_stream_enthalpies, duty_sign_conventions, independent_energy_closure, no_fabricated_latent_heat]
hypothesis: Rigorous-column stream enthalpies and duties calculated under a common property method satisfy the overall energy balance.
---
Read rigorous-column streams that passed the product targets. Use kg/s and kJ/kg to calculate enthalpy flows in kW. Take condenser heat removal and reboiler heat input as positive, and independently evaluate FhF+QR=DhD+BhB+QC. Record residuals and the no-heat-loss assumption. Calculate equipment size separately from duties.
