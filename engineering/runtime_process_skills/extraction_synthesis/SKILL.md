---
skill_id: extraction_synthesis
version: '1.1'
owner: engineering
gates: [G4]
tools: [explore_extraction_candidates, select_extraction_candidate]
checks: [bounded_search, individual_component_cascade_closure, original_recovery_target, retain_failed_candidates, no_uncomputed_energy_claim]
hypothesis: Computed solvent-flow and contact-count alternatives expose extraction trade-offs without imposing outlet recovery in the solver.
---
Run each bounded candidate, retain off-spec solutions and numerical failures, and select only a computed target-passing option. More solvent can improve extraction but increases circulation and affects downstream regeneration. Coextracted water and solvent in raffinate are coupled downstream loads; they are not energy duties. Do not call the selected extraction section a complete hybrid process or an economic optimum.

If every candidate is independently checked but off spec, the coordinator may choose a typed revision from `workflow/process_revision.py`: increase contacts, increase solvent, or both, within `redesign_policy`. Preserve the original basis and every prior artifact. Invalidate G1/G4/G8, rerun phase screening and the cascade, independently review the new outputs, and compare against unchanged targets. Do not retry missing or unqualified property evidence by changing stages or solvent. Stop on the declared revision or LLM budget; exhaustion is not a proof of physical infeasibility.
