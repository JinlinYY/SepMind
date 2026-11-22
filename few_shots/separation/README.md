# Few-shot examples for the shortcut workflow

The twelve notebooks illustrate how the design, simulation, and review roles clarify inputs, call tools, cite evidence, and respond to failed checks. They contain synthetic examples marked `expert_validated: false`. Their `demo_*` evidence identifiers apply only to the examples.

Each notebook has a raw JSON cell marked `metadata.separation_example: true`. The cell includes `example_id`, `role`, `phase`, `title`, `provenance`, `expert_validated`, `context`, and `response`. The response follows the schema for its role. `context.available_evidence_ids` lists the example evidence available for citation.

The [loader](../../sepmind/shortcut/utils/few_shots.py) reads the marked JSON cell and selects up to two matching examples per role and stage by default. The recorded `few_shot_context` event identifies the examples and their SHA-256 hashes. DWSIM supplies numerical results for actual tasks.

Use `--no-few-shots` on the [shortcut CLI](../../sepmind/shortcut/README.md) or set `use_few_shots: false` in the API request to disable the examples. Use `--few-shots-dir` to choose a different example directory. Record the versions of examples used in experiments and keep the evaluation set independent of the demonstrations.
