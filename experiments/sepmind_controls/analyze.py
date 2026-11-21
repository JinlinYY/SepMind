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
    h=['配置','案例','实际n','验证成功','错误接受／宣称成功','首次失败后恢复','LLM请求','token','阶段工具','严格仿真','总时间s','仿真时间s','设计修订']
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
        '收敛并达到原始产品指标后，控制器要求按该组规则完成当前候选的审查或提交。'
        '带内部审查的组只有在审查未通过后才可继续修订。统一外部评测留在运行结束后。'
        if protocol.get('stop_at_first_target') else '各组按各自的决策与修订策略结束运行。'
    )
    report=f'''# SepMind架构对比与机制消融实验报告

当前阶段：**{phase}**。实际完成 {n}／计划 {expected} 次。预实验与正式实验分别统计，缺失任务保留为空。

## 实验设置与实现范围

使用D01–D04原始进料、压力、热状态、产品要求和Raoult／Raoult／NRTL／NRTL方法。保留D04的1.6倍初筛最小回流约束。共同计算阶段由PHA派生的原有协调器及注册工具执行；Agent对固定设计原子工具进行决策。H01/H02不参与。A4为匹配严格塔范围的完整机制适配器，不是生产G0–G9设备流程的字节级重放。

所有组使用真实 DeepSeek，请求模型为 {protocol['model']}，控制策略为 {protocol.get('controller_policy', 'legacy')}。采用温度 0.2、关闭 thinking 和 JSON 模式，每次最多 {budget['max_output_tokens']} 个输出 Token。单次运行上限为 {budget['llm']} 次 LLM 请求、{budget['actions']} 次动作、{budget['tools']} 次含重复准备的阶段工具和 {budget['native']} 次原生计算（严格塔最多 {budget['columns']} 次、VLE 最多 {budget['vle']} 次）。单次原生计算时限为 {budget['native_timeout_s']} s，运行时限为 {budget['episode_timeout_s']} s。所有角色通信均计入同一预算。

{stopping_scope}

各运行重新计算共同初筛，完整知识文本相同；A4应用可执行的阶段／Skill约束、独立数值验收、失败分类修正及依赖复用。B1仅移除决策强制约束，保留知识与物理数据安全条件；B2移除最终设计内部独立审查；B3取消机器分类修正，保留通用LLM合法重试；B4实际重算上游准备及已取得的原生VLE。详情见独立模块DESIGN.md和八份JSON配置。

## 统计定义

验证成功率分母为实际启动任务，包括失败；未启动任务另报。错误接受率分母为最终宣称成功的任务，同时JSON保留相对全部启动任务的比例。恢复率分母为首次实际严格塔尝试失败的任务，包括求解器失败；没有首次严格塔的任务不进入恢复分母。每案例正式目标n=10，预实验目标n=3。均值与样本标准差使用已观测值，n<2不填标准差，缺失费用不记0。重复调用不是新的独立工业物系。

最终外部评测独立重算原始物流的全部产品要求、组分／质量／能量闭合、输入冻结、模型与压力、级数及预算内回流范围，不调用运行时product_checks，不反馈给Agent，也不额外求解救援。所有候选保留，按最终提交记录评分，不择优替换。

## Table 1 架构对比

{tabulate(summary,['A1','A2','A3','A4'])}

## Table 2 核心机制消融

{tabulate(summary,['A4','B1','B2','B3','B4'])}

## 图与轨迹

![验证可靠性](figures/Figure1_reliability.png)

图1：各指标采用各自统计分母，柱上给出实际成功次数／分母；NA表示无相应宣称成功或首次失败集合，不能记0。完整范围0–100%。

![调用与时间](figures/Figure2_costs.png)

图2：LLM请求、严格塔次数与方法耗时，误差条为样本标准差。方法耗时含自身准备与审查，外部评分时间单列。两进程并发，时间反映当前机器调度，不证明普遍算法加速。

![决策与恢复](figures/Figure3_trajectory.png)

图3：确定性选择D03/A4中严格塔调用最多、并列最早的运行，展示其实际决策与执行，未按成功或美观择优。未获得恢复时如实显示失败终点。

## 失败原因与预算

终点分布：`{dict(terms)}`。逐次错误、拒绝提案、原生启动、超时及预算在events.jsonl；所有原生尝试另有请求与原始输出。求解不收敛不判作物理不可行。无可评分输出时物性／残差缺失，不能计算“0误差”。

历史SI乙醇／水10次重复审计另见批次根目录historical_ethanol_failure_audit.json：10次都失败，每次3次严格塔180s超时、1次VLE成功，耗尽4次原生上限；14–15次LLM未耗尽24次上限。新批不覆盖或合并这些失败，也不能把预算增加后的结果当作同预算改进。

## 成本与选择性重计算

完整统计包含实际token、阶段工具、严格塔、VLE、总方法时间、数值时间、修订、约束违反、重复计算和保留证据ID。B4的recalculation_tools/time记录实际重复开销；A4保留引用不伪装为已测时间节省。若两组轨迹不同，不能将总时间差归因于选择性重算；当前未执行同决策配对重放的时间为NA。

## 局限与公平性

四例已经用于开发，只覆盖三个相关二元体系。物性方法固定，因此B1不能评价自主选择不同热力学模型。A4为共同终点机制适配器，结论不得扩写为完整生产系统或所有多Agent架构排名。模型别名不等于固定权重版本；实际served_models随运行保存。提供方采样seed不可控，仅保证任务／调度／本地种子可追踪。全部结果来自本批真实运行，不预设SepMind获胜，失败不剔除。

无新物性实验、工业运行验证或完整设备资格声明；无生产默认行为改动或远程推送。
'''
    (dest/'experiment_report.md').write_text(report,encoding='utf8')
    (root/'experiment_report.md').write_text(report.replace('](figures/',f']({phase}/analysis/figures/'),encoding='utf8')
    save(dest/'figure_checks.json',{'phase':phase,'actual_runs':n,'planned':expected,'missing':expected-n,
        'formats':['PDF','SVG','PNG'],'minimum_font_pt':8,'missing_as_zero':False,'source':'actual results.json only',
        'figure3_selection':'A4/D03 most strict calls, earliest repeat tie','all_outcomes_retained':True})
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--phase',default='main');a=p.parse_args();summarize(a.output,a.phase)
