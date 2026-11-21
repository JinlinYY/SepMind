"""Independent arithmetic over retained native streams and phase probes."""
import math
from .graph import validate_graph


def component_flows(port, count):
    fractions = port['mole_fractions']
    values = [port['flow_mol_s'], port['mass_flow_kg_s'], port['specific_enthalpy_kJ_kg'], port['temperature_K'], *fractions]
    if len(fractions) != count or any(not math.isfinite(value) for value in values):
        raise ValueError('NUMERICAL_OUTPUT: incomplete finite port data')
    if min(fractions) < 0 or max(fractions) > 1 or abs(sum(fractions)-1) > 1e-7:
        raise ValueError('NUMERICAL_OUTPUT: invalid composition')
    if min(port['flow_mol_s'], port['mass_flow_kg_s']) <= 0 or not 273.15 <= port['temperature_K'] <= 600:
        raise ValueError('NUMERICAL_OUTPUT: port outside the declared model domain')
    return [port['flow_mol_s']*value for value in fractions]


def heat(port):
    return port['mass_flow_kg_s']*port['specific_enthalpy_kJ_kg']


def relative_difference(left, right, scale):
    return abs(left-right)/max(abs(scale), 1e-12)


def review_unit(record, probe, expected):
    if record.get('status') != 'ok' or probe.get('status') != 'ok':
        raise ValueError('NATIVE_RECORD: successful native records required')
    if any(not str(value.get('version', '')).startswith('DWSIM version 9.0.5') for value in [record, probe]):
        raise ValueError('NATIVE_VERSION: DWSIM 9.0.5 required')
    request = record['request']
    for key in ['components', 'property_package', 'equilibrium_stages', 'feed_stage', 'ideality_assumption_source', 'solver_preference', 'solver_tolerance', 'solver_iteration_limit', 'strict_flash_tolerances']:
        if request[key] != expected[key]:
            raise ValueError('FROZEN_UNIT_INPUT: ' + key)
    for key in ['pressure_pa', 'feed_molar_flow_mol_s', 'distillate_flow_mol_s', 'reflux_ratio']:
        if relative_difference(request[key], expected[key], expected[key]) > 1e-10:
            raise ValueError('FROZEN_UNIT_INPUT: ' + key)
    for key in ['feed_temperature_K', 'feed_specific_enthalpy_kJ_kg']:
        if request.get(key) != expected.get(key):
            raise ValueError('FROZEN_UNIT_INPUT: feed thermodynamic specification differs')
    if request['feed_mole_fractions'] != expected['feed_mole_fractions']:
        raise ValueError('FROZEN_UNIT_INPUT: component fractions differ')
    if list(probe['request']['components']) != list(request['components']):
        raise ValueError('PHASE_PROBE_ORDER: component identities differ')
    if probe['request']['ideality_assumption_source'] != expected['ideality_assumption_source']:
        raise ValueError('PHASE_PROBE_MODEL: assumption provenance differs')
    if probe['request'].get('property_package', "Raoult's Law") != expected['property_package']:
        raise ValueError('PHASE_PROBE_MODEL: native property package differs')
    outputs = record['outputs']
    feed, distillate, bottoms = [outputs[key] for key in ['feed', 'distillate', 'bottoms']]
    count = len(request['components'])
    vectors = [component_flows(port, count) for port in [feed, distillate, bottoms]]
    flow = request['feed_molar_flow_mol_s']
    feed_error = max(relative_difference(vectors[0][i], flow*request['feed_mole_fractions'][i], flow) for i in range(count))
    if request.get('feed_specific_enthalpy_kJ_kg') is not None:
        feed_error = max(feed_error, relative_difference(feed['specific_enthalpy_kJ_kg'], request['feed_specific_enthalpy_kJ_kg'], max(abs(request['feed_specific_enthalpy_kJ_kg']), 1)))
    component_error = max(abs(vectors[0][i]-vectors[1][i]-vectors[2][i])/flow for i in range(count))
    mass_error = relative_difference(feed['mass_flow_kg_s'], distillate['mass_flow_kg_s']+bottoms['mass_flow_kg_s'], feed['mass_flow_kg_s'])
    qc, qr = outputs['condenser_duty_kW'], outputs['reboiler_duty_kW']
    if not all(math.isfinite(value) and value >= 0 for value in [qc, qr]):
        raise ValueError('ENERGY_OUTPUT: nonnegative finite column duties required')
    energy_error = abs(heat(feed)+qr-heat(distillate)-heat(bottoms)-qc)/max(qc, qr, 1.)
    draw_error = relative_difference(distillate['flow_mol_s'], request['distillate_flow_mol_s'], flow)
    profiles = outputs['stage_profiles']
    if len(profiles) != request['equilibrium_stages']+1 or len(probe['points']) != len(profiles)-1:
        raise ValueError('STAGE_COVERAGE: every equilibrium stage must be reviewed')
    if record['mapping']['DWSIM_feed_stage_zero_based'] != request['feed_stage']:
        raise ValueError('STAGE_MAPPING: native feed location differs')
    reflux_error = relative_difference(profiles[0]['liquid_flow_mol_s']/distillate['flow_mol_s'], request['reflux_ratio'], request['reflux_ratio'])
    residuals = []
    for index, (stage, phase) in enumerate(zip(profiles[1:], probe['points']), 1):
        point = probe['request']['points'][index-1]
        if point['point_id'] != str(index) or phase['point_id'] != str(index):
            raise ValueError('PHASE_PROBE_ID: stage evidence differs')
        for field in ['temperature_K', 'pressure_Pa', 'liquid_mole_fractions', 'vapor_mole_fractions']:
            if point[field] != stage[field]:
                raise ValueError('PHASE_PROBE_INPUT: probe was not computed at the returned stage')
        phi_l, phi_v = phase['liquid_fugacity_coefficients'], phase['vapor_fugacity_coefficients']
        if len(phi_l) != count or len(phi_v) != count or any(not math.isfinite(v) or v <= 0 for v in phi_l+phi_v):
            raise ValueError('PHASE_PROBE_OUTPUT: incomplete positive coefficients required')
        x, y = stage['liquid_mole_fractions'], stage['vapor_mole_fractions']
        if len(x) != count or len(y) != count or abs(sum(x)-1) > 1e-7 or abs(sum(y)-1) > 1e-7:
            raise ValueError('STAGE_COMPOSITION: phase fractions do not close')
        if not 273.15 <= stage['temperature_K'] <= 600 or relative_difference(stage['pressure_Pa'], expected['pressure_pa'], expected['pressure_pa']) > 1e-8:
            raise ValueError('STAGE_DOMAIN: temperature or pressure differs from the declared slice')
        for i in range(count):
            if x[i] < 0 or y[i] < 0:
                raise ValueError('STAGE_COMPOSITION: negative component')
            if max(x[i], y[i]) > 1e-10:
                if min(x[i], y[i]) <= 0:
                    raise ValueError('PHASE_EQUILIBRIUM: active component missing from one phase')
                residuals.append(abs(math.log(x[i]*phi_l[i]/(y[i]*phi_v[i]))))
    phase_error = max(residuals, default=float('inf'))
    flags = record.get('checks', {})
    passed = (max(feed_error, component_error, mass_error, energy_error, draw_error, reflux_error) <= 1e-7
              and phase_error <= 1e-3 and flags.get('flowsheet_solved') is True
              and flags.get('product_compositions_imposed') is False)
    return {'passed': passed, 'component_residual': component_error, 'mass_residual': mass_error,
            'energy_residual': energy_error, 'feed_residual': feed_error, 'draw_residual': draw_error,
            'reflux_residual': reflux_error, 'maximum_log_fugacity_residual': phase_error,
            'phase_trace_cutoff': 1e-10, 'phase_probe_evidence_id': probe['evidence_id'],
            'scope': 'Independent residual arithmetic with the declared native property model; experimental mixture validity remains separate',
            'property_package': expected['property_package']}


def review_process(basis, graph, records, unit_reviews):
    structure = validate_graph(graph, basis)
    streams = {}
    external_feed = None
    connection_errors = []
    duties = {'condenser_kW': 0., 'reboiler_kW': 0.}
    for name in structure['topological_order']:
        node = next(column for column in graph.columns if column.column_id == name)
        record = records[name]
        outputs = record['outputs']
        incoming = outputs['feed']
        count = len(basis.components)
        request = record['request']
        expected_flow = basis.feed_flow_mol_s if node.input_stream == 'feed' else streams[node.input_stream]['flow_mol_s']
        if list(request['components']) != basis.components or request['property_package'] != basis.property_package or request['ideality_assumption_source'] != basis.ideality_assumption_source:
            raise ValueError('FROZEN_PROCESS_MODEL: unit differs from the original basis')
        if request['equilibrium_stages'] != node.equilibrium_stages or request['feed_stage'] != node.feed_stage or request['reflux_ratio'] != node.reflux_ratio or request['solver_preference'] != node.solver_preference:
            raise ValueError('FROZEN_GRAPH_SETTINGS: executed column differs from the proposed graph')
        if relative_difference(request['pressure_pa'], basis.pressure_Pa, basis.pressure_Pa) > 1e-10 or relative_difference(request['distillate_flow_mol_s'], expected_flow*node.distillate_fraction, expected_flow) > 1e-10:
            raise ValueError('FROZEN_GRAPH_SETTINGS: pressure or draw differs')
        if node.input_stream == 'feed':
            external_feed = incoming
            expected = [basis.feed_flow_mol_s*x for x in basis.feed_mole_fractions]
            actual = component_flows(incoming, count)
            connection_errors.append(max(abs(a-b) for a, b in zip(actual, expected))/basis.feed_flow_mol_s)
            if record['request'].get('feed_specific_enthalpy_kJ_kg') is not None or record['request'].get('feed_temperature_K') is not None:
                raise ValueError('FROZEN_FEED_STATE: the source feed is explicitly saturated liquid')
        else:
            upstream = streams[node.input_stream]
            left, right = component_flows(upstream, count), component_flows(incoming, count)
            connection_errors.extend([max(abs(a-b) for a, b in zip(left, right))/basis.feed_flow_mol_s,
                                      relative_difference(heat(upstream), heat(incoming), max(abs(heat(upstream)), 1.)),
                                      relative_difference(upstream['mass_flow_kg_s'], incoming['mass_flow_kg_s'], upstream['mass_flow_kg_s'])])
        streams[name+'.distillate'] = outputs['distillate']
        streams[name+'.bottoms'] = outputs['bottoms']
        duties['condenser_kW'] += outputs['condenser_duty_kW']
        duties['reboiler_kW'] += outputs['reboiler_duty_kW']
    products = {outlet.product_id: streams[outlet.input_stream] for outlet in graph.products}
    totals = [0.]*len(basis.components)
    for port in products.values():
        totals = [a+b for a, b in zip(totals, component_flows(port, len(basis.components)))]
    initial = [basis.feed_flow_mol_s*x for x in basis.feed_mole_fractions]
    component_error = max(abs(a-b) for a, b in zip(initial, totals))/basis.feed_flow_mol_s
    mass_error = relative_difference(external_feed['mass_flow_kg_s'], sum(p['mass_flow_kg_s'] for p in products.values()), external_feed['mass_flow_kg_s'])
    energy_error = abs(heat(external_feed)+duties['reboiler_kW']-sum(heat(p) for p in products.values())-duties['condenser_kW'])/max(*duties.values(), 1.)
    targets = []
    for requirement in basis.products:
        index = basis.components.index(requirement.component)
        port = products[requirement.product_id]
        purity = port['mole_fractions'][index]
        recovery = port['flow_mol_s']*purity/initial[index]
        targets.append({'product_id': requirement.product_id, 'component': requirement.component,
                        'mole_fraction': purity, 'recovery': recovery,
                        'required_mole_fraction': requirement.minimum_mole_fraction,
                        'required_recovery': requirement.minimum_recovery,
                        'purity_passed': purity >= requirement.minimum_mole_fraction,
                        'recovery_passed': requirement.minimum_recovery <= recovery <= 1+1e-7})
    closed = max(component_error, mass_error, energy_error, *connection_errors) <= 1e-7
    passed = closed and all(review['passed'] for review in unit_reviews.values()) and all(target['purity_passed'] and target['recovery_passed'] for target in targets)
    return {'passed': passed, 'numerically_closed': closed, 'targets': targets, 'duties': duties,
            'component_residual': component_error, 'mass_residual': mass_error, 'energy_residual': energy_error,
            'maximum_connection_residual': max(connection_errors), 'unit_reviews': unit_reviews,
            'products': products, 'topology': structure, 'experimental_property_qualification': False,
            'full_operability_qualification': False}
