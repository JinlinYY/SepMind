---
skill_id: preliminary_equipment_review
version: '2.1'
title: Review preliminary equipment estimates and their scope
owner: process_advisor
applies_to: any
gates: [G6, G7]
tools: [estimate_column_equipment, estimate_auxiliary_equipment]
checks: [native_transport_properties, referenced_correlations, explicit_estimated_geometry, continuity, utility_approach, unresolved_checks_retained]
hypothesis: Rigorous-column loads and properties can support preliminary column and auxiliary equipment estimates under explicit assumptions.
---
Use calculated stage loads and transport properties to estimate overall tray efficiency, diameter, tray spacing, flooding, pressure drop, and downcomer and load behavior. Distinguish overall efficiency from Murphree efficiency. Use a declared U and IAPWS water and steam enthalpies for exchanger sizing and check for temperature cross. Use internal diameter for piping continuity. Calculate cold-feed pump head, power, and NPSHa from cold-stream properties using Bernoulli and Colebrook. Calculate the preheater duty from cold tank to saturated feed by balancing enthalpy, shaft work, and potential energy. Retain open checks for NPSHr, vendor curves, weeping, entrainment, pressure-drop feedback, and mechanical design.

The default preliminary F1 layout uses 39 mm holes and 34 g heavy valves. Use separate correlations for partial and full lift. Calculate chord weirs and segmental downcomers, lay out holes, and check open area. Use the source case's CF entrainment factor as a separate criterion from the Fair capacity coefficient and document any conflicting source values. Determine the operating range unless the user gives a load constraint. If flow and density vary widely, divide the internals into sections using the F0 constraint.
