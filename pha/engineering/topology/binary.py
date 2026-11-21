"""Original binary requirements with freely proposed acyclic column graphs."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import numpy as np
from scipy.interpolate import PchipInterpolator
from ..schemas import Contract, DesignBasis
from ..design.binary import material_balance, minimum_reflux, stages
from ..design.enthalpy_seed import coupled_initial_profile
from ..tools.atomic_recovery import save
from separation.tools.dwsim import BinaryVLERequest
from .binary_contracts import (BinaryTopologyBasis, BinaryTopologyState, BinaryGraph,
    BinaryProposal, BinaryGraphColumnRequest, BinarySparseColumnRequest, BinaryStageProbeRequest,
    BinaryTopologyBackend, BINARY_IDENTITIES)
from .executor import TopologyRuntime
from .orchestrator import TopologySynthesisOrchestrator
from .tools import TopologyToolRegistry
from .skills import ROOT


CASE_FOLDERS = {'D01': 'case-1a', 'D02': 'case-1b', 'D03': 'case-2', 'D04': 'case-3'}
CASE_MODELS = {'D01': "Raoult's Law", 'D02': "Raoult's Law", 'D03': 'NRTL', 'D04': 'NRTL'}


def binary_case_basis(case_id):
    source = ROOT/'case/curated'/CASE_FOLDERS[case_id]/'agent_input.json'
    original = json.loads(source.read_text(encoding='utf8'))
    normalized = {key: original[key] for key in ['components', 'feed', 'target', 'source_ids', 'assumptions']}
    names = [next(name for name, cas in BINARY_IDENTITIES.items() if cas == component['canonical_id'])
             for component in normalized['components']]
    target = normalized['target']
    products = [dict(product_id='P_light', component=names[0],
        minimum_mole_fraction=target['distillate_mole_fraction'],
        minimum_recovery=target.get('key_component_recovery', 0.))]
    products.append(dict(product_id='P_heavy', component=names[1], minimum_recovery=0.,
        minimum_mole_fraction=1-target['bottoms_mole_fraction'] if target.get('bottoms_mole_fraction') is not None else 0.))
    return BinaryTopologyBasis(design_id=case_id+'-autonomous-topology', components=names,
        feed_mole_fractions=normalized['feed']['composition'],
        feed_flow_mol_s=normalized['feed']['flow']/3.6,
        pressure_Pa=normalized['feed']['pressure_kPa']*1000,
        feed_state='saturated_liquid', property_package=CASE_MODELS[case_id],
        ideality_assumption_source='Original case property method retained. Native DWSIM9.0.5 database model. '
            'Experimental qualification and original source units remain separate evidence.',
        products=products, original_requirements=normalized,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        budget=dict(maximum_candidates=8, maximum_columns=4, maximum_llm_calls=22,
            maximum_native_calls=32, native_timeout_s=120, run_timeout_s=1800,
            desired_verified_topologies=1))


class BinaryToolInput(Contract):
    basis: BinaryTopologyBasis


class NativeEquilibrium:
    def __init__(self, points):
        self.curve = PchipInterpolator([0., *[p['x'][0] for p in points], 1.],
                                      [0., *[p['y'][0] for p in points], 1.], extrapolate=False)

    def point(self, x, pressure):
        y = float(self.curve(x))
        return {'x': [x, 1-x], 'y': [y, 1-y]}


class BinaryRuntime(TopologyRuntime):
    column_request_class = BinaryGraphColumnRequest
    probe_request_class = BinaryStageProbeRequest

    def sample_phase(self):
        basis = self.state.basis
        original = DesignBasis.model_validate(basis.original_requirements)
        self.balance = material_balance(original)
        xs = set(map(float, np.linspace(1e-6, 1-1e-6, 201)))
        xs.update([self.balance['xB'], self.balance['xD'], self.balance['zF']])
        xs.update(map(float, np.geomspace(1e-6, .05, 41)))
        request = BinaryVLERequest(tuple(basis.components), basis.property_package,
            basis.pressure_Pa, tuple(sorted(xs)), include_enthalpies=True)
        self.phase_record = self.native_call('binary_vle', request, self.folder/'native_vle.json')
        self.equilibrium = NativeEquilibrium(self.phase_record['points'])
        result = minimum_reflux(self.equilibrium, original, self.balance)
        hypotheses = []
        for factor in [1.3, 1.6, 1.9, 2.2]:
            trial = original.model_copy(deep=True)
            trial.column.reflux_ratio = result['minimum_reflux_ratio']*factor
            trial.assumptions = sorted(set(trial.assumptions+['constant_molar_overflow']))
            try:
                screening = stages(self.equilibrium, trial, self.balance, result)
                hypothesis = {key: screening[key] for key in ['reflux_ratio',
                    'theoretical_stages_rounded_up', 'feed_stage_from_top']}
                coupled = coupled_initial_profile(self.phase_record['points'], self.balance,
                    trial.column.reflux_ratio, screening['theoretical_stages_rounded_up'],
                    screening['feed_stage_from_top'])
                hypothesis['native_enthalpy_initializer_status_at_reference_draw'] = coupled['status']
                hypotheses.append(hypothesis)
            except ValueError as exc:
                hypotheses.append({'reflux_ratio': trial.column.reflux_ratio, 'screen_failure': str(exc)})
        return dict(native_evidence_id=self.phase_record['evidence_id'],
            minimum_reflux=result, reference_product_flow_mol_s=self.balance['D_kmol_h']/3.6,
            computed_single_unit_screening_hypotheses=hypotheses,
            interpretation='Necessary phase/CMO screening only. Flow reference is an algebraic target-boundary split, a design hypothesis for the Agent.',
            initialization_options=['native', 'native_cmo', 'native_enthalpy'])

    def prepare_request(self, request, node, upstream, folder):
        request = replace(request, solver_tolerance=node.solver_tolerance)
        if node.numerical_solver == 'sparse_trust_region':
            from dataclasses import asdict
            request = BinarySparseColumnRequest(**asdict(request))
        if node.initialization == 'native':
            return request
        if upstream is not None:
            raise ValueError('INITIALIZATION_SCOPE: sampled initializer describes the frozen external feed; select native for downstream columns')
        original = DesignBasis.model_validate(self.state.basis.original_requirements)
        balance = dict(self.balance)
        balance.update(D_kmol_h=request.distillate_flow_mol_s*3.6,
            B_kmol_h=(request.feed_molar_flow_mol_s-request.distillate_flow_mol_s)*3.6)
        balance['xB'] = (balance['F_kmol_h']*balance['zF']-balance['D_kmol_h']*balance['xD'])/balance['B_kmol_h']
        if not 0 < balance['xB'] < balance['zF']:
            raise ValueError('INITIALIZATION_SCOPE: target-boundary split leaves no positive bottoms initial guess; revise draw or select native initialization')
        if node.initialization == 'native_enthalpy':
            guess = coupled_initial_profile(self.phase_record['points'], balance, request.reflux_ratio,
                request.equilibrium_stages, request.feed_stage)
            save(folder/(node.column_id+'.initializer.json'), guess)
            if guess['status'] != 'initial_guess':
                raise ValueError('INITIALIZATION_FAILED: '+str(guess.get('reason', guess['status'])))
            profile = guess['profile']
        else:
            original.column.reflux_ratio = request.reflux_ratio
            original.assumptions = sorted(set(original.assumptions+['constant_molar_overflow']))
            minimum = minimum_reflux(self.equilibrium, original, balance)
            screen = stages(self.equilibrium, original, balance, minimum)
            old_n, old_feed = screen['theoretical_stages_rounded_up'], screen['feed_stage_from_top']
            source_x = [balance['xD']]+[row['x'] for row in screen['steps'][:-1]]+[balance['xB']]
            source_x = np.clip(source_x, balance['xB'], balance['xD'])
            n, feed = request.equilibrium_stages, request.feed_stage
            coordinates = [i*old_feed/feed if i <= feed else old_feed+(i-feed)*(old_n-old_feed)/(n-feed) for i in range(n+1)]
            xi = np.interp(coordinates, list(range(old_n+1)), source_x)
            temperature = PchipInterpolator([p['x'][0] for p in self.phase_record['points']],
                [p['temperature_k'] for p in self.phase_record['points']], extrapolate=False)
            f, d, b = [balance[key]/3.6 for key in ['F_kmol_h', 'D_kmol_h', 'B_kmol_h']]
            profile = [dict(temperature_K=float(temperature(x)),
                liquid_flow_mol_s=b if i == n else request.reflux_ratio*d+(f if i >= feed else 0.),
                vapor_flow_mol_s=0. if i == 0 else (request.reflux_ratio+1)*d,
                liquid_light_fraction=float(x), vapor_light_fraction=balance['xD'] if i == 0 else self.equilibrium.point(float(x), 0)['y'][0])
                for i, x in enumerate(xi)]
            save(folder/(node.column_id+'.initializer.json'), {'estimates_only': True,
                'source_evidence_id': self.phase_record['evidence_id'], 'profile': profile})
        if node.numerical_solver == 'sparse_trust_region':
            profile = [{key: row[key] for key in ['temperature_K', 'liquid_flow_mol_s', 'vapor_flow_mol_s']} |
                {'liquid_mole_fractions': [row['liquid_light_fraction'], 1-row['liquid_light_fraction']],
                 'vapor_mole_fractions': [row['vapor_light_fraction'], 1-row['vapor_light_fraction']]} for row in profile]
        return replace(request, initial_profile=profile,
            initial_estimate_source_evidence_id=self.phase_record['evidence_id'])


class BinaryToolRegistry(TopologyToolRegistry):
    input_contract = BinaryToolInput
    component_identities = BINARY_IDENTITIES
    calculation_assumptions = ['frozen_original_binary_property_model', 'zero_column_pressure_drop']
    TOOLS = {name: (gate, BinaryToolInput) for name, (gate, contract) in TopologyToolRegistry.TOOLS.items()}

    def execute(self, name, state, gate, arguments):
        result = super().execute(name, state, gate, arguments)
        if name == 'admit_topology_task' and result.status == 'success':
            try:
                result.data['phase_screen'] = self.runtime.sample_phase()
            except (ValueError, RuntimeError, TimeoutError) as exc:
                result.status = 'failed'
                result.validation = {'passed': False}
                result.diagnostics = {'error': str(exc)}
        return result


class BinaryTopologyOrchestrator(TopologySynthesisOrchestrator):
    basis_contract = BinaryTopologyBasis
    state_contract = BinaryTopologyState
    runtime_class = BinaryRuntime
    registry_class = BinaryToolRegistry
    proposal_contract = BinaryProposal
    graph_contract = BinaryGraph
    excluded_source_files = ('hybrid_autonomous.py',)
    extra_source_files = ('pha/engineering/design/binary.py', 'pha/engineering/design/enthalpy_seed.py',
        'pha/engineering/validation/native_sparse.py', 'pha/engineering/validation/balanced_mesh.py',
        'pha/engineering/validation/initialization.py')
    thermodynamic_gate_reason = 'Frozen original binary property method and native phase evidence admitted for conditional numerical evaluation'

    def __init__(self, basis, backend, prior_evidence=None, **kwargs):
        self.prior_evidence = prior_evidence or []
        self.allow_initial_counterevidence = bool(self.prior_evidence)
        kwargs.setdefault('native_backend', BinaryTopologyBackend())
        super().__init__(basis, backend, **kwargs)
        save(self.folder/'prior_evidence.json', self.prior_evidence)

    def context(self):
        context = super().context()
        context['computed_phase_screen'] = self.state.artifacts['admit_topology_task'].data.get('phase_screen')
        if context['computed_phase_screen']:
            context['available_evidence_ids'].append(context['computed_phase_screen']['native_evidence_id'])
        context['scope_note'] = ('This is an original binary industrial case. Choose column count and routes freely. '
            'The property model, feed and product bounds are frozen. Zero purity/recovery minima mean unspecified bounds. '
            'Select initialization=native, native_cmo or native_enthalpy for each column. Sampled native phase/enthalpy data '
            'are available for the external-feed column. Initializers produce numerical guesses only. '
            'Use computed inventory bounds and reference target split to choose draw fractions accurately. '
            'Solver tolerance is a numerical setting between 1e-10 and 1e-7. The independent balance '
            'acceptance remains 1e-7 and phase residual acceptance remains 1e-3. '
            'Initializer failure applies to the exact N/feed/R/draw combination that failed. '
            'An additional registered numerical_solver=sparse_trust_region solves the original native '
            'DWSIM MESH residuals through the existing trusted numerical bridge. It is available with '
            'cold native initialization or native CMO/enthalpy guesses. Acceptance thresholds stay fixed. '
            'The phase-screen tool reports which newly computed N/feed/R combinations admit positive '
            'native_enthalpy starting guesses at its exact algebraic reference draw. They require MESH verification. '
            'No accepted original-case column count, stage count, reflux, feed location or historical solution is supplied.')
        context['prior_computational_failures'] = self.prior_evidence
        context['available_evidence_ids'].extend(item['evidence_id'] for item in self.prior_evidence)
        return context
