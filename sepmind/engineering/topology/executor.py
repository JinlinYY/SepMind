"""Compile graph dependencies into typed native calls with bounded reuse."""
import hashlib
import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from sepmind.simulation.multicomponent import MultiColumnRequest, IdealStageProbeRequest
from ..tools.atomic_recovery import save
from .graph import digest, validate_graph
from .review import review_unit, review_process


class TopologyBudgetExceeded(RuntimeError):
    pass


class TopologyRuntime:
    column_request_class = MultiColumnRequest
    probe_request_class = IdealStageProbeRequest

    def __init__(self, state, folder, backend, emit, cache=None, stop_event=None):
        self.state, self.folder, self.backend, self.emit = state, Path(folder), backend, emit
        self.cache = cache if cache is not None else {}
        self.started = time.monotonic()
        self.basis_hash = digest(state.basis.model_dump())
        self.stop_event = stop_event

    def check(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise TopologyBudgetExceeded('STOP_REQUESTED')
        if digest(self.state.basis.model_dump()) != self.basis_hash:
            raise ValueError('IMMUTABLE_REQUIREMENTS: original design inputs changed')
        if time.monotonic()-self.started >= self.state.basis.budget.run_timeout_s:
            raise TopologyBudgetExceeded('RUN_TIME_BUDGET')

    def native_call(self, method, request, path):
        self.check()
        if self.state.native_calls >= self.state.basis.budget.maximum_native_calls:
            raise TopologyBudgetExceeded('NATIVE_CALL_BUDGET')
        self.state.native_calls += 1
        remaining = self.state.basis.budget.run_timeout_s-(time.monotonic()-self.started)
        self.backend.timeout_s = min(self.state.basis.budget.native_timeout_s, remaining)
        self.emit('native_start', method=method, request=asdict(request) if is_dataclass(request) else request.model_dump(),
                  native_call=self.state.native_calls)
        start = time.monotonic()
        try:
            record = getattr(self.backend, method)(request)
            save(path, record)
            self.emit('native_end', method=method, status='passed', duration_s=time.monotonic()-start,
                      evidence_id=record['evidence_id'], record_file=str(path))
            return record
        except Exception as exc:
            save(path.with_suffix('.failure.json'), {
                'status': 'failed', 'method': method, 'native_call': self.state.native_calls,
                'request': asdict(request) if is_dataclass(request) else request.model_dump(),
                'error_type': type(exc).__name__, 'error': str(exc),
                'duration_s': time.monotonic()-start,
            })
            self.emit('native_end', method=method, status='failed', duration_s=time.monotonic()-start,
                      error=type(exc).__name__+': '+str(exc)[:1500])
            raise

    def execute(self, graph, candidate_id):
        structure = validate_graph(graph, self.state.basis)
        basis = self.state.basis
        folder = self.folder/candidate_id
        folder.mkdir(parents=True, exist_ok=False)
        save(folder/'graph.json', graph.model_dump())
        streams = {}
        units = []
        for name in structure['topological_order']:
            self.check()
            node = next(column for column in graph.columns if column.column_id == name)
            upstream = streams.get(node.input_stream)
            flow = upstream['flow_mol_s'] if upstream else basis.feed_flow_mol_s
            fractions = upstream['mole_fractions'] if upstream else basis.feed_mole_fractions
            request = self.column_request_class(
                components=tuple(basis.components), feed_mole_fractions=tuple(fractions),
                property_package=basis.property_package,
                pressure_pa=basis.pressure_Pa, feed_molar_flow_mol_s=flow,
                distillate_flow_mol_s=flow*node.distillate_fraction,
                reflux_ratio=node.reflux_ratio, equilibrium_stages=node.equilibrium_stages,
                feed_stage=node.feed_stage, ideality_assumption_source=basis.ideality_assumption_source,
                feed_specific_enthalpy_kJ_kg=upstream['specific_enthalpy_kJ_kg'] if upstream else None,
                solver_preference=node.solver_preference, solver_tolerance=1e-9,
                solver_iteration_limit=500, strict_flash_tolerances=True,
                save_path=str((folder/(name+'.dwxmz')).resolve()))
            request = self.prepare_request(request, node, upstream, folder)
            payload = json.loads(json.dumps(asdict(request)))
            save(folder/(name+'.request.json'), payload)
            signature = digest({key: value for key, value in payload.items() if key != 'save_path'})
            cached = self.cache.get(signature)
            if cached:
                for key in ['native_path', 'probe_path']:
                    path = Path(cached[key])
                    if hashlib.sha256(path.read_bytes()).hexdigest() != cached[key+'_sha256']:
                        raise ValueError('CACHE_EVIDENCE_CHANGED: retained native evidence was modified')
                native, probe = [json.loads(Path(cached[key]).read_text(encoding='utf8')) for key in ['native_path', 'probe_path']]
                native_path, probe_path = Path(cached['native_path']), Path(cached['probe_path'])
                self.emit('unit_reused', column_id=name, request_signature=signature,
                          evidence_id=native['evidence_id'], source_record=str(native_path), native_calls_avoided=2)
            else:
                native_path, probe_path = folder/(name+'.column.json'), folder/(name+'.phase_probe.json')
                native = self.native_call('multicomponent_column', request, native_path)
                profiles = native['outputs']['stage_profiles'][1:]
                probe_request = self.probe_request_class(
                    components=basis.components, ideality_assumption_source=basis.ideality_assumption_source,
                    **({'property_package': basis.property_package} if len(basis.components) == 2 else {}),
                    points=[{'point_id': str(index), **{key: stage[key] for key in [
                        'temperature_K', 'pressure_Pa', 'liquid_mole_fractions', 'vapor_mole_fractions']}}
                        for index, stage in enumerate(profiles, 1)])
                probe = self.native_call('ideal_stage_probe', probe_request, probe_path)
            reviewed = review_unit(native, probe, payload)
            save(folder/(name+'.independent_review.json'), reviewed)
            if not reviewed['passed']:
                raise ValueError('UNIT_NUMERICAL_REVIEW_FAILED: '+json.dumps(reviewed))
            if not cached:
                self.cache[signature] = {'native_path': str(native_path), 'probe_path': str(probe_path),
                    'native_path_sha256': hashlib.sha256(native_path.read_bytes()).hexdigest(),
                    'probe_path_sha256': hashlib.sha256(probe_path.read_bytes()).hexdigest()}
            streams[name+'.distillate'] = native['outputs']['distillate']
            streams[name+'.bottoms'] = native['outputs']['bottoms']
            units.append({'column_id': name, 'input_stream': node.input_stream, 'expected_request': payload,
                          'native_path': str(native_path), 'probe_path': str(probe_path),
                          'native_sha256': hashlib.sha256(native_path.read_bytes()).hexdigest(),
                          'probe_sha256': hashlib.sha256(probe_path.read_bytes()).hexdigest(),
                          'source_evidence_id': native['evidence_id'], 'reused': bool(cached)})
            save(folder/'executed_units.json', units)
            self.emit('unit_completed', column_id=name, independent_review=reviewed, reused=bool(cached))
        return {'candidate_id': candidate_id, 'units': units, 'topology': structure,
                'directory': str(folder), 'all_units_executed': True}

    def prepare_request(self, request, node, upstream, folder):
        return request

    def review(self, graph, execution):
        self.check()
        records, reviews = {}, {}
        for unit in execution['units']:
            paths = [Path(unit['native_path']), Path(unit['probe_path'])]
            for path, key in zip(paths, ['native_sha256', 'probe_sha256']):
                if hashlib.sha256(path.read_bytes()).hexdigest() != unit[key]:
                    raise ValueError('EVIDENCE_CHANGED: independent review requires unchanged native records')
            native, probe = [json.loads(path.read_text(encoding='utf8')) for path in paths]
            name = unit['column_id']
            if name in records:
                raise ValueError('DUPLICATE_EXECUTED_UNIT')
            records[name] = native
            reviews[name] = review_unit(native, probe, unit['expected_request'])
        if set(records) != {column.column_id for column in graph.columns}:
            raise ValueError('INCOMPLETE_EXECUTED_GRAPH')
        result = review_process(self.state.basis, graph, records, reviews)
        save(Path(execution['directory'])/'process_independent_review.json', result)
        return result
