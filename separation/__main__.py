"""Run: python -m separation doctor | python -m separation screen --output FILE"""

import argparse
import json
from pathlib import Path
import sys

from .tools import BinaryVLERequest, DwsimBackend, review_binary_vle
from .utils.data_schemas import DesignTask, RunLimits
from .agents import SeparationOrchestrator
from .utils.reporting import render_report, report_data


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="DWSIM tools and three-agent separation preliminary design")
    parser.add_argument("action", choices=["doctor", "screen", "design"])
    parser.add_argument("--dwsim-home")
    parser.add_argument("--request", type=Path, help="Binary VLE request JSON; required for screen")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--task", type=Path, help="Structured DesignTask JSON for design")
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    parser.add_argument("--strategy", choices=["baseline", "hypothesis"], default="baseline",
                        help="Use hypothesis for explicit, cost-aware verification; baseline preserves the original loop")
    parser.add_argument("--selection-policy", choices=["value_per_cost", "first_available"], default="value_per_cost")
    parser.add_argument("--max-verification-cost", type=float, default=20.0,
                        help="Declared relative calculation-cost budget for the hypothesis strategy")
    parser.add_argument("--provider", choices=["deepseek", "gemini", "openai", "anthropic"], default="deepseek")
    parser.add_argument("--model", help="Explicit provider model identifier for LLM mode")
    parser.add_argument("--message", default="", help="Discussion context; numerical inputs come from --task")
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--max-tool-calls", type=int, default=6)
    parser.add_argument("--report", type=Path, help="Optional readable Markdown design report")
    parser.add_argument("--no-few-shots", action="store_true", help="Disable demonstration examples for ablation")
    parser.add_argument("--few-shots-dir", type=Path, help="Chemical exemplar notebook directory")
    args = parser.parse_args()
    if args.action == "design":
        if args.task is None:
            parser.error("design requires --task")
        llm = None
        if args.mode == "llm":
            if args.provider != "deepseek" and not args.model:
                parser.error("This provider requires --model; API keys are read from environment variables")
            from .llm import make_backend
            llm = make_backend(args.provider, args.model)
        tools = DwsimBackend(args.dwsim_home) if args.dwsim_home else None
        team = SeparationOrchestrator(tools=tools, backend=llm,
                                      strategy=args.strategy,
                                      verification_policy={"selection": args.selection_policy,
                                                           "max_cost_units": args.max_verification_cost},
                                      use_few_shots=not args.no_few_shots, few_shots_dir=args.few_shots_dir,
                                      limits=RunLimits(max_rounds=args.max_rounds, max_tool_calls=args.max_tool_calls))
        task = DesignTask.model_validate_json(args.task.read_text(encoding="utf-8"))
        state = team.run(task, message=args.message)
        result = {"state": state.model_dump(), "report": report_data(state), "report_markdown": render_report(state)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(result["report_markdown"] + "\n", encoding="utf-8")
    elif args.action == "doctor":
        backend = DwsimBackend(args.dwsim_home)
        result = backend.doctor()
    else:
        backend = DwsimBackend(args.dwsim_home)
        if args.request is None:
            parser.error("screen requires --request")
        request = BinaryVLERequest(**json.loads(args.request.read_text(encoding="utf-8")))
        evidence = backend.binary_vle(request)
        result = {"evidence": evidence, "review": review_binary_vle(evidence)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(str(args.output.resolve()))
    else:
        print(rendered)
    if args.action == "design" and state.status != "preliminary_complete":
        # Batch callers must not treat clarification/failure/budget stops as success.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
