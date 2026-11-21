"""Bounded expert numerical repair using the existing, typed DWSIM adapter.

The target request is immutable. Coarse towers and relaxed cuts are initialization
experiments, never substitutes for the final design. No property gate is waived.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from pydantic import Field, model_validator

from pha.engineering.schemas import Contract
from .mixture import CandidateColumnRequest, MixtureDwsimBackend, mixture_card


class ColumnRevisionRequest(Contract):
    target: CandidateColumnRequest
    maximum_native_calls: int = Field(default=12, ge=1, le=30)
    maximum_seconds_per_call: float = Field(default=60, ge=5, le=180)
    initial_cut_step: float = Field(default=.05, gt=0, le=.1)
    minimum_cut_step: float = Field(default=.00625, gt=0, le=.05)
    initial_cut_fraction: float = Field(default=.5, gt=0, lt=1)
    seed_evidence_path: str | None = None

    @model_validator(mode='after')
    def physical_target(self):
        if self.target.numerical_homotopy_strength != 1:
            raise ValueError('Final target must use the full physical model')
        if self.minimum_cut_step > self.initial_cut_step:
            raise ValueError('Minimum step exceeds initial step')
        return self


def warm_profile(result, stages):
    """Interpolate native converged estimates, never product constraints."""
    rows = result['outputs']['stage_profiles']
    old = np.linspace(0, 1, len(rows)); new = np.linspace(0, 1, stages + 1)
    result_rows = [{} for _ in new]
    for key in ('temperature_K', 'liquid_flow_mol_s', 'vapor_flow_mol_s'):
        values = np.interp(new, old, [r[key] for r in rows])
        for row, value in zip(result_rows, values): row[key] = float(value)
    for key in ('liquid_mole_fractions', 'vapor_mole_fractions'):
        values = np.asarray([r[key] for r in rows])
        interpolated = np.asarray([np.interp(new, old, values[:, i]) for i in range(values.shape[1])]).T
        # Linear interpolation of normalized vectors preserves normalization;
        # only floating point rounding is tolerated by CandidateColumnRequest.
        for row, value in zip(result_rows, interpolated): row[key] = value.tolist()
    return result_rows


def run_column_revision(request, output_dir):
    """Execute and retain every experiment; success means target MESH only.

    After a failed cut step, halve the step. Once sufficiently small steps fail,
    increase stages from the last solved tower, then resume continuation. Stop
    on budget exhaustion, retaining the best computed state and unmet target.
    """
    request = ColumnRevisionRequest.model_validate(request)
    folder = Path(output_dir).resolve()
    root = Path(__file__).resolve().parents[2] / 'output'
    if not folder.is_relative_to(root): raise ValueError('Evidence must remain in workspace output')
    folder.mkdir(parents=True, exist_ok=False)
    frozen = request.target.model_dump()
    frozen_bytes = request.target.model_dump_json().encode()
    (folder / 'protocol.json').write_text(request.model_dump_json(indent=2), encoding='utf8')
    ledger = {'scope': 'Native column numerical repair only; not a qualified hybrid design',
              'target_sha256': hashlib.sha256(frozen_bytes).hexdigest(),
              'target_reproduced': False, 'design_admitted': False, 'attempts': []}
    backend = MixtureDwsimBackend(timeout_s=request.maximum_seconds_per_call)
    target_cut = frozen['distillate_flow_mol_s'] / frozen['feed_molar_flow_mol_s']
    step = request.initial_cut_step
    last = None; last_request = None; last_path = None
    next_stages = min(8, frozen['equilibrium_stages'])
    next_cut = min(request.initial_cut_fraction, target_cut)
    next_reflux = min(1., frozen['reflux_ratio'])
    action = 'coarse_initialization'
    if request.seed_evidence_path is not None:
        seed=Path(request.seed_evidence_path).resolve()
        if not seed.is_relative_to(root) or seed.name!='native.json':
            raise ValueError('Seed evidence must be a saved native.json in workspace output')
        native=json.loads(seed.read_text(encoding='utf8'))
        seed_request=CandidateColumnRequest.model_validate(native['request'])
        same=('property_card_id','feed_mole_fractions','feed_molar_flow_mol_s','pressure_pa','feed_temperature_K','bottom_pressure_pa')
        if any(getattr(seed_request,k)!=getattr(request.target,k) for k in same):
            raise ValueError('Seed feed/model/operating conditions differ from frozen target')
        if (not native['checks']['flowsheet_solved'] or not native['checks']['results_physical']
            or native.get('intermediate_not_physical_result',True)
            or native.get('parameter_sha256')!=mixture_card(request.target.property_card_id)[1]):
            raise ValueError('Seed must be a full-model, validated native calculation')
        next_cut=seed_request.distillate_flow_mol_s/frozen['feed_molar_flow_mol_s']
        if next_cut>target_cut or seed_request.equilibrium_stages>frozen['equilibrium_stages']:
            raise ValueError('Seed lies beyond the declared continuation target')
        last,last_request,last_path=native,seed_request,seed
        next_stages=seed_request.equilibrium_stages;next_reflux=seed_request.reflux_ratio
        next_cut=min(target_cut,next_cut+step);action='resume_from_saved_native_solution'
        ledger['seed_sha256']=hashlib.sha256(seed.read_bytes()).hexdigest()
    for index in range(request.maximum_native_calls):
        attempt_dir = folder / f'attempt-{index+1:02d}'; attempt_dir.mkdir()
        payload = dict(frozen)
        payload.update(equilibrium_stages=next_stages,
                       feed_stage=max(1, min(next_stages-1, round(frozen['feed_stage']*next_stages/frozen['equilibrium_stages']))),
                       distillate_flow_mol_s=next_cut*frozen['feed_molar_flow_mol_s'],
                       reflux_ratio=next_reflux, include_profiles=True,
                       save_path=str(attempt_dir / 'column.dwxmz'))
        if last is not None:
            payload.update(initial_profile=warm_profile(last, next_stages),
                           initial_estimate_source_evidence_id=str(last_path))
        candidate = CandidateColumnRequest.model_validate(payload)
        (attempt_dir/'request.json').write_text(candidate.model_dump_json(indent=2),encoding='utf8')
        record = {'attempt': index+1, 'action': action,
                  'predecessor_evidence': str(last_path) if last_path else None,
                  'cut': next_cut, 'stages': next_stages, 'reflux_ratio': next_reflux,
                  'target_constraints_unchanged': True, 'accepted_as_design': False}
        try:
            native = backend.candidate_column(candidate)
            if not native['checks']['flowsheet_solved'] or not native['checks']['results_physical']:
                raise ValueError('Independent native closure not passed')
            native_path = attempt_dir/'native.json'
            native_path.write_text(json.dumps(native,indent=2),encoding='utf8')
            last, last_request, last_path = native, candidate, native_path
            record.update(status='solved', checks=native['checks'], evidence=str(native_path))
            ledger['last_solved_evidence'] = str(native_path)
            reached = (abs(next_cut-target_cut)<1e-12 and next_stages==frozen['equilibrium_stages']
                       and abs(next_reflux-frozen['reflux_ratio'])<1e-12)
            if reached:
                ledger['target_reproduced'] = True
            elif next_cut < target_cut-1e-12:
                next_cut = min(target_cut, next_cut+step); action='advance_product_cut'
            elif next_reflux != frozen['reflux_ratio']:
                next_reflux = frozen['reflux_ratio']; action='restore_target_reflux'
            else:
                next_stages = min(frozen['equilibrium_stages'], next_stages+4); action='restore_target_stages'
        except (RuntimeError, ValueError, TimeoutError) as exc:
            record.update(status='failed', failure_class='numerical_nonconvergence_or_validation', error=str(exc))
            (attempt_dir/'failure.json').write_text(json.dumps(record,indent=2),encoding='utf8')
            if last_request is None:
                next_stages=min(frozen['equilibrium_stages'],next_stages+4)
                action='retry_initialization_with_more_stages'
            elif (next_cut-last_request.distillate_flow_mol_s/frozen['feed_molar_flow_mol_s'])/2>=request.minimum_cut_step:
                step=min(step/2,(next_cut-last_request.distillate_flow_mol_s/frozen['feed_molar_flow_mol_s'])/2)
                next_cut=min(target_cut,last_request.distillate_flow_mol_s/frozen['feed_molar_flow_mol_s']+step)
                next_stages=last_request.equilibrium_stages
                next_reflux=last_request.reflux_ratio;action='reduce_continuation_step'
            else:
                next_stages=min(frozen['equilibrium_stages'],last_request.equilibrium_stages+4)
                next_cut=last_request.distillate_flow_mol_s/frozen['feed_molar_flow_mol_s']
                next_reflux=last_request.reflux_ratio;action='increase_stages_at_last_solved_cut'
                # A cut can exceed the separation capability at the current
                # reflux. More stages alone cannot cure a reflux pinch.
                if last_request.reflux_ratio < frozen['reflux_ratio']:
                    next_stages=last_request.equilibrium_stages
                    next_reflux=min(frozen['reflux_ratio'],last_request.reflux_ratio*1.5)
                    action='increase_reflux_at_last_solved_cut'
        ledger['attempts'].append(record)
        ledger['native_call_count']=index+1
        assert request.target.model_dump_json().encode()==frozen_bytes
        (folder/'revision.json').write_text(json.dumps(ledger,indent=2),encoding='utf8')
        print(json.dumps({k:record[k] for k in ('attempt','action','status','cut','stages')}),flush=True)
        if ledger['target_reproduced']: break
    return ledger
