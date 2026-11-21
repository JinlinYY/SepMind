# SepMind matched controls

Read `DESIGN.md` before interpretation. No module is imported by the production
app; no defaults, source cases, historical results or remote branches change.

```powershell
python -X utf8 -m pytest experiments/sepmind_controls/tests -q
python -X utf8 -u -m experiments.sepmind_controls.run --output outputs/NEW_IMMUTABLE_BATCH --phase all --jobs 2
```

`all` runs the 96-episode pilot before the 320-episode main batch. Existing
phase directories cannot be overwritten. A provider outage/common worker error
halts new launches; remaining jobs stay missing. Create `STOP_REQUESTED` in the
batch root to stop new dispatch while preserving active episodes and evidence.
Do not change code/config during a frozen phase.

Read-only summaries of actual partial results are available at any time:

```powershell
python -X utf8 -m experiments.sepmind_controls.analyze --output outputs/BATCH --phase pilot
python -X utf8 -m experiments.sepmind_controls.postaudit --output outputs/BATCH --phase pilot
```

After main completion, run the actual paired **upstream-only** recalculation
timing microbenchmark, separately from all autonomous success counts:

```powershell
python -X utf8 -m experiments.sepmind_controls.recalculation --output outputs/BATCH --repeats 3
python -X utf8 -m experiments.sepmind_controls.postaudit --output outputs/BATCH --phase main
```

Independent test fixtures use frozen results or controlled exceptions only for
unit tests. They never enter experimental outcomes. JSONL logs include real
prompts/replies, decisions, tools, native starts/ends and external scoring.
Provider metadata is whitelisted; secrets are loaded by the existing backend
and not copied to source, prompts, logs or reports. Seed fields are local;
DeepSeek sampling seed is unavailable in the retained provider wrapper.

Tables and figures are regenerated from `results.json`, not handwritten values.
Failed and incomplete episodes remain, missing measurements stay NA. Four
related tasks do not establish broad generalization or universal superiority.

## Evidence-aware initialization and review

The supplementary prescribed-flowsheet protocol exposes seed availability
from actual VLE records and the review state of the latest executed column.
It is shared by all experimental arms. In arms with classified revision, an unavailable
enthalpy seed can fall back once to a supported seed without changing the
column proposal. A closed off-spec result with a matching internal review can
produce a bounded stage-margin suggestion at the same reflux. The agent still
selects a design action, and the strict calculation and final independent
evaluation determine whether it passes. Other physical guards remain active.

The default protocol is the prescribed-flowsheet architecture comparison.
For the supplementary comparison, use the controller value in the archived
protocol with `--controller-policy`. Use a fresh output directory for each run.

For the five-revision sensitivity experiment, add `--max-revisions 5` and use
one fresh output directory for each policy. This permits the initial strict
column start plus five more starts, and raises the shared native cap to eight
so that two native VLE calls can still be made. The LLM, tool, time, and VLE
caps are identical to the three-revision protocol. Use the same revision cap
in the pilot and the formal phase. The default is three revisions.

`--stop-at-first-target` uses the same raw simulator convergence and product
specification checks in every arm. The controller requires submission of the
current candidate, with internal review first where enabled. Failed internal
review can reopen revision. The external evaluator still runs after the
episode, and the agent still submits its own final decision. This option
must be the same in the pilot and formal phase.

`initialization_diagnostic` is a separate local DWSIM diagnostic. It selects
all zero-strict-start A4 runs in the archived batch with the explicit missing
phase-enthalpy error. It executes their original proposals and optionally one
fixed-reflux stage-margin trial, retaining both numerical results and review
records. This command consumes no LLM requests.

```powershell
python -X utf8 -u -m experiments.sepmind_controls.initialization_diagnostic --try-reviewed-redesign --output outputs/NEW_REDESIGN_DIAGNOSTIC
```
