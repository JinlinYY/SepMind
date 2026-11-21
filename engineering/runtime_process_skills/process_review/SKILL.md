---
skill_id: process_review
version: '1.2'
owner: expert_review
gates: [G8]
tools: [review_extraction_candidates]
checks: [reload_raw_component_flows, independent_nrtl_formula, stage_and_overall_closure, frozen_feed_and_solvent, stage_interconnections_and_endpoints, reported_composition_and_recovery, missing_energy_and_recycle_retained]
hypothesis: Saved phase compositions and component flows satisfy an independent implementation of the available numerical invariants.
---
Recompute NRTL activity equality without using the executing model's activity routine. Recompute each stage and overall component closure from raw stream vectors. Verify the frozen feed/solvent, all stage connections, final endpoints, reported mass/composition/recovery and candidate grid. Selection is permitted only after this review passes. Do not confuse the internal countercurrent cascade iteration with a plant solvent-recycle solution. Missing downstream VLE, vapour association, energy, hydraulics and solvent regeneration remain explicit blockers.

For a revised experiment, check the actual `active_search` against the retained revision decision and its declared bounds. Keep the frozen source requirements unchanged. Earlier passing review artifacts cannot approve a new candidate grid; G8 must execute again. Historical rejected results remain in `artifact_history` and must not be presented as current designs.
