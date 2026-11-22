---
skill_id: ideal_model_review
version: '1.1'
title: Review ideality assumptions
owner: thermodynamics
applies_to: ideal
gates: [G2]
tools: [select_thermodynamic_model]
checks: [model_eligibility, explicit_ideality, pair_coverage]
hypothesis: A supported pair may enter ideal VLE testing under explicit ideality assumptions. Benzene/toluene may enter within the research scope after independent measurement screening and explicit acceptance of extrapolation.
---
Check that ideality is explicitly declared. Missing binary parameters do not establish ideality. Distinguish pure-component correlation validity from experimental support for ideal mixture behavior. When the conditions fail, request evidence and keep Raoult's law outside the candidate set.

The research exception for benzene/toluene requires every condition to hold: allowlisted CAS identities, pressure within 106.325 ± 0.025 kPa, the research_scope_low_pressure_vle flag, and independent measured P-x-T screening. The measurements cover 333.15 and 353.15 K. Bottoms temperatures beyond that range are an explicit extrapolation.
