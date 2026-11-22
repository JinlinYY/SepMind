---
skill_id: parameter_evidence_audit
version: '1.0'
title: Audit parameter and experimental evidence
owner: thermodynamics
applies_to: any
gates: [G2]
tools: [resolve_property_parameters]
checks: [parameter_provenance, experimental_reference, declared_limitations]
hypothesis: Parameter order, units, provenance, and independent measurements can support conditional calculations within the stated range.
---
Check CAS order, the parameter equation, units, source hashes, and the applicable range. Test against independent experimental data when available. Record unknown fitting ranges and distinguish project bounds from literature fitting ranges. Reject downstream use if the model fails reference checks.
