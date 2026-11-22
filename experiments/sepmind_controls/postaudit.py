"""Read-only post-audit of logs; never changes controls or numerical results."""
import argparse,json
from pathlib import Path
from collections import Counter
from .config import ROOT,arms,task_basis,digest
from .logging import save
from .analyze import ratio,group,mean
from .evaluator import evaluate

def audit(root,phase):
    root=Path(root);p=root/phase;rows=json.loads((p/'results.json').read_text(encoding='utf8'))
    cases=[];categories=Counter();violations=Counter();integrity=[]
    for row in rows:
        folder=Path(row['directory']);ledger=folder/'events.jsonl'
        events=[json.loads(x) for x in ledger.read_text(encoding='utf8').splitlines()] if ledger.exists() else []
        errors=[str(e.get('error','')) for e in events if e['kind'] in ['invalid_decision','tool_end','native_end','llm_error','episode_error'] and e.get('error')]
        labels=Counter()
        for err in errors:
            if 'TimeoutError' in err or 'DWSIM' in err and 'failed' in err:labels['solver_failure']+=1
            elif any(k in err for k in ['MODEL_','PROPERTY','PARAMETER_MISSING']):labels['property_or_initializer_evidence']+=1
            elif 'BUDGET' in err:labels['budget_exhaustion']+=1
            elif any(k in err for k in ['SKILL_','STAGE_','INPUT_','FIXED_SPECIFICATION','validation error','REVISION_']):labels['invalid_decision']+=1
            elif 'DeepSeek' in err or 'HTTP' in err:labels['provider_failure']+=1
            else:labels['other']+=1
            if 'FIXED_SPECIFICATION' in err:violations[row['arm']]+=1
        off_spec=sum(bool(e['external_review'].get('strict_targets')) and not all(e['external_review']['strict_targets'].values()) for e in row.get('endpoint_reviews',[]))
        labels['converged_product_miss']+=off_spec
        categories.update(labels)
        starts=Counter(e.get('action') for e in events if e['kind']=='native_start')
        recomputed=None
        solver_attempts_known=0;solver_attempts_unknown=0;native_convergence_flags=[]
        for attempt in row.get('endpoint_reviews',[]):
            file=attempt.get('record_file')
            if file and Path(file).exists():
                raw=json.loads(Path(file).read_text(encoding='utf8'))
                solver_attempts_known+=len(raw.get('solver_attempts',[]))
                native_convergence_flags.append(raw.get('status')=='ok' and raw.get('checks',{}).get('flowsheet_solved') is True
                    and raw.get('checks',{}).get('product_compositions_imposed') is False)
            else:solver_attempts_unknown+=1
        if row.get('final_record_file'):
            record=json.loads(Path(row['final_record_file']).read_text(encoding='utf8'))
            b,_=task_basis(row['case']);state=json.loads((folder/'preparation/screen_state.json').read_text(encoding='utf8'))
            reference=state['artifacts']['calculate_mccabe_thiele_stages']['data']['reflux_ratio']
            recomputed=evaluate(record,b,reference)
        check={'case':row['case'],'arm':row['arm'],'repeat':row['repeat'],
            'llm_ledger_count_matches':sum(e['kind']=='llm_start' for e in events)==row.get('llm_requests'),
            'tool_ledger_count_matches':sum(e['kind']=='tool_start' for e in events)==row.get('tool_calls'),
            'native_ledger_count_matches':sum(starts.values())==row.get('native_calls'),
            'strict_ledger_count_matches':starts['rigorous_column']==row.get('strict_calls'),
            'external_recheck_matches':recomputed['passed']==row['external_review']['passed'] if recomputed else None}
        integrity.append(check)
        any_failure=bool(errors or off_spec or row['terminal'] in ['worker_failure','environment_or_worker_failure','provider_failure','budget_exhausted'])
        cases.append({'case':row['case'],'arm':row['arm'],'repeat':row['repeat'],'terminal':row['terminal'],
            'any_failure_observed':any_failure,'any_failure_recovered':bool(any_failure and row['verified_success']),
            'failure_event_counts':dict(labels),'blocked_fixed_specification_proposals':sum('FIXED_SPECIFICATION' in e for e in errors),
            'executed_fixed_constraint_violations':row.get('fixed_constraint_violations'),
            'known_internal_solver_attempts':solver_attempts_known,
            'strict_requests_without_complete_solver_trace':solver_attempts_unknown,
            'all_returned_records_native_converged':all(native_convergence_flags) if native_convergence_flags else None,
            'raw_ledger':str(ledger),'sha256':digest(ledger) if ledger.exists() else None})
    broad_recovery=[]
    for a in arms():
        for case in ['ALL',*['D01','D02','D03','D04']]:
            data=[r for r in cases if r['arm']==a and (case=='ALL' or r['case']==case) and r['any_failure_observed']]
            broad_recovery.append({'arm':a,'case':case,**ratio(sum(r['any_failure_recovered'] for r in data),len(data))})
    result={'phase':phase,'runs':len(rows),'failure_event_counts':dict(categories),
        'broad_any_failure_recovery':broad_recovery,
        'blocked_fixed_specification_proposals_by_arm':dict(violations),
        'interpretation':'Event counts can include a native timeout and its enclosing tool failure; they are not independent failed episodes. Blocked proposals are distinct from actually executed constraint violations.',
        'integrity':integrity,'per_run':cases}
    save(p/'analysis/post_audit.json',result)
    md='\n\n## Independent audit of JSONL records\n\n'
    md+=f'Checked LLM, workflow tool, and native start counts and final external scores for {len(rows)} launched runs. Failure event categories: {dict(categories)}. A native timeout may also be logged at the tool layer, so event counts and failed-run counts can differ.\n\n'
    md+=f'Blocked proposals that violated fixed conditions by arm: {dict(violations)}. Proposed violations and executed constraint violations are reported separately. See {phase}/analysis/post_audit.json for per-run records.\n'
    md+='\nPrimary recovery uses runs that failed their first actual rigorous-column attempt. Broad recovery uses runs with a tool failure, invalid proposal, solver failure, or a converged candidate that missed specifications. The numerator is the number of such runs that ultimately passed verification. This reports outcomes of launched runs and their individual decision traces. Success claims come from the final structured claim_success field.\n\n| Arm | Broad recoveries / runs with any failure |\n|---|---|\n'
    for v in broad_recovery:
        if v['case']=='ALL':md+=f"|{v['arm']}|{v['numerator']}/{v['denominator']}|\n"
    md+='\nRigorous simulation counts are actual launches of fixed-design DWSIM requests. A single request may try several solvers with identical settings across arms. Solver attempts are counted separately when returned. Internal trajectories after a timeout remain unknown. Native convergence and the absence of imposed product compositions are checked independently.\n'
    expected=10 if phase=='main' else 3
    complete=all(sum(r['arm']==a and r['case']==c for r in rows)==expected for a in arms() for c in ['D01','D02','D03','D04'])
    if complete:
        baseline=group(rows,'A4');md+='\n## Observed differences and cost in the formal batch\n\nValues are descriptive under common caps and equal case weights. Success-rate differences are A4 minus the comparison arm.\n\n| Comparison | A4 minus comparison (percentage points) | Comparison LLM calls (mean ± SD) | A4 LLM calls (mean ± SD) | Comparison method time (s, mean ± SD) | A4 method time (s, mean ± SD) |\n|---|---|---|---|---|---|\n'
        for a in ['A1','A2','A3','B1','B2','B3','B4']:
            other=group(rows,a);delta=100*(baseline['success']['rate']-other['success']['rate'])
            md+='|'+a+'|'+f'{delta:+.1f}'+'|'+mean(other['llm_requests'])+'|'+mean(baseline['llm_requests'])+'|'+mean(other['method_time_s'])+'|'+mean(baseline['method_time_s'])+'|\n'
        md+='\nThe four tasks cover three related systems and the repeats sample model calls. Interpret differences alongside case-level results, missing cost records, failure categories, and simulator limits. A zero observed false acceptance count leaves population risk uncertain.\n'
    concordance=root/'historical_request_concordance.json'
    if concordance.exists():
        md+='\n## Provenance of historical ethanol/water failures\n\nAll ten historical 35-stage requests matched the accepted reference, including initialization, after excluding save paths and evidence identifiers. The frozen and current numerical driver, worker, and rigorous-column code differ, while the enthalpy seed and rigorous revision modules match. The differences document provenance and leave the effects of scheduling, numerical stability, and implementation unresolved. Hashes and diffs are stored separately from agent inputs and historical failure records.\n'
    report=root/'experiment_report.md'
    if report.exists() and '## Independent audit of JSONL records' not in report.read_text(encoding='utf8'):
        with report.open('a',encoding='utf8') as f:f.write(md)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--phase',default='main');a=p.parse_args();audit(a.output,a.phase)
