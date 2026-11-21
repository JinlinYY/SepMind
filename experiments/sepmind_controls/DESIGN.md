# SepMind architecture and mechanism benchmark

The benchmark uses D01–D04 with a prescribed single-column topology. Agents
receive the input requirements and computed screening results.

## Controller, tools, and evaluator

- `pha/engineering/agents/orchestrator.py`: retained PHA coordinator, specialists,
  stage DAG, per-step planner and snapshot persistence.
- `pha/engineering/skills/__init__.py` and `engineering/runtime_skills/*/SKILL.md`:
  actual runtime policies, applicability and numerical evidence records.
- `pha/engineering/knowledge/__init__.py`: model cards and admissibility.
- `pha/engineering/tools/registry.py`: typed stage tools, including bundled
  `verify_and_refine_column`. The bundled repair is NOT exposed to experiment
  arms: otherwise all arms would inherit the very mechanisms being removed.
- `pha/engineering/tools/atomic_recovery.py`: existing fixed-design, no-fallback
  atomic tools and initialization. Its `simulate` includes `product_checks` and
  automatic acceptance, so this experiment overrides that boundary locally to
  return raw numerical outputs. Internal review is an explicit separate module.
- `separation/tools/dwsim.py`: DWSIM child-process driver, typed requests, timeout.
- `pha/llm/backend_multimodel.py`: real DeepSeek HTTP provider and usage metadata.
- Old `evaluation/architectures.py` changes candidate-selection message graphs
  but shares production repair/review. It cannot stand in for A1–A4 here.

## Scope and isolation

Endpoint is a fixed-input binary column, not equipment or a new route. The four
original `agent_input.json` files are read directly; feed, targets, q, pressure,
assumptions and D04 reflux multiplier stay fixed. Raoult/Raoult/NRTL/NRTL are
frozen to the original cases' property methods. No experiment changes source
input files. This specifically limits B1: it tests enforcement of expert
decision procedures, NOT free model selection under changed physical models.

Common deterministic screening is computed afresh within each run using the
existing production orchestrator with no provider and `preliminary_process`.
Its actual tools/time are charged to every arm. No native column, accepted
design, human settings or accepted warm start is fetched. All arms receive the
same computed initial screen and the same complete runtime Skill/model-card
knowledge text. Only knowledge enforcement and agent/control topology vary.

A4 is a **matched-scope full-mechanism adapter**, not a byte-identical replay of
the production G0–G9 equipment run. It reuses production preparation, runtime
Skill catalogue, atomic calculations, independent product review and native
initialization. Its stage enforcement, review and failure-specific revision are
explicit. Conclusions concern this adapter, not an unqualified production rank.

## Arms

| ID | Topology | Expert constraints | Internal review | Classified revision | Dependency reuse |
|---|---|---|---|---|---|
| A1 | One ReAct agent | No mandatory expert routing | No | No | Yes |
| A2 | Planner proposes updated plan; Executor chooses/executes action | No | No | No | Yes |
| A3 | Thermodynamics → Engineering → Analysis collaboration | No | No | No | Yes |
| A4 | Stage-constrained expert coordinator | Yes | Yes | Yes | Yes |
| B1 | Same as A4 | Off; same text remains available | Yes | Yes | Yes |
| B2 | Same as A4 | Yes | Off | Yes | Yes |
| B3 | Same as A4 | Yes | Yes | Off; generic LLM retry | Yes |
| B4 | Same as A4 | Yes | Yes | Yes | Off |

All arms retain schema validation, frozen specification enforcement, source
parameter/data availability, DWSIM isolation and numeric input legality. B1
does not remove those execution-safety conditions. All arms have the same
physical actions and variable domain. Internal review is a control mechanism,
not an extra physical simulator. B2/A1/A2/A3 receive raw streams/residuals but
no runtime independent pass/fail oracle. All final submissions use the same
external evaluator, whose results are NOT fed back into the episode.

Full routing first establishes model/phase evidence. A simulation with review
enabled must be reviewed before accepting. Failure-specific routing recommends
native equilibrium/rescreen after solver failure and design changes after a
converged target miss; it never supplies an accepted answer. B3 removes that
classification/machine routing, retaining generic legal retry and the same
knowledge text. B1 removes Skill identity/applicability enforcement, not raw
knowledge. B4 actually reruns upstream screening and any acquired native VLE
before revised columns, charging every invocation and elapsed second.

## Frozen common budgets

- DeepSeek, requested `deepseek-flash`, temperature 0.2, thinking disabled,
  JSON mode, 2048 maximum output tokens per request, 60s request timeout.
- 24 actual LLM requests; 32 action attempts; 96 total registered/atomic tools
  including repeated preparation; 6 total native design calls, at most 4 strict
  columns and 2 native VLE calls; 180s per native call; 1800s per episode.
- The five-revision condition permits 8 native design calls, at most 6 strict
  columns and 2 native VLE calls. It applies the on-spec submission rule before
  further revision. Independent internal review is applied where enabled.
- Same N=3..200, feed=1..N−1, reflux_factor=1..2 relative to the common computed
  screen. Fixed user reflux/multiplier cannot change. Default/native-CMO/native-
  enthalpy profiles available to every arm with identical data preconditions.
- Counts are caps, not forced waste: actual usage is reported. Planner/expert
  messages consume the SAME 24-call cap, not a separate free budget.
- Method time includes per-run screening and internal review. External scoring
  time is separate, no unbudgeted external redesign or solver rescue.
- Two episode workers maximum, fresh process each run. Python schedule seeds
  and per-run local seeds are logged. DeepSeek's current wrapper exposes no
  provider seed: independent temperature-0.2 requests are not bitwise replay.
- Model alias is logged with actual served model; drift is flagged, not called
  a pinned weight snapshot. Provider outages are retained and stop new launch;
  unlaunched jobs remain missing, not invented failures or numerical zeros.

Pilot: 3 runs per arm/task (96). Main: 10 NEW runs per arm/task (320), only after
tests and pilot execution-integrity checks. Pilot results remain separate.
Configuration/source changes after pilot create a new immutable batch and are
recorded; failed pilots remain. Never tune based on winning an outcome.

## Evaluator and denominators

External evaluator separately recomputes raw stream products, component/energy
and mass closure, stage convention, frozen feed/pressure/model/draw and reflux
bounds; it does not import runtime `product_checks`. Positive result requires
an explicitly submitted actually executed final record and ALL original goals.
Final means selected submission, not the best historical candidate.

Verified success: successes / launched episodes (missing official jobs shown
separately). False acceptance: claimed-success externally rejected / all claimed
successes; also report unconditional count / launched episodes. Recovery:
successful runs after first actual strict-column failure / runs whose first
actual strict-column attempt failed, including solver failures. No first column
means not eligible, not automatically a failed recovery. All final records are
evaluated regardless of the agent's claim; unfinished runs are not completed.

Cost tables provide per-case n=10 main summaries, sample SD (ddof=1), successes
and mean±SD of 0/1 outcomes. n<10 is explicitly incomplete; no fabricated SD at
n<2. Overall 40 repeated runs cover 4 related tasks, not 40 distinct processes.
Failure labels: solver failure/timeout, property evidence, off-specification,
invalid decision, budget exhausted, provider/environment/worker failure.

Selective recalculation reports actual cache retention and B4 measured repeated
tools/time. Cross-arm cost differences alone do not identify causal time savings
when decisions differ. A separate paired same-decision replay (if executed)
must measure that effect; missing paired timings stay NA.

## Output contract

Each episode: input/config/seed, append-only JSONL with provider prompts and
responses, tool requests/results, every actual native launch and duration,
internal and final external review, selected final record, terminal status.
Whitelisted provider metadata only; never log API keys, auth headers or env.
Batch: source hashes, randomized schedule, failure audit, CSV/JSON Tables1/2,
three vector/raster figures and `experiment_report.md`. No winner is assumed.
