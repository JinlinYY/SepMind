"""PFD and report rendering from the generated graph and retained tool records."""
from html import escape
from .graph import validate_graph


def selected_review(state):
    return next((candidate.get('review', {}) for candidate in state.candidates
                 if candidate['candidate_id'] == state.accepted_candidate_id), {})


def render_report(state):
    review = selected_review(state)
    lines = ['# SepMind autonomous flowsheet synthesis report', '',
             f'Run ID {state.run_id}. Current status {state.status}.', '',
             '## Design basis and synthesis scope', '',
             f'Component order {",".join(state.basis.components)}.',
             f'Feed {state.basis.feed_flow_mol_s:g} mol/s, mole fractions {state.basis.feed_mole_fractions}, pressure {state.basis.pressure_Pa:g} Pa.',
             'External feeds are saturated liquids. Connected streams carry the calculated upstream composition, flow rate, and specific enthalpy.',
             f'Property assumptions {state.basis.ideality_assumption_source}', '',
             f'Run scope {state.scope}. Property method {state.basis.property_package}.',
             'The equilibrium-stage model defines the efficiency and pressure-drop assumptions. Verification covers phase equilibrium, material and energy balances, and the original product specifications under this model.', '',
             '## Selected flowsheet', '']
    if state.accepted_candidate_id:
        lines += [f'Selected candidate {state.accepted_candidate_id}. Verified candidates are ranked first by total reboiler duty and then by column count.', '',
                  '| Product | Target component | Mole fraction | Minimum | Recovery | Minimum |', '|---|---|---|---|---|---|']
        for target in review['targets']:
            lines.append(f"|{target['product_id']}|{target['component']}|{target['mole_fraction']:.10f}|{target['required_mole_fraction']:.10f}|{target['recovery']:.10f}|{target['required_recovery']:.10f}|")
        lines += ['', f"Total reboiler duty {review['duties']['reboiler_kW']:.6g} kW, total condenser duty {review['duties']['condenser_kW']:.6g} kW.",
                  f"Normalized component residual {review['component_residual']:.6e}, mass residual {review['mass_residual']:.6e}, energy residual {review['energy_residual']:.6e}."]
    else:
        lines += ['The search ended without an accepted design. The evaluated candidates and failed checks are listed below.']
    lines += ['', '## Candidates and failed checks', '', '| Candidate | Status | Graph change | Column count | Details |', '|---|---|---|---|---|']
    for candidate in state.candidates:
        error = candidate.get('error', '').replace('|', '/').replace('\n', ' ')[:700]
        lines.append(f"|{candidate['candidate_id']}|{candidate['status']}|{candidate.get('change_kind', 'rejected_proposal')}|{len(candidate.get('graph', {}).get('columns', []))}|{error}|")
    for candidate in state.candidates:
        failed_targets = [target for target in candidate.get('review', {}).get('targets', []) if not target['purity_passed'] or not target['recovery_passed']]
        for target in failed_targets:
            lines += ['', f"Candidate {candidate['candidate_id']}, {target['product_id']} mole fraction {target['mole_fraction']:.10f}, recovery {target['recovery']:.10f}.", '']
    lines += ['', '## Expert decisions', '']
    for decision in state.decisions:
        lines += [f"### {decision['role']}", '', decision.get('rationale', decision.get('observation', ''))]
        if decision.get('recommendation'):
            lines.append(decision['recommendation'])
        lines += ['', 'Evidence IDs '+', '.join(decision.get('evidence_ids', [])), '']
    lines += ['## Execution statistics and scope', '',
              f'LLM requests {state.llm_calls}, simulator calls {state.native_calls}, workflow tool calls {state.tool_calls}.',
              f"Distinct verified topologies {len({c['topology_signature'] for c in state.candidates if c['status']=='passed'})}. Search target {state.basis.budget.desired_verified_topologies}.",
              'Simulator calls include rigorous columns and stage fugacity probes. Units can be reused when inputs and source evidence hashes match. Reuse is recorded in events.jsonl.',
              f'Implementation hash {state.implementation_sha256}, source integrity during the run {state.source_integrity_passed}.',
              'The initial task has an empty flowsheet. SepMind proposes connections and parameters. The graph, simulator requests, results, and independent review are saved.',
              'The search is bounded by the registered unit library. Complex extraction, recycle, reaction, membrane, and adsorption flowsheets require suitable unit models and verification methods.',
              'Review experimental properties, dynamic operability, and equipment qualification separately from numerical closure.', '']
    usage = [event['usage'] for event in state.provider_events if isinstance(event.get('usage'), dict)]
    recorded_tokens = [item['total_tokens'] for item in usage if isinstance(item.get('total_tokens'), int)]
    lines += [f'Recorded tokens {sum(recorded_tokens)}, responses with complete token counts {len(recorded_tokens)}, LLM requests {state.llm_calls}.',
              'Missing token usage is left blank. See events.jsonl for call details.', '']
    lines += [question+'\n' for question in state.questions]
    if state.graph is not None:
        lines += ['## Flowsheet', '', '![Generated flowsheet](flowsheet.svg)', '', '```mermaid', render_mermaid(state), '```', '']
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
