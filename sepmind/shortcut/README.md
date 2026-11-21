# Binary shortcut screening

The shortcut workflow uses the shared DWSIM tools for binary vapor-liquid equilibrium screening and preliminary column estimates. It accepts saturated-liquid feed and estimates stage count, duties, and other shortcut quantities from a structured task. The full design workflow documented in the paper is available through [the reproduction entry point](../../reproducibility/README.md).

Run the bundled benzene/toluene task with DWSIM installed:

```text
python -m sepmind.shortcut design --mode rules --task examples/separation/binary_design_task.json
```

Use `--mode llm` with `DEEPSEEK_API_KEY` for the three-role workflow. The [few-shot examples](../../few_shots/separation/README.md) illustrate structured model outputs. The same workflow is available at `POST /separation/design` in the web API.

The `agents/` directory contains the design, simulation and review roles. `reasoning/` contains the hypothesis and evidence policies. DWSIM requests and the subprocess worker live in [the shared simulation module](../simulation/).
