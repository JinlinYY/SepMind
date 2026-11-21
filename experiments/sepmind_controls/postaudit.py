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
    md='\n\n## JSONL独立事后审计\n\n'
    md+=f'逐次核对{len(rows)}个已启动运行的LLM、工具、原生启动计数和最终外部评分。失败事件分类：`{dict(categories)}`。同一原生超时可同时在工具层记录，事件数不等于失败运行数。\n\n'
    md+=f'被安全执行层阻止的固定条件违规提案按组计数：`{dict(violations)}`。这与已执行方案的固定约束违反分开报告，避免将“拦截后为0”解释为Agent没有提出违规动作。完整逐运行审计见`{phase}/analysis/post_audit.json`。\n'
    md+='\n主表恢复率采用首次实际严格塔失败作为可重复定义的分母；另报告广义恢复率，分母为出现工具失败、无效提案、求解失败或已收敛但指标失败的运行，分子为这些运行最终验证成功数。它不将未启动任务视作失败，也不表示共享同一个反例的因果对照。成功宣称按最终结构化claim_success定义，非事后自由解释措辞。\n\n|配置|广义恢复成功／出现任意失败的运行|\n|---|---|\n'
    for v in broad_recovery:
        if v['case']=='ALL':md+=f"|{v['arm']}|{v['numerator']}/{v['denominator']}|\n"
    md+='\n严格仿真次数指实际启动的固定设计DWSIM请求。原有数值驱动在同一请求内可能尝试多个求解器，所有组的数值设置相同；已返回记录的solver_attempts另计，超时导致完整内部轨迹未知时保持未知，不能假定只有一次或填充为零。返回记录的原生收敛标志与未强制产品组成标志亦独立核查。\n'
    expected=10 if phase=='main' else 3
    complete=all(sum(r['arm']==a and r['case']==c for r in rows)==expected for a in arms() for c in ['D01','D02','D03','D04'])
    if complete:
        baseline=group(rows,'A4');md+='\n## 完整阶段的观测差异与成本\n\n下表为同一预算上限、相同四任务权重下的描述性差异，不是显著性或因果优势声明。成功率差按A4减对照组计算，允许为负。\n\n|对照|A4−对照验证成功率／百分点|对照LLM均值±SD|A4 LLM均值±SD|对照方法时间s均值±SD|A4方法时间s均值±SD|\n|---|---|---|---|---|---|\n'
        for a in ['A1','A2','A3','B1','B2','B3','B4']:
            other=group(rows,a);delta=100*(baseline['success']['rate']-other['success']['rate'])
            md+='|'+a+'|'+f'{delta:+.1f}'+'|'+mean(other['llm_requests'])+'|'+mean(baseline['llm_requests'])+'|'+mean(other['method_time_s'])+'|'+mean(baseline['method_time_s'])+'|\n'
        md+='\n四例属于三个相关体系，重复为服务调用层级重复；差异应同时结合逐案例结果、未知成本覆盖率、失败类型和接口限制解释。零次观测到错误接受不表示真实错误概率为零。\n'
    concordance=root/'historical_request_concordance.json'
    if concordance.exists():
        md+='\n## 历史乙醇失败的实现版本溯源\n\n10次历史35级候选与既有接受记录在忽略保存路径与证据ID后数值请求完全相同，包括初始化；但历史冻结源码与当前驱动／worker／严格塔实现存在版本差异，enthalpy_seed与rigorous修正模块则相同。源代码差异本身不能证明二元求解行为改变，仍不能单独判定资源调度、数值稳定性或具体实现的因果贡献。旧新源码哈希及diff单列保存；这些诊断资料没有进入新Agent提示，也不以新结果覆盖旧失败。\n'
    report=root/'experiment_report.md'
    if report.exists() and '## JSONL独立事后审计' not in report.read_text(encoding='utf8'):
        with report.open('a',encoding='utf8') as f:f.write(md)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--phase',default='main');a=p.parse_args();audit(a.output,a.phase)
