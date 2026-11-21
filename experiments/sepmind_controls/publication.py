"""Final presentation QA from actual records, without changing evaluation."""
from pathlib import Path
import json,textwrap
from .config import arms
from .logging import save

def finalize(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(root);p=root/'main';dest=p/'analysis/figures'
    rows=json.loads((p/'results.json').read_text(encoding='utf8'))
    candidates=[r for r in rows if r['arm']=='A4' and r['case']=='D03']
    if candidates:
        r=sorted(candidates,key=lambda r:(-(r.get('strict_calls') or 0),r['repeat']))[0]
        es=[json.loads(x) for x in (Path(r['directory'])/'events.jsonl').read_text(encoding='utf8').splitlines()]
        # Preserve the entire physical/review/submission sequence and the final
        # external outcome, rather than truncating the first fifteen events.
        visible=[]
        for e in es:
            if e['kind']=='decision' and e['action']['tool'] in ['sample_native_vle','screen_native','simulate_column','review','finish','stop']:
                a=e['action'];msg='Decision: '+a['tool']
                if a['tool']=='simulate_column':msg+=f"; N={a.get('equilibrium_stages')}, feed={a.get('feed_stage')}, factor={a.get('reflux_factor')}, profile={a.get('profile')}"
                color='#0072B2'
            elif e['kind']=='native_end':
                msg=f"DWSIM {e['action']}: {e['status']}; {e['duration_s']:.1f} s";color='#D55E00' if e['status']=='failed' else '#007A5E'
            elif e['kind']=='tool_end' and e.get('tool')=='review':
                passed=e.get('data',{}).get('passed');msg=f"Internal numerical review: {passed}";color='#007A5E' if passed else '#D55E00'
            elif e['kind']=='external_evaluation':
                msg=f"External verification (after episode): {e['final_review']['passed']}";color='#243746'
            elif e['kind']=='episode_error':msg=e.get('error','Episode failure')[:110];color='#D55E00'
            else:continue
            visible.append((e,msg,color))
        plt.rcParams.update({'font.family':'Arial','font.size':8,'pdf.fonttype':42,'svg.fonttype':'none'})
        height=max(4.5,len(visible)*.29+1.3)
        fig,ax=plt.subplots(figsize=(7.2,height));ax.axis('off')
        for i,(e,msg,color) in enumerate(visible):
            y=.94-i*.86/max(len(visible),1)
            ax.text(.01,y,f"{e['elapsed_s']:.1f} s",fontsize=8,va='top')
            ax.text(.16,y,textwrap.fill(msg,85),fontsize=8,va='top',color=color)
        ax.set_title(f"D03 · SepMind A4 · repeat {r['repeat']} · terminal: {r['terminal']}",fontsize=10,loc='left')
        fig.text(.03,.02,'Selection: most strict calls; earliest repeat tie. Setup-only actions omitted; no recovery invented.',fontsize=8)
        fig.tight_layout(rect=(0,.05,1,1))
        for ext in ['pdf','svg','png']:fig.savefig(dest/f'Figure3_trajectory.{ext}',dpi=350,bbox_inches='tight')
        plt.close(fig)
        save(dest/'Figure3_selected_trace.json',{'selection_rule':'A4/D03 maximum strict calls; earliest repeat tie',
            'run':r,'events':[e for e,_,_ in visible],'final_external_outcome_included':True,'no_physical_sequence_truncation':True})
    report=root/'experiment_report.md'
    text=report.read_text(encoding='utf8')
    legend='\n\n配置定义：'+ '；'.join(k+'＝'+v.label for k,v in arms().items())+'。A4在架构表和消融基准中是同一组运行，不额外重复或择优。\n'
    text=text.replace('## Table 1 架构对比',legend+'\n## Table 1 架构对比',1)
    text+='\n\n## 原始记录与启动环境事件\n\n首批v1有50个工作进程因Windows GBK无法输出继承PHA注册日志中的emoji而在模型／仿真前退出，另46项未启动；没有当作算法性能样本。全部记录保留于`prior_environment_failures_v1.zip`与`prior_batches.json`。v2统一UTF-8启动，正式结果不覆盖或混入v1。测试执行摘要见`test_execution_summary.json`，原PHA归属、许可及复用说明见`provenance/`。\n'
    report.write_text(text,encoding='utf8')
    save(dest/'publication_checks.json',{'actual_main_runs':len(rows),'target':320,'minimum_font_pt':8,
        'vector_exports':True,'selected_trace_not_truncated':True,'claims_inferred_from_actual_results_only':True,
        'visual_review_pending':True})
