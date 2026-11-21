# Expert-guided route construction

Start with the frozen feed, original targets and computed phase evidence. Select a process family before selecting stage counts. Each topology remains a hypothesis requiring actual calculation.

For selective-solvent liquid-liquid separation, compare solvent loading and stage count using the computed LLE results. A low solvent loading can leave most of the solute in the raffinate. Raising reflux downstream can be expensive when the solvent-free VLE enrichment becomes weak near a pure product.

Inspect both solute contamination and dissolved solvent in the raffinate. When the registered phase model and allowed chemicals support a wash, compare a wash contact or countercurrent wash followed by phase separation. Fresh wash water can be represented by auxiliary_feed. A makeup_mixer followed by a supported decanter is another contact hypothesis. Validate the resulting liquid phases with actual tools.

When a computed phase already meets the original product specification, compare assigning that phase directly as product against adding a column. Additional equilibrium stages can create a two-liquid condenser state even if algebraic MESH equations converge. A negative independent liquid TPD requires a phase-aware route revision or a physically verified single-phase draw; do not suppress the review. Derive distillation draws from the actual hydrocarbon inventory rather than a fixed fraction of a solvent-rich inlet.

In the solvent-rich branch, inspect co-extracted light components before assigning a high-purity solute product. Compare a light-component removal step, solvent recovery, and any physically justified recycle. If water is present, evaluate whether condensation and liquid separation are required. Check phase-specific model coverage for every operation.

For extractive distillation, compare separate solvent and hydrocarbon feeds, with solvent entering an upper interior stage and hydrocarbon entering lower. A single combined feed changes solvent availability in the rectifying section. Use actual calculated residuals to justify its performance. Recover the entrainer in a subsequent supported separation and close its material balance through explicit makeup and purge choices.

Choose pressures within source-model guards. Pressure increase requires a pump or an explicitly supported pressure-raising operation. Record thermal conditioning and fresh auxiliary enthalpy. Preserve the original hydrocarbon feed conditions.

Choose either an absolute distillate_flow_mol_s or a relative distillate_fraction for each column. Derive a first draw estimate from computed key-component inventory, and verify its recovery and impurities by an actual solve. Column draws near a product boundary should not be rounded to a coarse fraction. Keep downstream pressure at or below each inlet pressure unless an explicit liquid pump is present. An external-condenser column uses reboiled_absorber, zero reflux_ratio and an explicit reflux feed with its actual composition and enthalpy.

A third supported draw specification is distillate_inventory_components with an explicitly selected distillate_inventory_multiplier. This expresses a design draw relative to selected component inventories in the actual inlet, including the current recycle iterate. Set both distillate_fraction and distillate_flow_mol_s to null when using this rule. A solvent recovery column can compare drawing the incoming light-component inventory against drawing a fraction of the entire solvent-rich feed. A subsequent light/heavy separation should compare its light-component inventory against the desired heavy product. These are design hypotheses requiring native calculations and independent checks.

Classify failures before revision. Numerical nonconvergence calls for a registered algorithm or initialization change at the same physical design. A closed off-spec result calls for revising the responsible separation variables or route. Missing model evidence requires a qualified calculation domain or an explicit unresolved finding. Unclosed recycle guesses are provisional states. Original product targets are checked on the converged complete process.

Use the supplied evidence identifiers or the explicitly provided context aliases. Return concise public observations and actionable parameter changes matching the output schema.

The latest deterministic error is authoritative. Explicitly fix every reported offending unit before changing unrelated numerical choices. Prior expert advice remains a hypothesis and cannot override the frozen feed pressure or other hard constraints. A makeup_mixer itself supplies only the calculated shortfall to its target circulation; a separate auxiliary_feed is optional and must specify its own allowed chemical and positive amount.

The original fresh stream is defined by its supplied temperature and pressure. Use its computed native TP phase and enthalpy, including a vapor feed when the flash gives vapor. Numerical initialization records from an incompatible earlier feed state are guesses requiring recomputation. Omit optional unit parameters that are irrelevant to the selected unit kind.
