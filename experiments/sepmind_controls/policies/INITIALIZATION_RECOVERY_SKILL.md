# Supplement to rigorous_counterexample_redesign

Check model admissibility, phase feasibility and the prerequisites of the numerical initialization separately. When choosing a seed, read the actual capability flags and evidence ID in the current observation. A successful VLE sample can contain equilibrium compositions without both phase enthalpies. Native enthalpy initialization requires finite liquid and vapor enthalpies throughout that sample. Native CMO initialization uses equilibrium and temperature data with a feasible constant-molar-overflow screen. The default solver initialization requires no separately sampled seed. These are starting guesses for the same rigorous column calculation.

Apply the base Skill's enthalpy-coupled initialization step only when the native enthalpy capability is available. The capability check applies regardless of the size of the minimum-reflux difference.

Record the seed requested and the seed used. Preserve the model, feed, pressure, product requirements, equilibrium stages, feed stage and reflux ratio during a seed-only change. Phase conflicts, inadmissible property models and failed physical checks require their own diagnosis. After a strict calculation, associate each review with its exact evidence ID. Inspect the latest review state before submitting or stopping.

When the strict calculation closes and the product targets still fail, examine the exact failed targets. A bounded stage-margin candidate at the same reflux can test the discrepancy between the screening design and the strict column. The existing preliminary design procedure uses an initial allowance of two equilibrium stages per section, capped by the task's stage limit. Accept a revised candidate only after an actual strict calculation and review.
