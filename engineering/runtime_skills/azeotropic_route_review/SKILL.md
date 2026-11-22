---
skill_id: azeotropic_route_review
version: '1.0'
title: Azeotropic limits and route review
owner: thermodynamics
applies_to: any
gates: [G1]
tools: [assess_separation_feasibility]
checks: [target_interval, azeotropic_boundary, alternative_data_requirements]
hypothesis: A conventional single column can achieve the requested enrichment within the verified composition interval.
---
Locate model azeotropic boundaries using calculated VLE and check the composition intervals containing the feed and products. Check the specific target even when the mixture exhibits an azeotrope. Stop stage stepping at the boundary. If the route fails, propose alternatives for verification and specify the missing solvent, phase-equilibrium, or equipment data.
