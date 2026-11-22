"""Actual-only summaries and scientific figures; missing data stay NA."""
import argparse, csv, json, math, statistics, textwrap
from pathlib import Path
from collections import Counter
from .config import arms, TASKS
from .logging import save

def average(values):
    v=[x for x in values if isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)]
    return {'n':len(v),'mean':statistics.mean(v) if v else None,
        'sd':statistics.stdev(v) if len(v)>1 else None}

def ratio(numerator,denominator):
    if denominator==0:return {'numerator':numerator,'denominator':0,'rate':None,'sd':None}
    binary=[1.]*numerator+[0.]*(denominator-numerator)
    return {'numerator':numerator,'denominator':denominator,'rate':numerator/denominator,
        'sd':statistics.stdev(binary) if denominator>1 else None}

def group(rows,arm,case=None):
    data=[r for r in rows if r['arm']==arm and (case is None or r['case']==case)]
    claims=[r for r in data if r.get('claimed_success')]
    failed=[r for r in data if r.get('first_strict_failed') is True]
    result={'arm':arm,'case':case or 'ALL','n':len(data),
        'success':ratio(sum(bool(r.get('verified_success')) for r in data),len(data)),
        'false_acceptance':ratio(sum(bool(r.get('false_acceptance')) for r in claims),len(claims)),
        'false_acceptance_unconditional':ratio(sum(bool(r.get('false_acceptance')) for r in data),len(data)),
        'recovery':ratio(sum(bool(r.get('recovered')) for r in failed),len(failed)),
        'failure_terminals':dict(Counter(r['terminal'] for r in data if not r.get('verified_success')))}
    for field in ['llm_requests','tool_calls','strict_calls','vle_calls','native_calls','method_time_s',
        'simulation_time_s','revision_count','invalid_decisions','fixed_constraint_violations',
        'recalculation_tools','recalculation_native','recalculation_time_s','retained_artifact_references']:
        result[field]=average([r.get(field) for r in data])
    result['tokens']=average([(r.get('usage') or {}).get('total_tokens') for r in data])
    return result

def percent(v):
    if v['rate'] is None:return f"NA (0 eligible)"
    sd=f" ± {100*v['sd']:.1f}" if v['sd'] is not None else ''
    return f"{v['numerator']}/{v['denominator']} ({100*v['rate']:.1f}{sd}%)"

def mean(v):
    if v['mean'] is None:return 'NA'
    return f"{v['mean']:.2f}"+(f" ± {v['sd']:.2f}" if v['sd'] is not None else '')+f" [n={v['n']}]"

def tabulate(summary,ids):
    h=['Arm','Case','Runs','Verified','False acceptances / success claims','Recovery after first failure','LLM requests','Tokens','Workflow tools','Rigorous simulations','Total time (s)','Simulation time (s)','Revisions']
    lines=['| '+' | '.join(h)+' |','| '+' | '.join(['---']*len(h))+' |']
    for a in ids:
        for g in [v for v in summary if v['arm']==a]:
            lines.append('| '+' | '.join([a,g['case'],str(g['n']),percent(g['success']),percent(g['false_acceptance']),
                percent(g['recovery']),mean(g['llm_requests']),mean(g['tokens']),mean(g['tool_calls']),
                mean(g['strict_calls']),mean(g['method_time_s']),mean(g['simulation_time_s']),mean(g['revision_count'])])+' |')
    return '\n'.join(lines)

def plot(summary,rows,dest,phase):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'Arial','font.size':8,'axes.labelsize':8,'axes.titlesize':9,
        'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','axes.spines.right':False,'axes.spines.top':False})
    dest.mkdir(parents=True,exist_ok=True)
    colors=['#6E7785','#0072B2','#009E73','#D55E00','#CC79A7','#56B4E9','#E69F00','#58508D']
    ids=list(arms());overall={r['arm']:r for r in summary if r['case']=='ALL'}
    fig,axs=plt.subplots(1,3,figsize=(7.2,3.6))
    for panel,(ax,key,title) in enumerate(zip(axs,['success','false_acceptance','recovery'],['Verified success','False acceptance','Failure recovery'])):
        for i,a in enumerate(ids):
            r=overall[a][key]
            if r['rate'] is not None:
                ax.bar(i,100*r['rate'],color=colors[i],width=.7,edgecolor='black',linewidth=.35)
                ax.text(i,min(103,100*r['rate']+3),f"{r['numerator']}/{r['denominator']}",ha='center',fontsize=8,rotation=90)
            else:ax.text(i,3,'NA',ha='center',rotation=90,fontsize=8)
        ax.set_xticks(range(8),ids,rotation=45);ax.set_ylim(0,118);ax.set_yticks([0,25,50,75,100]);ax.set_ylabel('Runs / %')
        ax.set_title(chr(97+panel)+'  '+title,loc='left');ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
    fig.suptitle(phase.upper()+' — actual runs; labels give metric-specific denominators',fontsize=9)
    fig.tight_layout()
    for ext in ['pdf','svg','png']:fig.savefig(dest/f'Figure1_reliability.{ext}',dpi=350,bbox_inches='tight')
    plt.close(fig)
    fig,axs=plt.subplots(1,3,figsize=(7.2,3.6))
    for panel,(ax,key,title) in enumerate(zip(axs,['llm_requests','strict_calls','method_time_s'],['LLM requests','DWSIM strict calls','Method time / s'])):
        for i,a in enumerate(ids):
            v=overall[a][key]
            if v['mean'] is None:ax.text(i,0,'NA',ha='center');continue
            ax.bar(i,v['mean'],yerr=v['sd'],color=colors[i],width=.7,capsize=2,edgecolor='black',linewidth=.35)
        ax.set_xticks(range(8),ids,rotation=45);ax.set_title(chr(97+panel)+'  '+title,loc='left');ax.set_ylim(bottom=0)
        ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
    fig.suptitle(phase.upper()+' — mean ± sample SD; only observed values',fontsize=9);fig.tight_layout()
    for ext in ['pdf','svg','png']:fig.savefig(dest/f'Figure2_costs.{ext}',dpi=350,bbox_inches='tight')
    plt.close(fig)
    # Deterministic representative rule: D03 A4, most actual column attempts;
    # ties by repeat. Never select the best-looking successful trace.
    candidates=[r for r in rows if r['arm']=='A4' and r['case']=='D03']
    representative=sorted(candidates,key=lambda r:(-(r.get('strict_calls') or 0),r['repeat']))[0] if candidates else None
    fig,ax=plt.subplots(figsize=(7.2,5.5));ax.axis('off')
    if representative:
        ledger=Path(representative['directory'])/'events.jsonl'
        events=[json.loads(v) for v in ledger.read_text(encoding='utf8').splitlines()] if ledger.exists() else []
        selected=[e for e in events if e['kind'] in ['decision','native_end','external_evaluation','episode_error']]
        selected=selected[:15]
        for i,e in enumerate(selected):
            if e['kind']=='decision':
                a=e['action'];msg=f"LLM decision: {a['tool']}; N={a.get('equilibrium_stages')}; feed={a.get('feed_stage')}; profile={a.get('profile')}"
            elif e['kind']=='native_end':msg=f"DWSIM {e['action']}: {e['status']} ({e['duration_s']:.1f} s)"
            elif e['kind']=='external_evaluation':msg=f"External verification: {e['final_review']['passed']} (after episode; no feedback)"
            else:msg=e.get('error','episode error')[:100]
            y=.94-i*.058
            ax.text(.02,y,f"{e['elapsed_s']:.1f} s",fontsize=8,va='top')
            ax.text(.17,y,textwrap.fill(msg,85),fontsize=8,va='top',color='#D55E00' if 'failed' in msg else '#243746')
        ax.set_title(f"D03 / A4 / repeat {representative['repeat']} — terminal: {representative['terminal']}",loc='left',fontsize=10)
        save(dest/'Figure3_selected_trace.json',{'selection_rule':'A4 D03 maximum strict calls; tie minimum repeat; not selected for success','run':representative,'events':selected})
    else:ax.text(.1,.5,'No executed D03/A4 trace available. No synthetic trajectory.',fontsize=10)
    fig.tight_layout()
    for ext in ['pdf','svg','png']:fig.savefig(dest/f'Figure3_trajectory.{ext}',dpi=350,bbox_inches='tight')
    plt.close(fig)

def summarize(root,phase):
    root=Path(root);folder=root/phase;dest=folder/'analysis';dest.mkdir(parents=True,exist_ok=True)
    rows=json.loads((folder/'results.json').read_text(encoding='utf8')) if (folder/'results.json').exists() else []
    config=arms();summary=[group(rows,a,c) for a in config for c in [*TASKS,None]]
    save(dest/'summary.json',summary)
    for name,ids in [('Table1_architectures',['A1','A2','A3','A4']),('Table2_ablations',['A4','B1','B2','B3','B4'])]:
        data=[r for r in summary if r['arm'] in ids]
        save(dest/(name+'.json'),data)
        (dest/(name+'.md')).write_text(tabulate(data,ids),encoding='utf8')
        with (dest/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            fields=['arm','case','n','success_n','success_denominator','success_rate','success_sd','false_n','claim_denominator','false_rate','recovery_n','first_failure_denominator','recovery_rate']
            for metric in ['llm_requests','tokens','tool_calls','strict_calls','method_time_s','simulation_time_s','revision_count','recalculation_tools','recalculation_time_s']:fields.extend([metric+'_mean',metric+'_sd',metric+'_n'])
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            for g in data:
                v={'arm':g['arm'],'case':g['case'],'n':g['n'],'success_n':g['success']['numerator'],'success_denominator':g['success']['denominator'],'success_rate':g['success']['rate'],'success_sd':g['success']['sd'],
                    'false_n':g['false_acceptance']['numerator'],'claim_denominator':g['false_acceptance']['denominator'],'false_rate':g['false_acceptance']['rate'],
                    'recovery_n':g['recovery']['numerator'],'first_failure_denominator':g['recovery']['denominator'],'recovery_rate':g['recovery']['rate']}
                for metric in ['llm_requests','tokens','tool_calls','strict_calls','method_time_s','simulation_time_s','revision_count','recalculation_tools','recalculation_time_s']:
                    for k in ['mean','sd','n']:v[metric+'_'+k]=g[metric][k]
                writer.writerow(v)
    plot(summary,rows,dest/'figures',phase)
    protocol=json.loads((folder/'protocol.json').read_text(encoding='utf8'))
    expected=protocol['expected'];n=len(rows);terms=Counter(r['terminal'] for r in rows)
    budget = protocol['budgets']
    stopping_scope = (
        'Once a converged design meets the original product specifications, the controller requires review or submission under that arm’s rules. '
        'Arms with internal review allow further revision only after a failed review. The common external evaluation runs after the episode.'
        if protocol.get('stop_at_first_target') else 'Each arm stops according to its assigned decision and revision policy.'
    )
    report=f'''# SepMind architecture comparison and mechanism ablation

Phase **{phase}** completed {n} of {expected} planned runs. Pilot and formal runs are summarized separately. Missing runs remain blank.

## Experimental design and scope

The benchmark uses the original D01–D04 feeds, pressures, feed states, product specifications, and Raoult/Raoult/NRTL/NRTL methods. D04 retains the reflux constraint of 1.6 times the screening minimum. The inherited coordinator and registered tools prepare the common design basis. Agents choose from atomic actions for a prescribed column. This benchmark covers D01–D04. A4 implements the full mechanism within the matched rigorous-column scope.

All arms call DeepSeek with model {protocol['model']} under the {protocol.get('controller_policy', 'legacy')} control policy. Temperature is 0.2, thinking is disabled, JSON mode is enabled, and responses are capped at {budget['max_output_tokens']} tokens. Each run permits {budget['llm']} LLM requests, {budget['actions']} actions, {budget['tools']} workflow tool calls including repeated preparation, and {budget['native']} native calls (up to {budget['columns']} rigorous columns and {budget['vle']} VLE calls). The native timeout is {budget['native_timeout_s']} s and the episode timeout is {budget['episode_timeout_s']} s. Communication across roles shares these limits.

{stopping_scope}

Each run repeats common screening and uses the same knowledge text. A4 applies stage and Skill constraints, independent verification, failure-specific revision, and dependency-based reuse. B1 disables decision enforcement while retaining knowledge and physical input checks. B2 disables final internal review. B3 switches to general retries within valid actions. B4 repeats upstream preparation and any previously obtained native VLE. See DESIGN.md and the eight arm configuration files.

## Metrics and denominators

Verified success uses all launched runs, including failures. Report unlaunched tasks separately. False acceptance uses the runs that claimed success as its denominator. The JSON also reports the fraction of all launched runs. Recovery uses only runs that attempted and failed their first rigorous column, including solver failures. Formal and pilot targets are 10 and 3 runs per case, respectively. Means and sample standard deviations use observed values. Standard deviations require at least two observations. Missing costs remain blank. Repeats sample the model service on the same binary systems.

The external evaluator independently recomputes product specifications and component, mass, and energy closure from raw streams. It checks fixed inputs, model, pressure, stage count, and permitted reflux bounds. It scores the submitted candidate and retains all attempts, using separate checks from the controller and no additional recovery simulations.

## Table 1. Architecture comparison

{tabulate(summary,['A1','A2','A3','A4'])}

## Table 2. Mechanism ablation

{tabulate(summary,['A4','B1','B2','B3','B4'])}

## Figures and decision trace

![Verification reliability](figures/Figure1_reliability.png)

Figure 1. Bars show percentages and observed counts over the relevant denominator. NA indicates no success claims or first-failure episodes for that comparison. The axis spans 0–100%.

![Calls and runtime](figures/Figure2_costs.png)

Figure 2. LLM requests, rigorous column starts, and method runtime. Error bars are sample standard deviations. Method time includes preparation and internal review, with external evaluation reported separately. Times reflect the scheduling of two concurrent workers on this machine.

![Decisions and recovery](figures/Figure3_trajectory.png)

Figure 3. The trace shows the D03/A4 run with the most rigorous-column calls, using the earliest run to break ties. It includes the observed decisions, executions, and final status.

## Failures and budgets

Terminal status counts: {dict(terms)}. Individual errors, rejected proposals, native starts, timeouts, and budgets appear in events.jsonl. Each native attempt also has a request and raw output if returned. Record nonconvergence as a numerical outcome. Missing properties and residuals remain blank when there is no scorable output.

The historical_ethanol_failure_audit.json records 10 earlier ethanol/water failures. Each reached the limit of four native calls with three 180 s rigorous-column timeouts and one successful VLE call. LLM usage was 14–15 requests out of 24. These episodes retain their original budget and are reported separately from the current batch.

## Cost and selective recalculation

The report records observed tokens, workflow calls, rigorous-column starts, VLE, method and numerical time, revisions, constraint violations, recalculation, and retained evidence IDs. B4 recalculation tools and time measure actual repeated work. A4 evidence reuse identifies retained results. Differences between unpaired runs reflect their full decision trajectories. Paired replay time remains NA.

## Scope and limitations

The four development cases cover three related binary systems. All arms use fixed property methods, so B1 addresses rule enforcement within that scope. A4 is a matched-endpoint implementation. Served model metadata are saved because a provider alias can change. Task order and local seeds are recorded, while provider-side sampling remains uncontrolled. All launched failures contribute to the reported outcomes.

The study evaluates preliminary designs and numerical verification under the specified model and simulation boundaries.
'''
    (dest/'experiment_report.md').write_text(report,encoding='utf8')
    (root/'experiment_report.md').write_text(report.replace('](figures/',f']({phase}/analysis/figures/'),encoding='utf8')
    save(dest/'figure_checks.json',{'phase':phase,'actual_runs':n,'planned':expected,'missing':expected-n,
        'formats':['PDF','SVG','PNG'],'minimum_font_pt':8,'missing_as_zero':False,'source':'actual results.json only',
        'figure3_selection':'A4/D03 most strict calls, earliest repeat tie','all_outcomes_retained':True})
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--phase',default='main');a=p.parse_args();summarize(a.output,a.phase)
