# Few-shot examples for the shortcut workflow

These examples show how the design, simulation, and review roles clarify inputs, call tools, cite evidence, and respond to failed checks. Each JSON file contains a `context` supplied to the model and the corresponding expected `response`. The examples are synthetic and carry `expert_validated: false`. Their `demo_*` evidence identifiers apply only to the demonstrations.

| Role | Example |
| --- | --- |
| Design | [Clarify missing feed state](01_design_clarification.json) |
| Design | [Screen phase equilibrium first](02_design_initial_screening.json) |
| Design | [Propose a shortcut candidate after screening](03_design_shortcut_initialization.json) |
| Design | [Revise within bounds after exceeding the stage limit](04_design_revision.json) |
| Design | [Refine the grid around a possible boundary](05_design_refinement.json) |
| Simulation | [Call the registered equilibrium tool](06_simulation_vle_execution.json) |
| Simulation | [Execute the DWSIM shortcut column](07_simulation_shortcut_execution.json) |
| Review | [Review the conditional scope of equilibrium screening](08_review_vle_review.json) |
| Review | [Request revision when the stage limit is exceeded](09_review_stage_review.json) |
| Review | [Retain open checks at preliminary acceptance](10_review_preliminary_review.json) |
| Review | [Distinguish solver failure from physical infeasibility](11_review_solver_failure.json) |
| Review | [Stop recommending candidates that exceed load limits](12_review_constraint_review.json) |

The [loader](../../sepmind/shortcut/utils/few_shots.py) validates each response against its role schema and selects up to two matching examples per role and stage by default. The `few_shot_context` event records the selected files and their SHA-256 hashes. Numerical results for actual tasks come from the calculation tools.

Use `--no-few-shots` on the [shortcut CLI](../../sepmind/shortcut/README.md) or set `use_few_shots: false` in the API request to disable the examples. Use `--few-shots-dir` to choose a different directory. Existing example notebooks with a marked JSON cell can also be loaded through this option.
