---
skill_id: topology_counterevidence
version: '1.0'
title: Revise flowsheet topology and parameters after failed checks
owner: process_advisor
applies_to: failure
gates: [G1, G4]
tools: [validate_topology_graph, execute_topology]
checks: [failure_evidence, frozen_requirements, connected_graph, conserved_ports, native_execution]
hypothesis: Recalculation after topology or parameter changes can recover the original product specifications while preserving hard constraints.
---
Read the original failed records and classify the issue as connections, inputs, solver behavior, or product requirements.
Adjust the column count, connections, outlet assignment, and permitted parameters within bounds. Validate the graph and recalculate the revised design.
Reuse units when the inputs and evidence match exactly. Recalculate units with changed dependencies.
