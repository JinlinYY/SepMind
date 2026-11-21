"""Graph conservation and connectivity checks independent of an LLM proposal."""
import hashlib
import json
from collections import Counter
from .schemas import FlowsheetGraph, TopologyDesignBasis


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_graph(graph: FlowsheetGraph, basis: TopologyDesignBasis):
    columns = {column.column_id: column for column in graph.columns}
    if len(columns) != len(graph.columns) or len(columns) > basis.budget.maximum_columns:
        raise ValueError('TOPOLOGY_COLUMN_LIMIT: distinct columns within the declared bound are required')
    outlets = {product.product_id: product for product in graph.products}
    required = {target.product_id for target in basis.products}
    extras = set(outlets)-required
    if len(outlets) != len(graph.products) or not required.issubset(outlets) or any(not name.startswith('waste_') for name in extras):
        raise ValueError('TOPOLOGY_PRODUCTS: map every frozen product and identify additional waste outlets explicitly')
    streams = {'feed'} | {f'{name}.{port}' for name in columns for port in ['distillate', 'bottoms']}
    consumers = Counter(node.input_stream for node in [*graph.columns, *graph.products])
    if set(consumers) != streams or any(n != 1 for n in consumers.values()):
        raise ValueError('TOPOLOGY_PORTS: every feed and outlet needs exactly one physical consumer')
    order = []
    available = {'feed'}
    remaining = dict(columns)
    while remaining:
        ready = sorted(name for name, node in remaining.items() if node.input_stream in available)
        if not ready:
            raise ValueError('TOPOLOGY_CYCLE: a connected acyclic graph is required by this unit library')
        for name in ready:
            order.append(name)
            available.update([name+'.distillate', name+'.bottoms'])
            remaining.pop(name)
    by_stream = {node.input_stream: node for node in [*graph.columns, *graph.products]}

    def structure(stream):
        node = by_stream[stream]
        if hasattr(node, 'product_id'):
            return ['product', node.product_id]
        return ['column', structure(node.column_id+'.distillate'), structure(node.column_id+'.bottoms')]

    def design(stream):
        node = by_stream[stream]
        if hasattr(node, 'product_id'):
            return ['product', node.product_id]
        settings = node.model_dump(exclude={'column_id', 'input_stream'})
        return ['column', settings, design(node.column_id+'.distillate'), design(node.column_id+'.bottoms')]

    return {'topological_order': order, 'topology_signature': digest(structure('feed')),
            'design_signature': digest(design('feed')), 'column_count': len(columns),
            'all_ports_accounted_for': True, 'all_frozen_products_mapped': True,
            'generated_connections': [[node.input_stream, getattr(node, 'column_id', None) or node.product_id]
                                      for node in [*graph.columns, *graph.products]]}


def screen_product_flow_bounds(graph, basis):
    """Necessary inventory inequalities, independent of model or column efficiency."""
    structure = validate_graph(graph, basis)
    flows = {'feed': basis.feed_flow_mol_s}
    for name in structure['topological_order']:
        node = next(column for column in graph.columns if column.column_id == name)
        inlet = flows[node.input_stream]
        flows[name+'.distillate'] = inlet*node.distillate_fraction
        flows[name+'.bottoms'] = inlet*(1-node.distillate_fraction)
    outlets = {product.product_id: product for product in graph.products}
    bounds = []
    demand = {component: 0. for component in basis.components}
    for target in basis.products:
        available = basis.feed_flow_mol_s*basis.feed_mole_fractions[basis.components.index(target.component)]
        proposed = flows[outlets[target.product_id].input_stream]
        minimum = available*target.minimum_recovery
        maximum = available/target.minimum_mole_fraction if target.minimum_mole_fraction > 0 else basis.feed_flow_mol_s
        demand[target.component] += proposed*target.minimum_mole_fraction
        bounds.append({'product_id': target.product_id, 'component': target.component,
                       'proposed_flow_mol_s': proposed, 'necessary_minimum_flow_mol_s': minimum,
                       'necessary_maximum_flow_mol_s': maximum,
                       'inventory_purity_upper_bound': min(1., available/proposed),
                       'passed': minimum <= proposed <= maximum})
    allocation = [{'component': component, 'minimum_demand_mol_s': demand[component],
                   'available_mol_s': basis.feed_flow_mol_s*basis.feed_mole_fractions[index],
                   'passed': demand[component] <= basis.feed_flow_mol_s*basis.feed_mole_fractions[index]+1e-12}
                  for index, component in enumerate(basis.components)]
    return {'passed': all(row['passed'] for row in bounds+allocation), 'product_necessary_bounds': bounds,
            'component_allocation_bounds': allocation, 'stream_flow_hypotheses_mol_s': flows,
            'scope': 'Necessary conditions for this graph and its draw hypotheses; passing still requires native calculation'}
