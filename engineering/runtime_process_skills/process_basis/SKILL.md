---
skill_id: process_basis
version: '1.0'
owner: process_advisor
gates: [G0, G3]
tools: [check_process_basis, calculate_process_feed_inventory]
checks: [explicit_component_identities, flow_and_composition_basis, pretreatment_boundary, no_source_normalization, extraction_not_overall_recovery]
hypothesis: The supplied streams define an auditable multicomponent extraction section without inventing missing inputs.
---
Resolve post-pretreatment inlet and fraction units first. Keep targets distinct from reference operating choices. Preserve unresolved downstream purity basis. A q-line, two-component limit and distillate specification are not prerequisites for an LLE contact. Convert feed units with source-tagged molecular weights only. Missing inlet flow or composition requires input, not an assumed industrial feed.
