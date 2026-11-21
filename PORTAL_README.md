# SepMind web interface

The browser interface provides the two design settings described in the paper. Run the backend and frontend in separate terminals.

In the first terminal, from the repository root:

```text
python -m pip install -r requirements-research.txt
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In the second terminal, from the repository root:

```text
cd frontend
npm ci
npm run dev
```

Open the [local portal](http://127.0.0.1:3000) and select a design setting:

- **Setting I — Prescribed flowsheet design (既定拓扑设计).** Review the given design basis and the adjustable column parameters before starting a run.
- **Setting II — Autonomous flowsheet design (自主流程设计).** Review the feed, separation requirements, and allowed units. SepMind proposes the unit connections and parameters from an empty flowsheet.

Set `DEEPSEEK_API_KEY` in the backend environment for DeepSeek. The deterministic option executes the supported numerical workflow without a model call. To enable rigorous simulator calculations on Windows, set `DWSIM_HOME` to the DWSIM 9.0.5 installation directory containing `DWSIM.Automation.dll`.

Review the stage results, validation status, and exported design records after each run. For the published case inputs, metrics, and command-line equivalents, see the [reproduction guide](reproducibility/README.md).
