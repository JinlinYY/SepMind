"""Run SepMind topology synthesis with an existing real provider credential."""
import argparse
import json
from pathlib import Path
from .schemas import TopologyDesignBasis
from .orchestrator import TopologySynthesisOrchestrator, create_topology_backend
from .skills import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--basis', default=str(ROOT/'engineering/examples/topology_ideal_ternary.json'))
    parser.add_argument('--provider', choices=['deepseek', 'qwen'], default='deepseek')
    parser.add_argument('--output')
    args = parser.parse_args()
    basis = TopologyDesignBasis.model_validate_json(Path(args.basis).read_text(encoding='utf8'))
    team = TopologySynthesisOrchestrator(basis, create_topology_backend(args.provider), output_dir=args.output)
    result = team.run()
    print(json.dumps({'run_id': result.run_id, 'status': result.status,
                      'accepted_candidate_id': result.accepted_candidate_id,
                      'llm_calls': result.llm_calls, 'native_calls': result.native_calls,
                      'output_directory': str(team.folder)}, ensure_ascii=False), flush=True)
    return 0 if result.status == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
