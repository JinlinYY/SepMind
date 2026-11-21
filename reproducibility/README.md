# Reproducing the SepMind study

This guide accompanies *Expert-guided agent framework for chemical separation process design*. Run the commands from the repository root. Use a new output directory for each export or replay.

## Data and numerical outputs

```text
python -m reproducibility verify
python -m reproducibility export --output reproduced/tables
python -m unittest reproducibility.test_tables
```

These commands use Python 3.11 or later and the standard library. [evidence.json](evidence.json) contains the archived numerical inputs and results used by the export, including source-file SHA-256 values and original numerical evidence identifiers. The exports use full numerical precision where available. Format for publication after export.

| Manuscript item | What the export derives | Code or records |
| --- | --- | --- |
| Fig. 1 and Tables S1–S3 | Design stages, executable expert rules, tool registration and validation | [Orchestrator](../pha/engineering/agents/orchestrator.py), [runtime Skills](../engineering/runtime_skills/), [property knowledge](../engineering/knowledge/), [tool contracts](../engineering/contracts/), [validation](../pha/engineering/validation/) |
| Fig. 2, Table 1 and Tables S4–S6 | Common-basis product checks, design basis, tower parameters, duties and preliminary sizing | [Binary table extraction](tables.py), [four source cases](../case/curated/) |
| Fig. 3 and Tables S7–S8 | Ethanol/water candidate scores, observed strict-tower attempts and the paired cooling-water calculation | The `ethanol_water_trace` record in [evidence.json](evidence.json) |
| Table 2 | Recorded Setting I metrics and the planned Setting II rows for A1–A4 | [Prescribed benchmark controller](../experiments/sepmind_controls/controller.py), [autonomous design controller](../pha/engineering/topology/binary.py) |
| Figs. 4–5, Table 3 and Tables S9–S10 | Original product constraints and reported streams for the accepted prescribed H01 and H02 flowsheets | [H01 calculation](../scripts/complete_case3_flowsheet.py), [H02 calculation](../scripts/complete_case5_flowsheet.py) and the `hybrid` records in [evidence.json](evidence.json) |
| Table S11 | Binary component and energy residuals recalculated from recorded streams, and the archived integrated closure results | [Closure calculation](tables.py) |

The figure mappings identify the supporting numerical data and process configurations. Figure layout and artwork were prepared separately. H01 and H02 reconstruct source-defined flowsheets with controlled operating revisions. Their stream tables and recorded closure results can be exported from `evidence.json`.

### Architecture comparison

The manuscript defines **Setting I as prescribed flowsheet design and Setting II as autonomous flowsheet design**. These labels are used in the `table_02_architectures.csv` export.

| Evidence | Where to find it | How to interpret it |
| --- | --- | --- |
| Prescribed flowsheet design (Setting I) | `table_02_architectures.csv` | In the architecture comparison, each configuration and budget includes ten runs on each of D01–D04 with a specified column. |
| Setting II autonomous case examples | `autonomous_flowsheet_examples.csv` | One verified SepMind graph per D01–D04 case, with the accepted design parameters and original run identifier. D03 used three archived failure records as counterevidence. The examples have different run budgets. |
| Setting II repeated architecture comparison | `table_02_architectures.csv` | Metric cells are blank. A complete matrix covers A1–A4 on D01–D04 under both revision budgets, with ten independent runs per case and configuration. |
| Prescribed flowsheet design, supplementary comparison and ablations | `architecture_and_ablation.csv` | This table reports two numerical review and revision procedures under a specified single-column topology. Each row describes the procedure in words and records the corresponding revision budget. The archived execution settings are recorded in `evidence.json`. |

The five-revision prescribed batches use a common on-spec submission rule. Comparisons across revision budgets include this difference. Failures remain in the denominator. Token means use complete usage records, with sample sizes included in the export.

## Execute numerical calculations

Install [research dependencies](../requirements-research.txt). The DWSIM replay was verified with Python 3.13 and Windows DWSIM 9.0.5. Set `DWSIM_HOME` to the DWSIM installation directory that contains `DWSIM.Automation.dll`.

```text
python -m pip install -r requirements-research.txt
python -m reproducibility replay-column --case D01 --design sepmind --output reproduced/D01-sepmind
python -m reproducibility replay-column --case D03 --design human --output reproduced/D03-human
```

Each replay saves the exact request, the native flowsheet, the returned numerical record and a comparison against the archived product mole fractions. The native result retains its own evidence identifier.

### Review the integrated process records

This optional review requires Windows DWSIM 9.0.5 and the underlying simulator records listed below. The compact repository evidence contains the quantities needed to regenerate Tables 3, S9, S10, and S11. The native review additionally uses the saved unit outputs, numerical initialization records, and recycle ledgers. Git ignores `output/`, so a fresh checkout needs these simulator records supplied separately at the paths below.

| Case | Accepted unit records and recycle ledger | Numerical initialization records |
| --- | --- | --- |
| H01 | `output/engineering/case3_warm_pressure_20261111/` | `N8_molarSF3.5.json` in `case3_molar_extraction_20261110/`, `wash_N2.json` in `case3_water_wash_20261110/`, `C1_N7.json` in `case3_native_recovery_20261110/`, and `revised_draw_balanced.json` and `seeded_decanter.json` in `case3_repair_20261110/`. All folders are under `output/engineering/`. |
| H02 | `output/engineering/case5_pressure_R7_20261111/` | `C1_N39.json` and `C2_N19.json` in `output/engineering/case5_balanced_newton_20261110/`. |

With the records available, H01 writes numerical review files in a new directory. H02 writes them alongside the saved records, so run it on a copy. If the saved native requests were moved from another computer, clear their `request.save_path` fields in the working copies to use the records for review.

```powershell
python scripts/complete_case3_flowsheet.py --review-only --resume output/engineering/case3_warm_pressure_20261111 --extraction-temperature 308.15 --c1-pressure-drop 0.6 --c2-pressure-drop 0.7 --output reproduced/H01
New-Item -ItemType Directory -Force reproduced
Copy-Item -LiteralPath output/engineering/case5_pressure_R7_20261111 -Destination reproduced/H02 -Recurse
python scripts/complete_case5_flowsheet.py --review-existing --output reproduced/H02 --c1-pressure-drop 36.3965391 --c2-pressure-drop 29.1394849
```

These commands review the accepted prescribed flowsheets at the reported process boundaries and property assumptions.

### Repeat a design or benchmark

Use the design entry point to inspect and execute the paper's two settings. Set `DEEPSEEK_API_KEY` locally before executing the autonomous controller.

```text
python -m reproducibility design --setting I --case D01 --provider deterministic --output output/setting-I-D01
python -m reproducibility design --setting II --case D01 --basis-only
python -m reproducibility design --setting II --case D01 --output output/setting-II-D01
```

The last command runs SepMind from an empty topology with no supplied prior failure records. It executes a case, using the autonomous controller's own budget. The repeated architecture comparison requires a common budget and equivalent tools across all four architectures.

The following command repeats the prescribed five-revision protocol used for Table 2 Setting I:

```text
python -m experiments.sepmind_controls.run --output output/benchmark-setting-I --phase all --max-revisions 5 --stop-at-first-target --skip-historical-audit
```

For the three-revision archived protocol, use `--max-revisions 3` and omit `--stop-at-first-target`. Fresh calls to the provider give a new sample and use the installed numerical runtime. Use the offline export for the exact archived values. The scripts and the bundled model and parameter cards specify the applicability limits.

## Human preliminary designs

| Case | Worked engineering calculations |
| --- | --- |
| D01 | [Benzene/toluene at 42 wt% benzene](../case/curated/case-1a/calculations.md) |
| D02 | [Benzene/toluene at 36 wt% benzene](../case/curated/case-1b/calculations.md) |
| D03 | [Ethanol/water at 48 wt% ethanol](../case/curated/case-2/calculations.md) |
| D04 | [Methanol/water at 40 wt% methanol](../case/curated/case-3/calculations.md) |

The English notes organize the human source calculations and identify independently reconstructed arithmetic. Use the archived common-backend outputs in Table 1 for the numerical comparison.
