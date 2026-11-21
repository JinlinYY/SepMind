"""PFD and report rendering from the generated graph and retained tool records."""
from html import escape
from .graph import validate_graph


def selected_review(state):
    return next((candidate.get('review', {}) for candidate in state.candidates
                 if candidate['candidate_id'] == state.accepted_candidate_id), {})


def render_report(state):
    review = selected_review(state)
    lines = ['# SepMind自主拓扑综合运行报告', '',
             f'运行编号 {state.run_id}。当前状态 {state.status}。', '',
             '## 设计依据与综合范围', '',
             f'组分按以下顺序执行计算 {"、".join(state.basis.components)}。',
             f'进料 {state.basis.feed_flow_mol_s:g} mol/s，摩尔组成 {state.basis.feed_mole_fractions}，压力 {state.basis.pressure_Pa:g} Pa。',
             '外部进料明确指定为饱和液体，单元连接继承上游实际组成、流量和比焓。',
             f'物性假设依据 {state.basis.ideality_assumption_source}', '',
             f'当前运行范围为 {state.scope}。物性方法为 {state.basis.property_package}。',
             '设备效率与压降采用当前平衡级模型定义，数值验收范围为声明模型下的相平衡、物料、能量和原产品指标。', '',
             '## 选定流程', '']
    if state.accepted_candidate_id:
        lines += [f'选定候选 {state.accepted_candidate_id}。选择依据为已核验候选中的总再沸负荷，其次为塔数量。', '',
                  '|产品|目标组分|摩尔纯度|要求下限|回收率|要求下限|', '|---|---|---|---|---|---|']
        for target in review['targets']:
            lines.append(f"|{target['product_id']}|{target['component']}|{target['mole_fraction']:.10f}|{target['required_mole_fraction']:.10f}|{target['recovery']:.10f}|{target['required_recovery']:.10f}|")
        lines += ['', f"总再沸负荷 {review['duties']['reboiler_kW']:.6g} kW，总冷凝负荷 {review['duties']['condenser_kW']:.6g} kW。",
                  f"归一化组分残差 {review['component_residual']:.6e}，质量残差 {review['mass_residual']:.6e}，能量残差 {review['energy_residual']:.6e}。"]
    else:
        lines += ['搜索结束时获得的候选及失败证据如下。当前验收结果保留为未通过。']
    lines += ['', '## 候选与计算反证', '', '|候选|状态|图变更类型|塔数量|说明|', '|---|---|---|---|---|']
    for candidate in state.candidates:
        error = candidate.get('error', '').replace('|', '/').replace('\n', ' ')[:700]
        lines.append(f"|{candidate['candidate_id']}|{candidate['status']}|{candidate.get('change_kind', 'rejected_proposal')}|{len(candidate.get('graph', {}).get('columns', []))}|{error}|")
    for candidate in state.candidates:
        failed_targets = [target for target in candidate.get('review', {}).get('targets', []) if not target['purity_passed'] or not target['recovery_passed']]
        for target in failed_targets:
            lines += ['', f"候选 {candidate['candidate_id']} 的 {target['product_id']} 实际摩尔纯度 {target['mole_fraction']:.10f}，回收率 {target['recovery']:.10f}。", '']
    lines += ['', '## 专家公开决策', '']
    for decision in state.decisions:
        lines += [f"### {decision['role']}", '', decision.get('rationale', decision.get('observation', ''))]
        if decision.get('recommendation'):
            lines.append(decision['recommendation'])
        lines += ['', '证据编号 '+', '.join(decision.get('evidence_ids', [])), '']
    lines += ['## 执行统计与边界', '',
              f'实际LLM请求 {state.llm_calls} 次，实际原生请求 {state.native_calls} 次，阶段工具调用 {state.tool_calls} 次。',
              f"已验证的不同拓扑 {len({c['topology_signature'] for c in state.candidates if c['status']=='passed'})} 个，声明搜索目标 {state.basis.budget.desired_verified_topologies} 个。",
              '原生请求包含严格塔和阶段逸度探针。匹配输入与原始证据哈希的单元可复用，实际复用记录保存在events.jsonl。',
              f'实现版本哈希 {state.implementation_sha256}，运行期间源码一致性检查 {state.source_integrity_passed}。',
              '初始任务的流程拓扑为空，图连接与单元参数由本次Agent提出。图、数值请求、原生结果和独立验收均保存。',
              '适用范围为声明单元库内的有界流程综合。复杂萃取、循环、反应、膜与吸附流程需要对应的注册单元和验证方法。',
              '模型假设与数值闭合的证据需结合实验物性、动态可操作性及设备设计资格继续审查。', '']
    usage = [event['usage'] for event in state.provider_events if isinstance(event.get('usage'), dict)]
    recorded_tokens = [item['total_tokens'] for item in usage if isinstance(item.get('total_tokens'), int)]
    lines += [f'已记录Token合计 {sum(recorded_tokens)}，含完整Token计数的响应 {len(recorded_tokens)} 个，实际请求 {state.llm_calls} 次。',
              '缺少用量的请求保持缺失记录，调用明细以events.jsonl为准。', '']
    lines += [question+'\n' for question in state.questions]
    if state.graph is not None:
        lines += ['## 流程图', '', '![生成的流程图](flowsheet.svg)', '', '```mermaid', render_mermaid(state), '```', '']
    return '\n'.join(lines)


def render_mermaid(state):
    graph = state.graph
    if graph is None:
        return 'flowchart LR\n  feed["Feed"]'
    lines = ['flowchart LR', '  feed["Feed"]']
    for node in graph.columns:
        lines.append(f'  {node.column_id}["{node.column_id} · N={node.equilibrium_stages} · R={node.reflux_ratio:g}"]')
    for product in graph.products:
        lines.append(f'  {product.product_id}["{product.product_id}"]')
    for node in [*graph.columns, *graph.products]:
        source = node.input_stream.split('.')[0]
        port = node.input_stream.split('.')[1] if '.' in node.input_stream else 'feed'
        destination = getattr(node, 'column_id', None) or node.product_id
        lines.append(f'  {source} -->|{port}| {destination}')
    return '\n'.join(lines)


def render_svg(state):
    graph = state.graph
    if graph is None:
        raise ValueError('A graph is required for PFD rendering')
    try:
        structure = validate_graph(graph, state.basis)
    except ValueError:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120"><rect width="800" height="120" fill="white"/><text x="24" y="62" font-family="Arial" font-size="18">Candidate connectivity requires correction</text></svg>'
    nodes = {node.column_id: node for node in graph.columns}
    children = {node.input_stream: getattr(node, 'column_id', None) or node.product_id
                for node in [*graph.columns, *graph.products]}
    products = {product.product_id: product for product in graph.products}
    positions, leaf_index = {}, [0]

    def place(name, depth):
        if name in products:
            y = 115+leaf_index[0]*125
            leaf_index[0] += 1
        else:
            y = sum(place(children[name+'.'+port], depth+1) for port in ['distillate', 'bottoms'])/2
        positions[name] = (180+depth*280, y)
        return y

    root = children['feed']
    place(root, 0)
    width = max(x for x, _ in positions.values())+175
    height = max(y for _, y in positions.values())+100
    passed = state.status == 'passed' and state.accepted_candidate_id is not None
    title = 'SepMind · numerically verified preliminary flowsheet' if passed else 'SepMind · candidate flowsheet awaiting numerical acceptance'
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Generated process graph">',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#274958"/></marker></defs>',
           f'<rect width="{width}" height="{height}" fill="white"/>',
           f'<text x="24" y="33" font-family="Arial" font-size="18" fill="#1c3645">{title}</text>']
    def text(x, y, content, size=13):
        svg.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-family="Arial" font-size="{size}" fill="#243e4d">{escape(str(content))}</text>')

    root_y = positions[root][1]
    svg.append(f'<path d="M35 {root_y} H130" fill="none" stroke="#274958" stroke-width="2" marker-end="url(#arrow)"/>')
    text(73, root_y-13, f'{state.basis.feed_flow_mol_s:g} mol/s')
    text(73, root_y+23, 'Feed')
    for stream, destination in children.items():
        if stream == 'feed':
            continue
        parent, port = stream.split('.')
        x0, y0 = positions[parent]
        x1, y1 = positions[destination]
        y0 += -30 if port == 'distillate' else 30
        midpoint = (x0+x1)/2
        svg.append(f'<path d="M{x0+45} {y0} H{midpoint} V{y1} H{x1-55}" fill="none" stroke="#274958" stroke-width="2" marker-end="url(#arrow)"/>')
        text(midpoint-15, y0-9, 'D' if port == 'distillate' else 'B', 12)
    for name in structure['topological_order']:
        x, y = positions[name]
        node = nodes[name]
        svg.append(f'<rect x="{x-45}" y="{y-43}" width="90" height="86" rx="18" fill="#edf5f6" stroke="#186e7b" stroke-width="2"/>')
        for offset in [-20, 0, 20]:
            svg.append(f'<path d="M{x-30} {y+offset} H{x+30}" stroke="#799aa2" stroke-width="1"/>')
        text(x, y-58, name, 15)
        text(x, y+67, f'N {node.equilibrium_stages} · feed {node.feed_stage}')
        text(x, y+85, f'R {node.reflux_ratio:g}')
    review = selected_review(state)
    for name in products:
        x, y = positions[name]
        svg.append(f'<rect x="{x-55}" y="{y-34}" width="145" height="68" rx="6" fill="#f1f6ef" stroke="#739479"/>')
        text(x+17, y-8, name)
        port = review.get('products', {}).get(name)
        if port:
            text(x+17, y+17, f"{port['flow_mol_s']:.5g} mol/s")
        else:
            text(x+17, y+17, 'candidate outlet', 11)
    text(width/2, height-16, 'Total condensers and partial reboilers are included in each equilibrium-column model.', 11)
    svg.append('</svg>')
    return '\n'.join(svg)
