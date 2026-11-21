"""python -m experiments.sepmind_controls.run --output ... --phase all"""
import argparse, json, os, random, subprocess, sys, time, zipfile
from dataclasses import asdict, replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from .config import ROOT, HERE, TASKS, Budget, arms, digest, task_basis
from .initialization import LEGACY_POLICY, POLICIES, POLICY_DIRECTORY
from .logging import save

def source_manifest():
    files=set(HERE.rglob('*.py'))|set((HERE/'configs').glob('*.json'))|{HERE/'DESIGN.md'}
    files|=set((ROOT/'sepmind/engineering').rglob('*.py'))
    files|=set((ROOT/'engineering/runtime_skills').rglob('SKILL.md'))
    files|=set((ROOT/'engineering/knowledge').rglob('*.json'))
    files|=set((ROOT/'sepmind/simulation').glob('*dwsim*.py'))
    files|=set(POLICY_DIRECTORY.glob('*.md'))
    files|={ROOT/'sepmind/llm/backend_multimodel.py',ROOT/'sepmind/agent_runtime/orchestrator.py'}
    files|={ROOT/'case/curated'/old/'agent_input.json' for old in TASKS.values()}
    return {str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in sorted(files) if '__pycache__' not in str(p)}

def child(spec):
    from .controller import Episode
    arm=arms()[spec['arm']];limits=Budget(**spec['budget'])
    policy=spec.get('controller_policy',LEGACY_POLICY)
    e=Episode(spec['case'],arm,limits,spec['folder'],spec['seed'],spec['model'],
              controller_policy=policy,stop_at_first_target=spec.get('stop_at_first_target',False))
    r=e.run_episode();r.update(phase=spec['phase'],repeat=spec['repeat'],controller_policy=policy)
    save(Path(spec['folder'])/'result.json',r)

def launch(spec):
    job=Path(spec['job_file']);save(job,spec)
    started=time.monotonic()
    try:
        environment=os.environ.copy();environment['PYTHONUTF8']='1';environment['PYTHONIOENCODING']='utf-8'
        r=subprocess.run([sys.executable,'-X','utf8','-m','experiments.sepmind_controls.run','--child',str(job)],
            cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',
            env=environment,
            timeout=spec['budget']['episode_timeout_s']+90,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        job.with_suffix('.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
        result=Path(spec['folder'])/'result.json'
        if r.returncode or not result.exists():raise RuntimeError('Worker failed; original stdout/stderr retained')
        row=json.loads(result.read_text(encoding='utf8'));row['worker_time_s']=time.monotonic()-started
        save(result,row);return row
    except Exception as exc:
        # A launched infrastructure failure remains in the denominator. There
        # is no fabricated usage, physical quantity or residual for it.
        folder=Path(spec['folder']);folder.mkdir(parents=True,exist_ok=True)
        row={'case':spec['case'],'arm':spec['arm'],'phase':spec['phase'],'repeat':spec['repeat'],
            'seed':spec['seed'],'verified_success':False,'claimed_success':False,'false_acceptance':False,
            'first_strict_failed':None,'recovered':False,'terminal':'worker_failure',
            'error':type(exc).__name__+': '+str(exc),'worker_time_s':time.monotonic()-started,
            'llm_requests':None,'usage':None,'tool_calls':None,'strict_calls':None,'native_calls':None,
            'method_time_s':None,'simulation_time_s':None,'directory':str(folder)}
        save(folder/'worker_failure.json',row);return row

def preflight(out,model):
    from sepmind.simulation.dwsim import DwsimBackend
    from sepmind.llm.backend_multimodel import DeepSeekBackend
    start=time.monotonic();doctor=DwsimBackend(timeout_s=60).doctor()
    save(out/'environment.json',{'doctor':doctor,'python':sys.version,'platform':sys.platform,'logical_cpus':os.cpu_count()})
    backend=DeepSeekBackend(model_name=model,temperature=.2,max_tokens=128,json_mode=True,timeout_s=60,thinking=False)
    reply=backend.generate('Return JSON {"ready": true}. This is a transport preflight, not a design experiment.')
    metadata=backend.last_response_info or {}
    save(out/'provider_preflight.json',{'reply':reply,'metadata':{k:v for k,v in metadata.items() if k in ['provider','requested_model','served_model','request_id','usage']},'outside_episode_budgets':True,'duration_s':time.monotonic()-start})
    return metadata.get('served_model')

def column_revision_budget(max_revisions):
    """Give each column attempt room within the shared native-call cap."""
    base = Budget()
    columns = 1 + max_revisions
    return replace(base, columns=columns, native=columns + base.vle)


def batch(root,phase,repeats,jobs,model,seed, *, controller_policy=LEGACY_POLICY,
          budget=None, stop_at_first_target=False):
    out=root/phase;out.mkdir(parents=True,exist_ok=False)
    manifest=source_manifest();config=arms();limits=asdict(budget or Budget())
    plan=[{'case':c,'arm':a,'repeat':r,'phase':phase,'budget':limits,'model':model,
        'seed':seed+r,'folder':str(out/a/c/f'repeat-{r:02d}'),'controller_policy':controller_policy,
        'stop_at_first_target':stop_at_first_target}
        for c in TASKS for a in config for r in range(1,repeats+1)]
    random.Random(seed).shuffle(plan)
    for i,p in enumerate(plan):p['job_file']=str(out/'jobs'/f'{i:04d}.json')
    save(out/'protocol.json',{'phase':phase,'repeats':repeats,'expected':len(plan),'arms':{k:asdict(v) for k,v in config.items()},
        'budgets':limits,'tasks':{c:task_basis(c)[1] for c in TASKS},'model':model,'temperature':.2,'thinking':False,
        'jobs':jobs,'schedule_seed':seed,'provider_seed':None,'source_manifest':manifest,'controller_policy':controller_policy,
        'stop_at_first_target':stop_at_first_target,
        'scope':'matched-scope expert adapter, unchanged production defaults, four original binary tasks only'})
    save(out/'schedule.json',plan)
    with zipfile.ZipFile(out/'source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
        for file in manifest:z.write(ROOT/file,file)
    rows=[];next_index=0;halt=False
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        active={}
        while active or (next_index<len(plan) and not halt):
            if (root/'STOP_REQUESTED').exists():halt=True
            while len(active)<jobs and next_index<len(plan) and not halt:
                spec=plan[next_index];next_index+=1;active[pool.submit(launch,spec)]=spec
            completed,_=wait(active,return_when=FIRST_COMPLETED,timeout=15)
            if not completed:
                save(out/'status.json',{'completed':len(rows),'launched':next_index,'expected':len(plan),'active':list(active.values()),'halted':halt})
                continue
            for f in completed:
                spec=active.pop(f);row=f.result();rows.append(row)
                save(out/'results.json',rows)
                print(json.dumps({'phase':phase,'completed':len(rows),'expected':len(plan),'arm':row['arm'],
                    'case':row['case'],'repeat':row['repeat'],'success':row['verified_success'],
                    'terminal':row['terminal'],'llm':row.get('llm_requests'),'strict':row.get('strict_calls')},ensure_ascii=False),flush=True)
                error=row.get('error') or ''
                if any(x in error for x in ['HTTP 401','HTTP 402','HTTP 403','HTTP 429','authentication','insufficient balance']):halt=True
                if sum(r['terminal']=='worker_failure' for r in rows)>=2:halt=True
            save(out/'status.json',{'completed':len(rows),'launched':next_index,'expected':len(plan),'halted':halt,
                'unlaunched':len(plan)-next_index,'active':list(active.values())})
    unchanged=all(digest(ROOT/k)==v for k,v in manifest.items())
    integrity={'completed':len(rows),'expected':len(plan),'all_launched':next_index==len(plan),
        'unlaunched':len(plan)-next_index,'source_unchanged':unchanged,'provider_halt':halt,
        'framework_failures':sum(r['terminal'] in ['environment_or_worker_failure','worker_failure'] for r in rows),
        'served_models':sorted({v for r in rows for v in r.get('served_models',[])})}
    save(out/'completion.json',integrity)
    return integrity

def main():
    p=argparse.ArgumentParser();p.add_argument('--output');p.add_argument('--child');p.add_argument('--phase',choices=['pilot','main','all'],default='all')
    p.add_argument('--jobs',type=int,default=2,choices=[1,2]);p.add_argument('--model',default='deepseek-flash');p.add_argument('--skip-preflight',action='store_true')
    p.add_argument('--controller-policy',choices=POLICIES,default=LEGACY_POLICY)
    p.add_argument('--max-revisions', type=int, choices=(3, 5), default=3,
        help='Maximum strict-column starts after the initial attempt (shared across arms).')
    p.add_argument('--stop-at-first-target', action='store_true',
        help='Require review or submission after a converged candidate meets the product targets.')
    p.add_argument('--skip-historical-audit', action='store_true',
        help='Skip the separate audit of archived production runs outside this benchmark.')
    a=p.parse_args()
    if a.child:return child(json.loads(Path(a.child).read_text(encoding='utf8')))
    budget = column_revision_budget(a.max_revisions)
    out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    from .historical import audit
    from .analyze import summarize
    if not a.skip_historical_audit:
        audit(out)
    if not a.skip_preflight:preflight(out,a.model)
    if a.phase in ['pilot','all']:
        result=batch(out,'pilot',3,a.jobs,a.model,20261112,controller_policy=a.controller_policy,budget=budget,
                     stop_at_first_target=a.stop_at_first_target)
        summarize(out,'pilot')
        if not result['source_unchanged'] or not result['all_launched'] or result['framework_failures']:
            save(out/'MAIN_NOT_STARTED.json',{'reason':'Pilot incomplete or source changed; no main results fabricated.'});return
    if a.phase in ['main','all']:
        pilot=out/'pilot/completion.json'
        if not pilot.exists() or not json.loads(pilot.read_text())['all_launched']:
            raise RuntimeError('Complete the 3-repeat pilot before the main batch')
        pilot_protocol=json.loads((pilot.parent/'protocol.json').read_text(encoding='utf8'))
        if pilot_protocol.get('controller_policy',LEGACY_POLICY)!=a.controller_policy:
            raise RuntimeError('Use the same controller policy for the pilot and main batch')
        if (pilot_protocol['budgets'] != asdict(budget)
                or pilot_protocol.get('stop_at_first_target',False) != a.stop_at_first_target):
            raise RuntimeError('Use the same budgets and stopping rule for the pilot and main batch')
        batch(out,'main',10,a.jobs,a.model,20261113,controller_policy=a.controller_policy,budget=budget,
              stop_at_first_target=a.stop_at_first_target)
        summarize(out,'main')

if __name__=='__main__':main()
