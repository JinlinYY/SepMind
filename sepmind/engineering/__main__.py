"""Run a real PHA engineering slice: python -m sepmind.engineering --basis FILE."""

import argparse
import json
from pathlib import Path
from .agents import EngineeringOrchestrator
from .schemas import DesignBasis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--basis",type=Path,required=True)
    parser.add_argument("--provider",choices=["deepseek","deterministic"],default="deepseek")
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    team = EngineeringOrchestrator(basis=DesignBasis.model_validate_json(args.basis.read_text(encoding="utf-8")))
    if args.provider != "deterministic":
        team.configure(provider=args.provider)
    state = team.run(message="Execute explicit demonstration design basis")
    payload = state.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload,encoding="utf-8")
        print(str(args.output))
    else:
        print(payload)
    return 0 if state.gates["G4"].status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
