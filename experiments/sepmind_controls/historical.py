"""Read-only audit of the ten SI ethanol/water production failures."""
from pathlib import Path
import json
from .config import ROOT, digest
from .logging import save

def audit(out):
    root=ROOT/'output/engineering/quantitative_20261105/production_v1'
    summary=json.loads((root/'summary.json').read_text(encoding='utf8'))
    rows=[]
    for r in sorted((r for r in summary if r['case']=='case-2'),key=lambda r:r['repeat']):
        folder=ROOT/r['directory']
        run=json.loads((folder/'run.json').read_text(encoding='utf8'))
        events=json.loads((folder/'native_events.json').read_text(encoding='utf8'))
        rows.append({'repeat':r['repeat'],'strict_success':r['strict_success'],'status':run['status'],
            'llm_calls':run['llm_calls'],'llm_cap':24,'native_cap':4,
            'native_calls':len(events),'columns':sum(e['kind']=='rigorous_column' for e in events),
            'vle':sum(e['kind']=='binary_vle' for e in events),
            'gates':{k:v['status'] for k,v in run['gates'].items()},
            'verify_error':run['artifacts'].get('verify_and_refine_column',{}).get('error_type'),
            'events':[{'kind':e['kind'],'status':e['status'],'error':e.get('error'),
                'duration_s':e['elapsed_s'],'request':e['request']} for e in events],
            'run_file':str((folder/'run.json').relative_to(ROOT)),
            'run_sha256':digest(folder/'run.json'),'native_sha256':digest(folder/'native_events.json')})
    result={'count':len(rows),'all_original_failures_retained':len(rows)==10,
        'verified_success_count':sum(r['strict_success'] for r in rows),
        'column_timeouts':sum('TimeoutError' in (e.get('error') or '') for r in rows for e in r['events']),
        'interpretation':'Three actual strict-column timeouts and one successful native VLE per run exhaust the four-native cap; 14–15 LLM calls do not exhaust the 24-call cap. Numerical failure and budget exhaustion, not proof of physical infeasibility.',
        'rows':rows}
    save(Path(out)/'historical_ethanol_failure_audit.json',result)
    return result
