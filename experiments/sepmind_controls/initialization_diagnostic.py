"""Recompute all historical A4 enthalpy-seed blocks with unchanged tower proposals."""

import argparse
import json
from pathlib import Path

from .config import ROOT, Budget, arms, digest, task_basis
from .controller import Action
from .evaluator import evaluate
from .initialization import EVIDENCE_POLICY
from .logging import Ledger, save
from .tools import Meter, Tools, prepare


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def blocked_proposals(history):
    for row in load(history):
        if row['arm'] != 'A4' or row['strict_calls'] != 0 or row['verified_success']:
            continue
        source = Path(row['directory'])/'events.jsonl'
        events = [json.loads(line) for line in source.read_text(encoding='utf8').splitlines()]
        if not any(e['kind']=='tool_end' and e.get('tool')=='simulate_column'
                   and 'DATA_PARAMETER_MISSING: no native phase enthalpies' in e.get('error','') for e in events):
            continue
        decisions = [e['action'] for e in events if e['kind']=='decision' and e['action']['tool']=='simulate_column']
        if len(decisions) != 1 or decisions[0]['profile'] != 'native_enthalpy':
            raise ValueError(f'Ambiguous archived initialization decision: {source}')
        yield row, source, Action.model_validate(decisions[0])


def run(history, output, *, try_reviewed_redesign=False):
    cases = list(blocked_proposals(history))
    if not cases:
        raise ValueError('No archived enthalpy-seed block found')
    output.mkdir(parents=True, exist_ok=False)
    save(output/'protocol.json', {'purpose':'Same-proposal real DWSIM diagnostic without LLM calls',
        'history':str(history), 'history_sha256':digest(history), 'controller_policy':EVIDENCE_POLICY,
        'try_reviewed_redesign':try_reviewed_redesign,
        'cases':[{'case':r['case'], 'repeat':r['repeat'], 'events':str(source), 'sha256':digest(source)}
                 for r, source, _ in cases]})
    results = []
    for row, source, proposal in cases:
        case, repeat = row['case'], row['repeat']
        folder = output/case/f'repeat-{repeat:02d}'
        ledger, meter = Ledger(folder/'events.jsonl'), Meter(Budget())
        basis, provenance = task_basis(case)
        prior_input = load(source.with_name('input.json'))
        if prior_input['basis'] != basis.model_dump() or prior_input['source']['source_sha256'] != provenance['source_sha256']:
            raise ValueError(f'Frozen task mismatch: {case}/{repeat}')
        prepared, screen = prepare(basis, folder/'preparation', meter, ledger)
        prior_screen = load(source.parent/'preparation/screen_state.json')
        if screen['reflux_ratio'] != prior_screen['artifacts']['calculate_mccabe_thiele_stages']['data']['reflux_ratio']:
            raise ValueError(f'Frozen reflux basis mismatch: {case}/{repeat}')
        tools = Tools(basis, screen, folder/'tools', meter, ledger, arms()['A4'], prepared,
                      controller_policy=EVIDENCE_POLICY)
        phase = tools.execute_action(Action(tool='sample_native_vle', rationale='Recompute the archived VLE coverage'))
        attempt = tools.execute_action(proposal) if phase['status']=='success' else None
        record = tools.records.get(tools.last_id)
        review = None
        if record is not None:
            review = tools.execute_action(Action(tool='review', rationale='Check the actual latest strict result'))
        score = evaluate(record['record'], basis, screen['reflux_ratio']) if record else None
        redesign = None
        hint = tools.reviewed_redesign() if try_reviewed_redesign else None
        if hint is not None:
            changed = Action(tool='simulate_column', rationale='Try the reviewed fixed-reflux stage margin', **hint['candidate'])
            candidate = tools.execute_action(changed)
            revised_review = None
            revised_score = None
            if candidate['status']=='success':
                revised_review = tools.execute_action(Action(tool='review', rationale='Review the revised design'))
                revised_record = tools.records[candidate['data']['evidence_id']]['record']
                revised_score = evaluate(revised_record, basis, screen['reflux_ratio'])
            redesign = {'suggestion':hint, 'strict_result':candidate, 'internal_review':revised_review,
                        'external_review':revised_score}
        result = {'case':case, 'repeat':repeat, 'archived_strict_starts':row['strict_calls'],
            'new_strict_starts':meter.columns, 'llm_requests':meter.llm, 'model':basis.thermodynamic_model,
            'archived_proposal':proposal.model_dump(), 'fresh_vle':phase, 'strict_result':attempt,
            'internal_review':review, 'external_review':score, 'redesign':redesign}
        save(folder/'result.json', result)
        results.append(result)
        save(output/'results.json', results)
        print(json.dumps({'case':case,'repeat':repeat,'strict':meter.columns,
            'external_passed':score.get('passed') if score else None,
            'redesign_passed':bool(redesign and (redesign['external_review'] or {}).get('passed'))},
            ensure_ascii=False),flush=True)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, default=ROOT/'outputs/sepmind-controls-20261112-v2/main/results.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--try-reviewed-redesign', action='store_true')
    args = parser.parse_args()
    run(args.history.resolve(), args.output.resolve(), try_reviewed_redesign=args.try_reviewed_redesign)
