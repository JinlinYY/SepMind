"""Run and report the five-revision follow-up under the two recorded policies."""

import argparse
import json
import os
from collections import Counter
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sepmind.llm.local_credentials import deepseek_key

from .analyze import group, summarize
from .config import ROOT, TASKS, arms
from .historical import audit as historical_audit
from .initialization import EVIDENCE_POLICY, LEGACY_POLICY
from .logging import save
from .postaudit import audit
from .run import batch, column_revision_budget, preflight


ARCHIVES = {
    LEGACY_POLICY: 'sepmind-controls-20261112-v2',
    EVIDENCE_POLICY: 'sepmind-controls-evidence-v2-20261118',
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def run_phase(folder, policy, phase, repeats, seed, *, stop_at_first_target):
    budget = column_revision_budget(5)
    path = folder / phase
    completion = batch(folder, phase, repeats, 2, 'deepseek-flash', seed,
                       controller_policy=policy, budget=budget, stop_at_first_target=stop_at_first_target)
    if (not completion['source_unchanged'] or not completion['all_launched']
            or completion['framework_failures'] or completion['provider_halt']
            or completion['served_models'] != ['deepseek-flash']):
        raise RuntimeError(f'Incomplete or invalid phase. See {path / "completion.json"}')

    protocol = load(path / 'protocol.json')
    if phase == 'main':
        pilot = load(folder / 'pilot/protocol.json')
        for field in ('source_manifest', 'controller_policy', 'budgets', 'tasks', 'arms',
                      'model', 'stop_at_first_target'):
            if protocol[field] != pilot[field]:
                raise RuntimeError(f'Pilot and main differ in {field}')
    rows = load(path / 'results.json')
    expected = Counter((arm, case, r) for arm in arms() for case in TASKS
                       for r in range(1, repeats + 1))
    observed = Counter((row['arm'], row['case'], row['repeat']) for row in rows)
    if (observed != expected or protocol['budgets'] != asdict(budget)
            or protocol['stop_at_first_target'] != stop_at_first_target):
        raise RuntimeError(f'Invalid coverage or budgets in {path}')
    for row in rows:
        if (row['controller_policy'] != policy or row['stop_at_first_target'] != stop_at_first_target
                or row['strict_calls'] > budget.columns or row['native_calls'] > budget.native
                or row['vle_calls'] > budget.vle or row['llm_requests'] > budget.llm
                or row['tool_calls'] > budget.tools or row['fixed_constraint_violations']):
            raise RuntimeError(f'Protocol violation in {row["directory"]}')
        if stop_at_first_target:
            audit_submission_gate(row)
    summarize(folder, phase)
    reviewed = audit(folder, phase)
    if any(value is False for row in reviewed['integrity'] for value in row.values()):
        raise RuntimeError(f'Ledger/score audit failed in {path}')
    return rows


def audit_submission_gate(row):
    log_path = Path(row['directory']) / 'events.jsonl'
    pending = None
    for line in log_path.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        if event['kind'] == 'target_submission_gate':
            pending = event['required_action'], event['evidence_id']
        elif pending and event['kind'] == 'tool_start':
            action, evidence_id = pending
            if action != 'review' or event['tool'] != action or event.get('evidence_id') not in (None, evidence_id):
                raise RuntimeError(f'Unexpected tool after reaching the product targets in {log_path}')
            pending = None
    if pending and row['terminal'] == 'submitted':
        if pending != ('finish', row['selected_evidence_id']):
            raise RuntimeError(f'Submission did not match the on-spec evidence in {log_path}')


def fixed(value, digits):
    if value is None:
        return 'NA'
    precise = Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f'{precise:,.{digits}f}'


def publish(root):
    config = arms()
    main, archives = {}, {}
    rules = set()
    for policy, archived in ARCHIVES.items():
        path = root / policy / 'main'
        completion = load(path / 'completion.json')
        if not (completion['all_launched'] and completion['source_unchanged']
                and completion['completed'] == 320
                and (path / 'analysis/post_audit.json').is_file()):
            raise RuntimeError(f'Formal coverage or audit incomplete in {path}')
        main[policy] = load(path / 'results.json')
        archives[policy] = load(ROOT / 'outputs' / archived / 'main/results.json')
        rules.add(load(path / 'protocol.json')['stop_at_first_target'])
    if len(rules) != 1:
        raise RuntimeError('Both policies must use the same stopping rule')
    stop_at_first_target = rules.pop()

    lines = [
        '# SepMind architecture and ablation results with up to five revisions', '',
        'D01–D04 use prescribed single columns. Each numerical policy has 320 formal runs with 40 per arm.',
        'Each run permits six rigorous-column starts including the initial calculation, and two native VLE calls. The policies are original numerical review and revision, and numerical review with explicit initialization evidence.',
        *(['After a design meets the product targets, the arm proceeds to review and submission. An internal review failure can reopen revision. The external evaluator runs after the episode.'] if stop_at_first_target else []), '',
        '| Arm | Policy | Verified runs | Success rate | LLM calls/run | Total LLM calls | Simulations/run | Tokens/run |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for arm, cfg in config.items():
        for policy, rows in main.items():
            stats = group(rows, arm)
            verified = stats['success']
            call_total = sum(r['llm_requests'] for r in rows if r['arm'] == arm)
            lines.append(f'| {arm} {cfg.label} | {policy} | {verified["numerator"]}/{verified["denominator"]}'
                         f' | {fixed(100*verified["rate"],1)}% | {fixed(stats["llm_requests"]["mean"],2)}'
                         f' | {call_total} | {fixed(stats["strict_calls"]["mean"],2)}'
                         f' | {fixed(stats["tokens"]["mean"],0)} |')
    lines.extend([
        '', 'Means include successes and failures. Token means use complete usage records. Simulation counts include every start, including solver failures and timeouts.', '',
        '## Comparison with historical runs allowing three revisions', '',
        '| Arm | Policy | Verified runs, three to five revisions | Change (percentage points) | Fifth column starts | Sixth column starts | First external pass at starts 5–6 and finally submitted |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |',
    ])
    for arm in config:
        for policy, rows in main.items():
            data = [r for r in rows if r['arm'] == arm]
            old = sum(r['verified_success'] for r in archives[policy] if r['arm'] == arm)
            new = sum(r['verified_success'] for r in data)
            selected_late = sum(row['verified_success'] and not any(
                attempt.get('index', 0) <= 4 and attempt['external_review']['passed']
                for attempt in row['endpoint_reviews']) and any(
                attempt.get('index', 0) > 4
                and attempt.get('evidence_id') == row['selected_evidence_id']
                for attempt in row['endpoint_reviews']) for row in data)
            lines.append(f'| {arm} | {policy} | {old}/40 → {new}/40 | {100*(new-old)/40:+.1f}'
                         f' | {sum(r["strict_calls"] >= 5 for r in data)}'
                         f' | {sum(r["strict_calls"] >= 6 for r in data)} | {selected_late} |')
    lines.extend([
        '', 'The historical original-policy batch used different rigorous-column code. The explicit-initialization batches share the numerical implementation. The provider samples independently across batches, and the agent sees the budget. Interpret late-start passes separately from differences in success rate.', '',
        *(['These batches used different stopping rules, so changes in success rate also reflect the early stopping rule.', ''] if stop_at_first_target else []),
        '## Formal records', '',
        '[Original-policy runs](legacy/main/results.json) · [Explicit-initialization runs](evidence_v2/main/results.json) · '
        '[Original-policy report](legacy/main/analysis/experiment_report.md) · [Explicit-initialization report](evidence_v2/main/analysis/experiment_report.md)',
    ])
    (root / 'sepmind_five_revision_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop-at-first-target', action='store_true')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    status_path = root / 'study_status.json'
    if status_path.exists():
        raise RuntimeError('Use a fresh study directory')
    key = deepseek_key() or os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DeepSeek credentials are required')
    os.environ['DEEPSEEK_API_KEY'] = key
    completed = []
    try:
        for policy in ARCHIVES:
            folder = root / policy
            folder.mkdir()
            historical_audit(folder)
            preflight(folder, 'deepseek-flash')
            for phase, repeats, seed in (('pilot', 3, 20261112), ('main', 10, 20261113)):
                save(status_path, {'phase': phase, 'policy': policy, 'completed_phases': completed})
                run_phase(folder, policy, phase, repeats, seed,
                          stop_at_first_target=args.stop_at_first_target)
                completed.append(f'{policy}/{phase}')
        publish(root)
    except Exception as exc:
        save(status_path, {'phase': 'stopped', 'completed_phases': completed,
                           'error': f'{type(exc).__name__}: {exc}'})
        raise
    save(status_path, {'phase': 'complete', 'completed_phases': completed})


if __name__ == '__main__':
    main()
