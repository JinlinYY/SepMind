"""Bounded topology jobs on the existing PHA-derived FastAPI application."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field
from sepmind.engineering.schemas import Contract
from sepmind.engineering.topology.schemas import TopologyDesignBasis
from sepmind.engineering.topology.binary_contracts import BinaryTopologyBasis
from sepmind.engineering.tools.atomic_recovery import save

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT/'output/engineering/topology_runs'
QUEUE = ROOT/'output/engineering/topology_queue'
router = APIRouter(prefix='/engineering/topology', tags=['SepMind topology synthesis'])
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sepmind-topology')
_jobs = {}
_lock = threading.Lock()


class TopologyRunRequest(Contract):
    basis: TopologyDesignBasis | BinaryTopologyBasis
    provider: Literal['deepseek', 'qwen'] = 'deepseek'
    message: str = Field(default='Propose, calculate, and compare flowsheets for the specified feed and product requirements', max_length=6000)


def run_folder(identifier):
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError('Noncanonical run identity')
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail='Unknown topology run')
    return RUNS/identifier


def worker(identifier, request, stop_event):
    from sepmind.engineering.topology.orchestrator import TopologySynthesisOrchestrator, create_topology_backend
    from sepmind.engineering.topology.binary import BinaryTopologyOrchestrator
    try:
        controller = BinaryTopologyOrchestrator if isinstance(request.basis, BinaryTopologyBasis) else TopologySynthesisOrchestrator
        team = controller(request.basis, create_topology_backend(request.provider),
                                             output_dir=run_folder(identifier), stop_event=stop_event)
        team.run(request.message)
    except Exception as exc:
        folder = run_folder(identifier)
        folder.mkdir(parents=True, exist_ok=True)
        state_path = folder/'state.json'
        state = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {
            'run_id': identifier, 'basis': request.basis.model_dump(), 'llm_calls': 0, 'native_calls': 0, 'tool_calls': 0}
        state.update(status='blocked', questions=[type(exc).__name__+': '+str(exc)[:1500]])
        save(state_path, state)


@router.get('/capabilities')
async def capabilities():
    return {'implemented': True, 'scope': 'bounded acyclic ideal multicomponent distillation graphs',
            'initial_topology_required': False, 'unit_library': ['equilibrium_distillation_column'],
            'components': ['Benzene', 'Toluene', 'Ethylbenzene', 'n-Heptane', 'n-Nonane'],
            'maximum_columns': 4, 'cyclic_flowsheet_synthesis': False,
            'registered_binary_cases': ['D02', 'D03', 'D04'],
            'numerical_acceptance': ['phase_residuals', 'unit_and_global_balances', 'frozen_product_targets'],
            'experimental_property_qualification': False, 'default_provider': 'deepseek'}


@router.get('/example')
async def example(case: Literal['ternary', 'D02', 'D03', 'D04'] = 'ternary'):
    if case != 'ternary':
        from sepmind.engineering.topology.binary import binary_case_basis
        return binary_case_basis(case).model_dump()
    return json.loads((ROOT/'engineering/examples/topology_ideal_ternary.json').read_text(encoding='utf8'))


@router.post('/runs', status_code=202)
async def create_run(request: TopologyRunRequest):
    with _lock:
        active = [job for job in _jobs.values() if not job['future'].done()]
        if len(active) >= 2:
            raise HTTPException(status_code=429, detail='Topology executor queue is full')
        for old in [identifier for identifier, job in _jobs.items() if job['future'].done()]:
            _jobs.pop(old)
        identifier = str(uuid4())
        stop = threading.Event()
        metadata = {'run_id': identifier, 'basis': request.basis.model_dump(), 'status': 'ready',
                    'provider': request.provider, 'llm_calls': 0, 'native_calls': 0, 'tool_calls': 0,
                    'gates': {}, 'candidates': [], 'decisions': []}
        save(QUEUE/(identifier+'.json'), metadata)
        future = _pool.submit(worker, identifier, request, stop)
        _jobs[identifier] = {'future': future, 'stop': stop}
    return {'run_id': identifier, 'status': 'ready'}


@router.get('/runs/{identifier}')
async def state(identifier: str):
    folder = run_folder(identifier)
    path = folder/'state.json'
    if not path.exists():
        path = QUEUE/(identifier+'.json')
    if not path.exists():
        raise HTTPException(status_code=404, detail='Unknown topology run')
    return json.loads(path.read_text(encoding='utf8'))


@router.post('/runs/{identifier}/stop')
async def stop_run(identifier: str):
    run_folder(identifier)
    with _lock:
        job = _jobs.get(identifier)
        if job and not job['future'].done():
            job['stop'].set()
            if job['future'].cancel():
                path = QUEUE/(identifier+'.json')
                queued = json.loads(path.read_text(encoding='utf8'))
                queued.update(status='blocked', questions=['STOP_REQUESTED before execution'])
                save(path, queued)
            return {'stop_requested': True, 'scope': 'checked between bounded native calls'}
    raise HTTPException(status_code=409, detail='Run has already finished or belongs to a previous server process')


@router.get('/runs/{identifier}/export/{format}')
async def export(identifier: str, format: str):
    folder = run_folder(identifier)
    files = {'json': ('state.json', 'application/json'), 'md': ('report.md', 'text/markdown; charset=utf-8'),
             'svg': ('flowsheet.svg', 'image/svg+xml'), 'mmd': ('flowsheet.mmd', 'text/plain; charset=utf-8')}
    if format not in files:
        raise HTTPException(status_code=400, detail='Supported exports are json, md, svg and mmd')
    filename, media = files[format]
    path = folder/filename
    if not path.exists():
        raise HTTPException(status_code=409, detail='Requested artifact has not been generated')
    return Response(path.read_bytes(), media_type=media,
                    headers={'Content-Disposition': f'inline; filename="{identifier}.{format}"', 'X-Content-Type-Options': 'nosniff'})


def stop_topology_jobs():
    with _lock:
        for job in _jobs.values():
            if not job['future'].done():
                job['stop'].set()
