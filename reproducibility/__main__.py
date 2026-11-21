"""Run the paper's design settings, export evidence, or replay a column."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .tables import CASES, binary_residuals, export_tables, load_evidence, manuscript_tables


def replay_column(args, evidence):
    from separation.tools.dwsim import DwsimBackend, RigorousColumnRequest

    archived = evidence["binary"][args.case][args.design]
    args.output.mkdir(parents=True, exist_ok=False)
    request = RigorousColumnRequest(**{
        **archived["request"], "save_path": str((args.output / "column.dwxmz").resolve()),
    })
    request_path = args.output / "request.json"
    request_path.write_text(json.dumps(asdict(request), indent=2) + "\n", encoding="utf-8")
    backend = DwsimBackend(installation=args.dwsim_home, timeout_s=args.timeout)
    if not str(backend.doctor()["version"]).startswith("DWSIM version 9.0.5"):
        raise RuntimeError("This replay requires DWSIM 9.0.5")
    record = backend.rigorous_column(request)
    c, e = binary_residuals(record)
    comparison = {
        "case": args.case, "design": args.design, "archived_evidence_id": archived["evidence_id"],
        "replay_evidence_id": record["evidence_id"], "component_relative": c, "energy_relative": e,
        "archived_and_replayed_product_mole_fractions": {
            stream: [data["outputs"][stream]["mole_fractions"] for data in (archived, record)]
            for stream in ("distillate", "bottoms")
        },
    }
    for path, data in (("column_result.json", record), ("comparison.json", comparison)):
        (args.output / path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved replay and numerical comparison in {args.output}")


def design_case(args, evidence):
    root = Path(__file__).resolve().parents[1]
    if args.setting == "I":
        from sepmind.engineering.agents import EngineeringOrchestrator
        from sepmind.engineering.schemas import DesignBasis

        case_folder = evidence["binary"][args.case]["preliminary_design"]
        source = root / "case/curated" / case_folder / "agent_input.json"
        basis = DesignBasis.model_validate_json(source.read_text(encoding="utf-8"))
        initial_topology = "single_column"
    else:
        from sepmind.engineering.topology.binary import BinaryTopologyOrchestrator, binary_case_basis
        from sepmind.engineering.topology.orchestrator import create_topology_backend

        basis = binary_case_basis(args.case)
        initial_topology = None

    if args.basis_only:
        print(json.dumps(dict(setting=args.setting, initial_topology=initial_topology,
                              basis=basis.model_dump(mode="json")), indent=2))
        return

    args.output = args.output.resolve()
    if not args.output.is_relative_to(root / "output") or args.output == root / "output":
        raise ValueError("Choose a fresh design-run directory under output/")
    if args.setting == "I":
        args.output.mkdir(parents=True, exist_ok=False)
        team = EngineeringOrchestrator(basis=basis, output_dir=args.output / "snapshots")
        if args.provider == "deepseek":
            team.configure(provider="deepseek")
        state = team.run(message="Design the specified single-column separation from its declared requirements.")
        (args.output / "result.json").write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
    else:
        team = BinaryTopologyOrchestrator(basis, create_topology_backend("deepseek"),
                                          output_dir=args.output, prior_evidence=[])
        state = team.run("Synthesize a flowsheet from the declared feed and product requirements.")

    print(f"Setting {args.setting}, {args.case}: {state.status}. Records: {args.output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="Check archived numerical records and benchmark coverage")
    export = commands.add_parser("export", help="Export the manuscript tables as CSV")
    export.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("replay-column", help="Run one archived strict-column design in DWSIM 9.0.5")
    replay.add_argument("--case", choices=CASES, required=True)
    replay.add_argument("--design", choices=("human", "sepmind"), required=True)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--dwsim-home", type=Path)
    replay.add_argument("--timeout", type=float, default=180)
    design = commands.add_parser("design", help="Run setting I (prescribed) or II (empty topology)")
    design.add_argument("--setting", choices=("I", "II"), required=True)
    design.add_argument("--case", choices=CASES, required=True)
    design.add_argument("--provider", choices=("deepseek", "deterministic"), default="deepseek")
    design.add_argument("--basis-only", action="store_true", help="Print task inputs without running a design")
    design.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = load_evidence()
    if args.command == "design":
        if not args.basis_only and not args.output:
            parser.error("design requires a fresh --output directory under output/")
        if not args.basis_only and args.setting == "II" and args.provider != "deepseek":
            parser.error("setting II requires DeepSeek")
        design_case(args, evidence)
        return
    if args.command == "replay-column":
        replay_column(args, evidence)
        return
    tables = manuscript_tables(evidence)
    if args.command == "export":
        export_tables(tables, args.output)
        print(f"Exported {len(tables)} tables to {args.output}")
    else:
        print(f"Verified {len(evidence['binary'])} binary cases, {len(evidence['hybrid'])} integrated cases and "
              f"{sum(len(b['runs']) for b in evidence['benchmark_batches'])} recorded benchmark runs.")


if __name__ == "__main__":
    main()
