---
skill_id: topology_construction
version: '1.0'
title: Construct a candidate separation graph from the design basis
owner: process_advisor
applies_to: ideal
gates: [G0, G1, G4]
tools: [admit_topology_task, validate_topology_graph, execute_topology]
checks: [model_domain, frozen_requirements, connected_graph, conserved_ports, native_execution]
hypothesis: Valid unit ports can form a candidate distillation flowsheet that meets the original product requirements.
---
Build the graph from feed and product requirements and record the basis for the column count, connections, and numerical assumptions.
Assign exactly one destination per stream. Include additional waste outlets in the process balance. Before calculation, check component order, property assumptions, connections, and variable bounds.
Obtain properties and performance from the calculation tools.
