"""Run the existing DeepSeek/PHA Agent's new M4 path; preserve first-pass results.

Use a new output folder for each experiment. No human design parameters are
passed to the Agent. Parallel jobs own independent native worker processes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sepmind.engineering import EngineeringOrchestrator
from sepmind.engineering.schemas import DesignBasis

ROOT=Path(__file__).resolve().parents[1]


def run_case(case, folder, provider):
    inputs=json.loads((ROOT/'case/curated'/case/'agent_input.json').read_text(encoding='utf-8'))
    inputs['design_level']='preliminary_equipment'
    basis=DesignBasis.model_validate(inputs)
    target=folder/case
    target.mkdir(parents=True,exist_ok=True)
    if (target/'run.json').exists():
        raise FileExistsError('Use a fresh output folder; existing experiment is immutable: '+str(target))
    (target/'input.json').write_text(basis.model_dump_json(indent=2),encoding='utf-8')
    team=EngineeringOrchestrator(basis,output_dir=target/'snapshots')
    if provider=='deepseek':
        team.configure(provider='deepseek',temperature=0)
    t=time.monotonic()
    state=team.run(message='Design from requirements only. Verify the fixed-design column in DWSIM, preserve all rejected candidates, and perform the available preliminary equipment calculations.')
    (target/'run.json').write_text(state.model_dump_json(indent=2),encoding='utf-8')
    (target/'report.md').write_text(state.report_markdown,encoding='utf-8')
    row={'case':case,'run_id':state.run_id,'status':state.status,'llm_calls':state.llm_calls,
         'provider':state.provider,'elapsed_s':time.monotonic()-t,
         'input_sha256':hashlib.sha256(basis.model_dump_json().encode()).hexdigest(),
         'gates':{k:v.status for k,v in state.gates.items()}}
    for key in ('verify_and_refine_column','calculate_energy_balance','estimate_column_equipment','estimate_auxiliary_equipment'):
        a=state.artifacts.get(key)
        if a:
            row[key]={'status':a.status,'validation':a.validation,'errors':[e.model_dump() for e in a.errors]}
            if key=='verify_and_refine_column':
                row[key]['selected_candidate']=a.data.get('selected_candidate')
    (target/'summary.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(row,ensure_ascii=False),flush=True)
    return row


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',nargs='+',default=['case-1a','case-1b','case-2','case-3'])
    parser.add_argument('--output',required=True)
    parser.add_argument('--provider',choices=['deepseek','deterministic'],default='deepseek')
    parser.add_argument('--jobs',type=int,choices=[1,2,3],default=3)
    args=parser.parse_args();folder=Path(args.output).resolve();folder.mkdir(parents=True,exist_ok=True)
    files=sorted([*ROOT.glob('sepmind/engineering/**/*.py'),*ROOT.glob('engineering/runtime_skills/**/SKILL.md'),
                  *ROOT.glob('sepmind/simulation/*dwsim*.py')])
    manifest={'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              'provider':args.provider,'cases':args.case,'physical_results':'native DWSIM only',
              'protocol':'Frozen requirements; first CMO counterexample retained; same-backend VLE resynthesis and bounded native MESH verification; preliminary equipment estimates remain qualified separately.'}
    (folder/'code_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    rows=[]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        tasks={pool.submit(run_case,c,folder,args.provider):c for c in args.case}
        for future in as_completed(tasks):
            try:rows.append(future.result())
            except Exception as exc:
                row={'case':tasks[future],'error':str(exc),'status':'failed'};rows.append(row);print(json.dumps(row),flush=True)
            (folder/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
