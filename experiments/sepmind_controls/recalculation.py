"""Paired upstream recalculation microbenchmark, not autonomous success data.

No historical accepted design, human settings or additional LLM is used. Strict
columns are deliberately outside this timing microbenchmark; main B4 already
executes its complete strict-column path within the common episode budget.
"""
import argparse,json,time,hashlib,random
from pathlib import Path
from .config import Budget,task_basis,arms,TASKS
from .logging import Ledger,save
from .tools import Meter,Tools,prepare
from .analyze import average

def run(root,repeats=3):
    root=Path(root);out=root/'paired_upstream_recalculation';out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for case in TASKS:
        for repeat in range(1,repeats+1):
            folder=out/case/f'repeat-{repeat:02d}';ledger=Ledger(folder/'events.jsonl');meter=Meter(Budget())
            basis,_=task_basis(case);state,screen=prepare(basis,folder/'initial',meter,ledger)
            tools=Tools(basis,screen,folder/'tools',meter,ledger,arms()['A4'],state)
            tools.sample_native()
            base_native=tools.native
            # Same unchanged upstream conditions for a proposed N/feed revision.
            key=json.dumps(basis.model_dump(),sort_keys=True)
            source_digest=hashlib.sha256(key.encode()).hexdigest()
            order=['selective','full'];random.Random(20261112+repeat).shuffle(order)
            results={}
            for arm in order:
                tools.native=base_native;before=meter.tools;before_native=meter.native;t=time.monotonic()
                if arm=='full':tools.rescreen_full()
                else:
                    assert hashlib.sha256(json.dumps(basis.model_dump(),sort_keys=True).encode()).hexdigest()==source_digest
                    retained=[a.artifact_id for a in state.artifacts.values()]
                    assert all(state.artifacts[k].status=='success' for k in ['calculate_binary_vle','calculate_material_balance','calculate_mccabe_thiele_stages'])
                    ledger.emit('measured_cache_reuse',retained_ids=retained,native_evidence_id=base_native['evidence_id'])
                results[arm]={'tool_calls':meter.tools-before,'native_calls':meter.native-before_native,
                    'elapsed_s':time.monotonic()-t}
            row={'case':case,'repeat':repeat,'order':order,'results':results,
                'tools_saved':results['full']['tool_calls']-results['selective']['tool_calls'],
                'native_saved':results['full']['native_calls']-results['selective']['native_calls'],
                'upstream_time_saved_s':results['full']['elapsed_s']-results['selective']['elapsed_s'],
                'scope':'Actual upstream preparation/native-equilibrium overhead only; no strict-solver speedup or autonomous task success inferred.'}
            rows.append(row);save(folder/'result.json',row);save(out/'results.json',rows)
            print(json.dumps(row),flush=True)
    summary={c:{k:average([r[k] for r in rows if r['case']==c]) for k in ['tools_saved','native_saved','upstream_time_saved_s']} for c in TASKS}
    save(out/'summary.json',summary)
    note='\n\n## 同条件配对上游重算微基准\n\n仅测量在相同任务与级数／进料位置修订场景下，上游准备和原生VLE的重算开销。严格塔求解不在此微基准内，因此不能解释为整套Agent加速。两分支顺序按固定种子打散，全部为真实工具计时，无额外LLM。\n\n|案例|重复n|节省工具调用均值±SD|节省原生VLE次数均值±SD|上游节省秒均值±SD|\n|---|---|---|---|---|\n'
    for c in TASKS:
        cells=[]
        for k in ['tools_saved','native_saved','upstream_time_saved_s']:
            v=summary[c][k];cells.append(f"{v['mean']:.3f} ± {v['sd']:.3f}" if v['sd'] is not None else f"{v['mean']:.3f}; SD NA")
        note+='|'+c+'|'+str(repeats)+'|'+'|'.join(cells)+'|\n'
    (out/'paired_recalculation_report.md').write_text(note,encoding='utf8')
    report=root/'experiment_report.md'
    if report.exists():
        with report.open('a',encoding='utf8') as f:f.write(note)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repeats',type=int,default=3);a=p.parse_args();run(a.output,a.repeats)
