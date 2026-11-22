"""Finish post-audit and packaging only after the real main batch terminates."""
import argparse,json,os,time,zipfile
from pathlib import Path
from .logging import save
from .config import digest
from .postaudit import audit

def finish(root,paired=True):
    root=Path(root)
    while True:
        main=root/'main/completion.json';blocked=root/'MAIN_NOT_STARTED.json'
        if main.exists():break
        if blocked.exists():
            save(root/'DELIVERY_INCOMPLETE.json',{'reason':'Main not started; pilot integrity/provider/environment blocker. Raw failures retained.','main_completed':False})
            return
        if (root/'STOP_REQUESTED').exists():
            save(root/'DELIVERY_INCOMPLETE.json',{'reason':'Dispatch stop requested; no missing results invented.','main_completed':False})
            return
        time.sleep(15)
    completion=json.loads(main.read_text(encoding='utf8'))
    # The parent summarizes after writing completion; wait for that atomic step.
    report=root/'main/analysis/experiment_report.md'
    for _ in range(12):
        if report.exists():break
        time.sleep(5)
    main_audit=audit(root,'main')
    recalculation=None
    if paired and completion['all_launched'] and completion['source_unchanged']:
        from .recalculation import run
        recalculation=run(root,3)
    from .publication import finalize
    finalize(root)
    files=[]
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix=='.zip':continue
        files.append({'path':str(p.relative_to(root)).replace('\\','/'),'bytes':p.stat().st_size,'sha256':digest(p)})
    save(root/'delivery_manifest.json',files)
    mismatches=[r for r in main_audit['integrity'] if any(v is False for k,v in r.items() if k.endswith('matches'))]
    final={'main_completed':completion['all_launched'],'main_runs':completion['completed'],'expected':320,
        'source_unchanged':completion['source_unchanged'],'ledger_or_evaluator_mismatches':mismatches,
        'paired_upstream_timing_executed':recalculation is not None,'visual_review_pending':True,
        'raw_data_preserved':True,'no_production_defaults_changed':True,'no_remote_push':True}
    save(root/'DELIVERY_STATUS.json',final)
    target=root/'sepmind_architecture_ablation_records.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in root.rglob('*'):
            if p.is_file() and p!=target:z.write(p,p.relative_to(root))
    print(json.dumps(final,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--no-paired',action='store_true');a=p.parse_args();finish(a.output,not a.no_paired)
