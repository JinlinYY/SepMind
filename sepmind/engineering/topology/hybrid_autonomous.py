"""Source-target hybrid synthesis with data-only graphs and cold numerical trials.

No accepted source topology, stage array or process simulation is loaded. Unit
models and source property cards are reused as conditional research tools.
"""
import copy
import hashlib
import json
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Literal
from uuid import UUID,uuid4
import numpy as np
from pydantic import Field, model_validator
from ..agents.orchestrator import EngineeringOrchestrator
from ..schemas import Contract
from ..design.extraction import extraction_cascade
from ..design.extraction import contact
from ..design.extraction_simultaneous import extraction_simultaneous
from ..thermo.lle import NRTLModel
from ..validation.multifeed import review_multifeed_column
from ..tools.atomic_recovery import save
from sepmind.simulation.mixture import mixture_card, MixtureProbeRequest
from sepmind.simulation.multifeed import MultiFeedColumnRequest, MultiFeedDwsimBackend
from .schemas import TopologyBudget, ExpertAssessment
from .orchestrator import TopologySynthesisOrchestrator
from .executor import TopologyRuntime, TopologyBudgetExceeded
from .graph import digest
from .skills import ROOT
from .hybrid_inventory import product_draw_bounds
from .hybrid_initialization import resample_profile
from .hybrid_context import compact_context,load_native_phase_evidence
from .hybrid_revisions import HybridRevision,apply_revision,pressure_findings
from ..skills.process import ProcessSkillRegistry
from ..validation.phase_admission import near_pure_freezing_screen


class HybridBudget(TopologyBudget):
    hydraulic_pressure_sensitivity: bool=False
    trace_relative_finite_differences: bool=False
    maximum_native_calls: int = Field(default=128, ge=2, le=256)
    maximum_recycle_iterations: int=Field(default=8,ge=1,le=32)
    maximum_recorded_tokens: int | None=Field(default=None,ge=1000)
    incremental_revisions: bool=False
    project_exact_absent_species: bool=False
    canonicalize_roundoff_compositions: bool=False


class HybridBasis(Contract):
    design_id: Literal['H01', 'H02']
    components: list[str]
    fresh_flow_mol_s: float = Field(gt=0)
    fresh_mole_fractions: list[float]
    fresh_temperature_K: float
    fresh_pressure_Pa: float
    fresh_state_specification: Literal['TP']='TP'
    property_cards: list[str]
    allowed_auxiliary_feeds: list[str]
    requirements: dict
    provenance: dict
    budget: HybridBudget = Field(default_factory=lambda: HybridBudget(
        maximum_candidates=8, maximum_columns=4, maximum_llm_calls=24,
        maximum_native_calls=128, native_timeout_s=120, run_timeout_s=2700))


class HybridUnit(Contract):
    unit_id: str = Field(pattern=r'^U[1-9][0-9]?$')
    kind: Literal['column', 'extraction', 'mixer', 'makeup_mixer', 'auxiliary_feed', 'conditioner', 'pump', 'splitter', 'decanter']
    inputs: list[str] = Field(min_length=0, max_length=4)
    property_card_id: str
    temperature_K: float = Field(ge=290, le=570)
    pressure_Pa: float = Field(ge=8000, le=200000)
    bottom_pressure_Pa: float | None=Field(default=None,ge=8000,le=200000)
    stages: int | None = Field(default=None, ge=1, le=100)
    feed_stages: list[int] = Field(default_factory=list)
    reflux_ratio: float | None = Field(default=None, ge=0, le=30)
    distillate_fraction: float | None = Field(default=None, gt=0, lt=1)
    distillate_flow_mol_s: float | None=Field(default=None,gt=0)
    distillate_inventory_components: list[str]=Field(default_factory=list)
    distillate_inventory_multiplier: float | None=Field(default=None,gt=0,le=2)
    column_mode: Literal['total_condenser', 'reboiled_absorber'] = 'total_condenser'
    solver_preference: Literal['default', 'modified_bubble_point', 'simultaneous_correction'] = 'default'
    numerical_solver: Literal['native', 'sparse_trust_region'] = 'native'
    numerical_jacobian_policy: Literal['balanced_reduced','sparse_finite_difference']='balanced_reduced'
    initialization_evidence_id: str | None = None
    initialization_policy: Literal['auto','cold','equilibrium_rescale']='auto'
    extraction_solver: Literal['cascade', 'simultaneous'] = 'simultaneous'
    split_fraction: float | None = Field(default=None, gt=0, lt=1)
    carrier_component: str | None = Field(default=None, description='Hydrocarbon feed carrier identifying the raffinate phase. For the registered H01 extraction this is Methylcyclohexane, with Toluene solute and Sulfolane extracting solvent.')
    makeup_component: str | None = None
    target_component_flow_mol_s: float | None = Field(default=None, gt=0)
    efficiency: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode='after')
    def operation_contract(self):
        if self.kind=='column' and self.bottom_pressure_Pa is not None and self.bottom_pressure_Pa<self.pressure_Pa:
            raise ValueError('COLUMN_PRESSURE_PROFILE: bottom pressure cannot be lower than top pressure')
        if self.kind=='auxiliary_feed':
            if self.inputs or self.makeup_component is None or self.target_component_flow_mol_s is None:
                raise ValueError('AUXILIARY_FEED: no inlet, allowed chemical and positive fresh flow required')
        elif not self.inputs:
            raise ValueError('UNIT_INPUTS: actual inlet streams required')
        if self.kind == 'column' and (self.stages is None or self.stages < 3 or self.reflux_ratio is None or len(self.feed_stages) != len(self.inputs)):
            raise ValueError('COLUMN_INPUTS: explicit N, feed locations, R and draw fraction required')
        inventory=bool(self.distillate_inventory_components)
        if inventory!=(self.distillate_inventory_multiplier is not None):
            raise ValueError('COLUMN_DRAW: inventory components require an explicit multiplier')
        if self.kind=='column' and sum([self.distillate_fraction is not None,self.distillate_flow_mol_s is not None,inventory])!=1:
            raise ValueError('COLUMN_DRAW: choose exactly one fraction, absolute flow, or component-inventory draw rule')
        if self.kind == 'extraction' and (len(self.inputs) != 2 or self.stages is None or self.carrier_component is None):
            raise ValueError('EXTRACTION_INPUTS: two actual feeds, stage count and carrier identity required')
        if self.kind=='extraction' and self.extraction_solver=='simultaneous' and self.stages>30:
            raise ValueError('EXTRACTION_STAGE_LIMIT: simultaneous contact solver supports at most 30 stages')
        if self.kind == 'makeup_mixer' and (self.makeup_component is None or self.target_component_flow_mol_s is None):
            raise ValueError('MAKEUP_INPUTS: supply chemical identity and desired circulating component flow')
        if self.kind == 'splitter' and self.split_fraction is None:
            raise ValueError('SPLITTER_INPUTS: explicit fraction required')
        if self.kind == 'pump' and self.efficiency is None:
            raise ValueError('PUMP_INPUTS: proposed efficiency required')
        return self


class TearGuess(Contract):
    tear_id: str = Field(pattern=r'^T[1-9][0-9]?$')
    source_stream: str
    component_flows_mol_s: list[float]
    temperature_K: float = Field(ge=290, le=570)
    pressure_Pa: float = Field(ge=8000, le=200000)


class HybridGraph(Contract):
    units: list[HybridUnit] = Field(min_length=1, max_length=24)
    products: dict[str, str] = Field(description='Required keys MCH and TOL. Additional external waste outlets use waste_ prefix. Recycles are declared in tears and consumed through tear.T1, with one physical consumer per outlet.')
    constraint_streams: dict[str, str] = Field(default_factory=dict, description='H01 uses {}. H02 requires literal keys solvent_rich and solvent_recycle, each mapped to an actual U#.port stream reference. Values are stream IDs, with no formulas, descriptions or limits.')
    tears: list[TearGuess] = Field(default_factory=list, max_length=5)

    @model_validator(mode='before')
    @classmethod
    def canonical_product_names(cls, values):
        values = copy.deepcopy(values)
        if isinstance(values, dict) and isinstance(values.get('products'), dict):
            aliases = {'MCH_product': 'MCH', 'TOL_product': 'TOL'}
            products = {}
            for name, stream in values['products'].items():
                key = aliases.get(name, 'waste_'+name[:-6] if name.endswith('_waste') else name)
                if key in products:
                    raise ValueError('DUPLICATE_PRODUCT_ALIAS')
                products[key] = stream
            values['products'] = products
            tear_rows=[row if isinstance(row,dict) else row.model_dump() for row in values.get('tears',[]) or []
                if isinstance(row,dict) or hasattr(row,'model_dump')]
            source_counts=Counter(row.get('source_stream') for row in tear_rows if isinstance(row.get('source_stream'),str))
            aliases={row['source_stream']:'tear.'+row['tear_id'] for row in tear_rows
                if isinstance(row.get('source_stream'),str) and isinstance(row.get('tear_id'),str)
                and source_counts[row['source_stream']]==1}
            units=[]
            for unit in values.get('units',[]) or []:
                inputs=unit.get('inputs') if isinstance(unit,dict) else getattr(unit,'inputs',None)
                if isinstance(inputs,list):
                    inputs=[aliases.get(reference,reference) if isinstance(reference,str) else reference for reference in inputs]
                    unit={**unit,'inputs':inputs} if isinstance(unit,dict) else unit.model_copy(update={'inputs':inputs})
                units.append(unit)
            values['units']=units
        return values


class HybridProposal(Contract):
    graph: HybridGraph
    evidence_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=6000)


class HybridExpertAssessment(ExpertAssessment):
    observation: str = Field(min_length=1, max_length=6000)
    recommendation: str = Field(min_length=1, max_length=6000)


class VLEUnit(HybridUnit):
    kind: Literal['column', 'mixer', 'makeup_mixer', 'auxiliary_feed', 'conditioner', 'pump', 'splitter']


class VLEGraph(HybridGraph):
    units: list[VLEUnit] = Field(min_length=1, max_length=24)
    constraint_streams: dict[str, str] = Field(description='Required exact keys solvent_rich and solvent_recycle. Each value is an actual U#.port reference.',
        json_schema_extra={'required': ['solvent_rich', 'solvent_recycle'],
            'properties': {'solvent_rich': {'type': 'string'}, 'solvent_recycle': {'type': 'string'}}})


class VLEProposal(HybridProposal):
    graph: VLEGraph


class HybridState(Contract):
    run_id: str
    basis: HybridBasis
    status: str = 'ready'
    llm_calls: int = 0
    native_calls: int = 0
    tool_calls: int = 0
    provider_events: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    accepted_candidate_id: str | None = None
    questions: list[str] = Field(default_factory=list)


def hybrid_basis(case_id):
    if case_id == 'H01':
        cards = ['mch_toluene_sulfolane_lle_brouwer2021', 'mch_toluene_sulfolane_vle_brouwer2021']
        card, _ = mixture_card(cards[0])
        mw = np.asarray(card['molecular_weights_g_mol'])
        z = np.array([.6, .4, 0., 0.])
        flow = 100000/(z@mw)/3.6
        temperature, pressure = 293.15, 100000.
        requirements = dict(MCH_minimum_mass_fraction=.9985, TOL_minimum_mass_fraction=.9985)
        source = ROOT/'scripts/complete_case3_flowsheet.py'
    else:
        cards = ['mch_toluene_phenol_unifac_v1']
        card, _ = mixture_card(cards[0])
        flow, z, temperature, pressure = 20., [0., .5, .5], 384., 101325.
        requirements = dict(solvent_rich_MCH_maximum_mole_fraction=1e-4,
            TOL_product_phenol_maximum_mole_fraction=1e-3,
            recycle_TOL_fraction_of_fresh_TOL_maximum=1e-3)
        source = ROOT/'scripts/complete_case5_flowsheet.py'
    return HybridBasis(design_id=case_id, components=card['native_names'],
        fresh_flow_mol_s=float(flow), fresh_mole_fractions=list(z),
        fresh_temperature_K=temperature, fresh_pressure_Pa=pressure,
        property_cards=cards, allowed_auxiliary_feeds=['Sulfolane', 'Water'] if case_id == 'H01' else ['Phenol'],
        requirements=requirements,
        provenance=dict(source_file=str(source.relative_to(ROOT)),
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            scope='Only original fresh-feed conditions and acceptance bounds extracted. Source graphs, numerical profiles, N/R and accepted simulations excluded.'))


PORTS = {'column': ['distillate', 'bottoms'], 'extraction': ['raffinate', 'extract'],
         'decanter': ['light', 'heavy'], 'splitter': ['first', 'second']}


def source_lle_active_model(card, incoming):
    active = np.flatnonzero(np.asarray(incoming) > 0).tolist()
    if len(active) == len(card['component_order']):
        return NRTLModel(card), active
    if [card['component_order'][index] for index in active] != ['108-87-2', '108-88-3', '126-33-0']:
        raise ValueError('LLE_COMPONENT_COVERAGE: exact absent-species submodel unavailable')
    subset, checksum = mixture_card('mch_toluene_sulfolane_lle_ternary_brouwer2021')
    for field in ['A', 'B_K', 'alpha']:
        if not np.array_equal(np.asarray(card[field])[np.ix_(active, active)], subset[field]):
            raise ValueError('LLE_SUBMODEL_PARAMETER_MISMATCH')
    return NRTLModel(subset), active


def validate_hybrid_graph(graph, basis):
    units = {unit.unit_id: unit for unit in graph.units}
    tears = {tear.tear_id: tear for tear in graph.tears}
    if len(units) != len(graph.units) or len(tears) != len(graph.tears):
        raise ValueError('DUPLICATE_GRAPH_ID')
    if sum(unit.kind == 'column' for unit in graph.units) > basis.budget.maximum_columns:
        raise ValueError('COLUMN_BUDGET')
    required = {'MCH', 'TOL'}
    if not required.issubset(graph.products) or any(name not in required and not name.startswith('waste_') for name in graph.products):
        raise ValueError('EXTERNAL_PRODUCTS: required keys MCH, TOL and optional waste_ outlets; actual keys '+str(list(graph.products)))
    if basis.design_id == 'H02' and not {'solvent_rich', 'solvent_recycle'}.issubset(graph.constraint_streams):
        raise ValueError('ORIGINAL_CONSTRAINT_STREAMS: identify solvent_rich and solvent_recycle evaluation locations')
    outputs = {unit.unit_id+'.'+port for unit in graph.units for port in PORTS.get(unit.kind, ['out'])}
    physical = {'fresh'} | outputs
    tear_refs = {'tear.'+name for name in tears}
    uses = Counter(stream for unit in graph.units for stream in unit.inputs)
    uses.update(graph.products.values())
    uses.update(tear.source_stream for tear in graph.tears)
    if set(uses) != physical | tear_refs or any(count != 1 for count in uses.values()):
        raise ValueError('GRAPH_PORTS: each outlet requires one consumer. Missing '+str(sorted((physical | tear_refs)-set(uses)))+
            '; unknown '+str(sorted(set(uses)-(physical | tear_refs)))+'; multiply consumed '+str({k:v for k,v in uses.items() if v!=1}))
    if any(stream not in outputs for stream in graph.constraint_streams.values()):
        raise ValueError('CONSTRAINT_LOCATION: reference an actual unit output')
    if basis.design_id == 'H02':
        recycle = graph.constraint_streams['solvent_recycle']
        if recycle not in {tear.source_stream for tear in graph.tears}:
            raise ValueError('RECYCLE_ROLE: solvent_recycle must be an actual declared recycle source')
        reachable = {graph.constraint_streams['solvent_rich']}
        while True:
            added = {unit.unit_id+'.'+port for unit in graph.units if set(unit.inputs)&reachable
                     for port in PORTS.get(unit.kind, ['out'])}
            if added <= reachable:
                break
            reachable.update(added)
        if graph.products['TOL'] not in reachable:
            raise ValueError('RECOVERY_ROLE: solvent_rich='+graph.constraint_streams['solvent_rich']+
                ' reaches '+str(sorted(reachable))+'; required TOL product='+graph.products['TOL'])
    for unit in graph.units:
        from .hybrid_model_scope import admitted_card
        if not admitted_card(unit.property_card_id,basis):
            raise ValueError('UNREGISTERED_SOURCE_MODEL')
        if unit.kind in {'auxiliary_feed','makeup_mixer'} and unit.makeup_component not in basis.allowed_auxiliary_feeds:
            raise ValueError('UNREGISTERED_AUXILIARY_CHEMICAL')
        if unit.kind == 'extraction' and unit.property_card_id != 'mch_toluene_sulfolane_lle_brouwer2021':
            raise ValueError('LLE_MODEL_SCOPE: source liquid-liquid model required')
        if unit.kind == 'extraction' and unit.carrier_component != 'Methylcyclohexane':
            raise ValueError('EXTRACTION_ROLES: carrier_component=Methylcyclohexane identifies the raffinate; Toluene is solute and Sulfolane is extracting solvent')
        if unit.kind == 'column' and unit.property_card_id.endswith('_lle_brouwer2021'):
            raise ValueError('VLE_MODEL_SCOPE: liquid-liquid table cannot replace vapor-liquid table')
        if len(set(unit.distillate_inventory_components))!=len(unit.distillate_inventory_components) or set(unit.distillate_inventory_components)-set(basis.components):
            raise ValueError('COLUMN_INVENTORY_IDENTITIES: unique actual component names required')
        if unit.kind=='decanter':
            try:
                MixtureProbeRequest(property_card_id=unit.property_card_id,phase_policy='direct_lle',
                    lle_initialization='independent_gibbs',points=[dict(point_id='contract_only',
                        mole_fractions=basis.fresh_mole_fractions,temperature_K=unit.temperature_K,
                        pressure_Pa=unit.pressure_Pa,specification='TP')])
            except ValueError as exc:
                raise ValueError('DECANTER_METHOD_SCOPE: current native LLE interface requires the registered LLE card, 293.15 to 303.15 K and 8000 to 101325 Pa; revise unit '+unit.unit_id) from exc
    for tear in graph.tears:
        if len(tear.component_flows_mol_s) != len(basis.components) or min(tear.component_flows_mol_s) < 0 or sum(tear.component_flows_mol_s) <= 0:
            raise ValueError('TEAR_GUESS: nonnegative normalized physical component-flow guess required')
    findings=pressure_findings(graph,basis)
    if findings:
        raise ValueError('PRESSURE_LIFT_REQUIRES_PUMP: '+json.dumps(findings))
    adjacency = {name: set() for name in ['fresh', *units]}
    for unit in graph.units:
        for reference in unit.inputs:
            source = reference.split('.')[0]
            if source == 'tear':
                source = tears[reference.split('.')[1]].source_stream.split('.')[0]
            adjacency[unit.unit_id].add(source)
            adjacency[source].add(unit.unit_id)
    reached, pending = set(), ['fresh']
    while pending:
        current = pending.pop()
        if current not in reached:
            reached.add(current)
            pending.extend(adjacency[current]-reached)
    if reached != set(adjacency):
        raise ValueError('DISCONNECTED_GRAPH: every process unit must connect to the original feed network')
    ready, remaining, order = {'fresh'} | tear_refs, dict(units), []
    while remaining:
        executable = [unit for unit in remaining.values() if set(unit.inputs) <= ready]
        if not executable:
            raise ValueError('UNDECLARED_RECYCLE: every numerical cycle requires an explicit tear')
        for unit in executable:
            order.append(unit.unit_id)
            ready.update(unit.unit_id+'.'+port for port in PORTS.get(unit.kind, ['out']))
            remaining.pop(unit.unit_id)
    return dict(order=order, design_signature=digest(graph.model_dump()),
        connected_ports_passed=True, declared_tears=len(tears))


class HybridRuntime(TopologyRuntime):
    def __init__(self, state, folder, backend, emit):
        super().__init__(state, folder, backend, emit)
        self.sequence = 0
        self.unit_history = {}
        self.initialization_records = {}

    def call(self, method, request, label):
        self.sequence += 1
        return self.native_call(method, request, self.current_folder/f'{self.sequence:03d}_{label}.json')

    def port_vector(self,vector,temperature,card_id):
        vector = np.asarray(vector, dtype=float)
        if np.any(vector < 0) or not np.isfinite(vector).all() or sum(vector) <= 0:
            raise ValueError('NONPHYSICAL_STREAM')
        if 'Sulfolane' in self.state.basis.components:
            reference = json.loads((ROOT/'engineering/data/hybrid/sulfolane_solid_phase_reference.json').read_text(encoding='utf8'))
            order = mixture_card(card_id)[0]['component_order']
            screen = near_pure_freezing_screen(temperature, (vector/sum(vector)).tolist(), order, reference)
            if screen['passed'] is False:
                raise ValueError('NEAR_PURE_SOLVENT_FREEZING: '+json.dumps(screen))
        return vector

    def equilibrium_port(self,vector,temperature,pressure,card_id,label):
        vector=self.port_vector(vector,temperature,card_id)
        request=MixtureProbeRequest(property_card_id=card_id,points=[dict(point_id=label,
            mole_fractions=(vector/sum(vector)).tolist(),temperature_K=temperature,
            pressure_Pa=pressure,specification='TP')])
        raw=self.call('mixture_probe',request,label+'_TP')
        row=raw['points'][0]
        if not row.get('converged') or not row.get('numerical_validation_passed'):
            raise ValueError('TP_STATE_FAILED: '+str(row.get('error')))
        properties=row['native_overall_properties']
        if not np.isfinite([properties['molecular_weight_kg_kmol'],properties['specific_enthalpy_kJ_kg']]).all():
            raise ValueError('TP_STATE_FAILED: nonfinite overall properties')
        if abs(row['temperature_K']-temperature)>1e-7*max(abs(temperature),1.):
            raise ValueError('TP_STATE_FAILED: specified temperature changed')
        return dict(flow_mol_s=float(sum(vector)),mole_fractions=(vector/sum(vector)).tolist(),
            mass_flow_kg_s=float(sum(vector)*properties['molecular_weight_kg_kmol']/1000),
            specific_enthalpy_kJ_kg=properties['specific_enthalpy_kJ_kg'],
            temperature_K=row['temperature_K'],pressure_Pa=pressure,
            vapor_mole_fraction=properties['vapor_mole_fraction'],
            density_kg_m3=properties['density_kg_m3'],equilibrium_phases=row['phases'],
            state_specification='TP',evidence_id=raw['evidence_id'])

    def liquid_port(self, vector, temperature, pressure, card_id, label):
        vector=self.port_vector(vector,temperature,card_id)
        unifac = mixture_card(card_id)[0]['model'] == 'UNIFAC'
        request = MixtureProbeRequest(property_card_id=card_id, points=[dict(point_id=label,
            mole_fractions=(vector/sum(vector)).tolist(), temperature_K=temperature,
            pressure_Pa=pressure, specification='phase_properties' if unifac else 'pure_properties')])
        raw = self.call('mixture_probe', request, label+'_properties')
        row = raw['points'][0]
        if not row.get('executed'):
            raise ValueError('NATIVE_PROPERTY_FAILURE: '+str(row))
        properties = row['phase_properties'] if unifac else dict(
            molecular_weight_kg_kmol=row['native_liquid_molecular_weight_kg_kmol'],
            specific_enthalpy_kJ_kg=row['native_liquid_specific_enthalpy_kJ_kg'],
            density_kg_m3=row['native_liquid_density_kg_m3'])
        mass = float(sum(vector)*properties['molecular_weight_kg_kmol']/1000)
        return dict(flow_mol_s=float(sum(vector)), mole_fractions=(vector/sum(vector)).tolist(),
            mass_flow_kg_s=mass, specific_enthalpy_kJ_kg=properties['specific_enthalpy_kJ_kg'],
            temperature_K=temperature, pressure_Pa=pressure,
            density_kg_m3=properties['density_kg_m3'], evidence_id=raw['evidence_id'])

    def vector(self, port):
        return np.asarray(port['mole_fractions'])*port['flow_mol_s']

    def heat(self, port):
        return port['mass_flow_kg_s']*port['specific_enthalpy_kJ_kg']

    def properties_card(self):
        from .hybrid_model_scope import admitted_card
        basis=self.state.basis
        graph=getattr(self,'active_graph',None)
        for unit in (graph.units if graph is not None else []):
            if unit.property_card_id not in basis.property_cards and admitted_card(unit.property_card_id,basis):
                return unit.property_card_id
        return basis.property_cards[-1]

    def run_unit(self, unit, inputs):
        basis = self.state.basis
        vectors = [self.vector(port) for port in inputs]
        incoming = sum(vectors,np.zeros(len(basis.components)))
        incoming_heat = sum(self.heat(port) for port in inputs)
        output = {}
        external = []
        work = 0.
        if unit.kind not in {'pump','splitter'} and any(unit.pressure_Pa>port['pressure_Pa']+1 for port in inputs):
            raise ValueError('PRESSURE_LIFT_REQUIRES_PUMP: '+unit.unit_id)
        if unit.kind == 'column':
            if unit.distillate_inventory_components:
                draw=float(sum(incoming[basis.components.index(name)] for name in unit.distillate_inventory_components)*unit.distillate_inventory_multiplier)
                save(self.current_folder/(unit.unit_id+'.inventory_draw_rule.json'),dict(
                    selected_components=unit.distillate_inventory_components,multiplier=unit.distillate_inventory_multiplier,
                    actual_inlet_components_mol_s=incoming.tolist(),calculated_draw_mol_s=draw,
                    scope='Agent-selected inventory-based design specification, recomputed at each actual recycle iterate; strict verification still required.'))
                unit=unit.model_copy(update={'distillate_inventory_components':[],
                    'distillate_inventory_multiplier':None,'distillate_flow_mol_s':draw})
            selected_solver=unit.numerical_solver
            if unit.numerical_solver=='sparse_trust_region' and unit.numerical_jacobian_policy=='balanced_reduced' and min(incoming)<=0 and not basis.budget.project_exact_absent_species:
                absent=[basis.components[i] for i,value in enumerate(incoming) if value<=0]
                selected_solver='native'
                save(self.current_folder/(unit.unit_id+'.numerical_method.json'),dict(
                    proposed_solver=unit.numerical_solver,effective_solver=selected_solver,
                    reason='Exact absent species outside positive-coordinate solver coverage',
                    absent_species=absent,physical_feed_unchanged=True))
            card,_=mixture_card(unit.property_card_id)
            bounds=product_draw_bounds(basis,self.active_graph,unit,incoming,card['molecular_weights_g_mol'])
            save(self.current_folder/(unit.unit_id+'.product_inventory.json'),bounds)
            if not self.active_graph.tears and any(not check['passed'] for check in bounds):
                raise ValueError('PRODUCT_DRAW_INVENTORY: '+json.dumps(bounds))
            request = MultiFeedColumnRequest(property_card_id=unit.property_card_id,
                purpose='design_candidate', feeds=[dict(feed_id=f'{unit.unit_id}_feed_{i}',
                    flow_mol_s=port['flow_mol_s'], mole_fractions=port['mole_fractions'],
                    temperature_K=port['temperature_K'], specific_enthalpy_kJ_kg=port['specific_enthalpy_kJ_kg'],
                    stage_index=unit.feed_stages[i], source_evidence_id=port['evidence_id']) for i, port in enumerate(inputs)],
                pressure_pa=unit.pressure_Pa, distillate_flow_mol_s=(unit.distillate_flow_mol_s if
                    unit.distillate_flow_mol_s is not None else float(sum(incoming)*unit.distillate_fraction)),
                bottom_pressure_pa=unit.bottom_pressure_Pa,
                reflux_ratio=unit.reflux_ratio, equilibrium_stages=unit.stages,
                column_mode=unit.column_mode, solver_preference=unit.solver_preference,
                numerical_solver=selected_solver, numerical_jacobian_policy=unit.numerical_jacobian_policy,
                positive_balance_initialization=True,
                trace_relative_finite_differences=basis.budget.trace_relative_finite_differences,
                strict_flash_tolerances=True,
                refine_ph_feed=True,
                project_exact_absent_species=basis.budget.project_exact_absent_species,
                canonicalize_roundoff_compositions=basis.budget.canonicalize_roundoff_compositions,
                solver_iteration_limit=300, solver_tolerance=1e-9,
                save_path=str((self.current_folder/(f'{self.sequence+1:03d}_{unit.unit_id}.dwxmz')).resolve()))
            old = self.unit_history.get(unit.unit_id)
            if unit.initialization_evidence_id:
                entry = self.initialization_records.get(unit.initialization_evidence_id)
                if entry is None:
                    raise ValueError('UNKNOWN_INITIALIZATION_EVIDENCE')
                if hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('INITIALIZATION_EVIDENCE_CHANGED')
                old = entry['record']
            from .hybrid_model_scope import same_source_physics
            compatible=[entry for entry in self.initialization_records.values() if
                same_source_physics(entry['record']['property_card_id'],unit.property_card_id,basis) and
                entry['record']['request']['column_mode']==unit.column_mode]
            if unit.initialization_policy=='cold':
                old=None
                compatible=[]
            if old is None and compatible:
                from .hybrid_initialization import initialization_distance
                def distance(entry):return initialization_distance(entry['record'],request)
                entry=min(compatible,key=distance)
                if hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()!=entry['sha256']:
                    raise ValueError('INITIALIZATION_EVIDENCE_CHANGED')
                old=entry['record']
            if old and same_source_physics(old['property_card_id'],unit.property_card_id,basis) and old['request']['column_mode']==unit.column_mode:
                profile=resample_profile(old,request)
                if unit.initialization_policy=='equilibrium_rescale':
                    count=len(profile)
                    phase=self.call('mixture_probe',MixtureProbeRequest(property_card_id=unit.property_card_id,
                        points=[dict(point_id=str(i),mole_fractions=row['liquid_mole_fractions'],
                            temperature_K=row['temperature_K'],pressure_Pa=unit.pressure_Pa+
                            ((unit.bottom_pressure_Pa or unit.pressure_Pa)-unit.pressure_Pa)*i/(count-1),
                            specification='bubble') for i,row in enumerate(profile)]),unit.unit_id+'_pressure_initialization')
                    for row,point in zip(profile,phase['points']):
                        if not point.get('numerical_validation_passed'):raise ValueError('PRESSURE_INITIALIZATION_PHASE_FAILED')
                        row.update(temperature_K=point['temperature_K'],vapor_mole_fractions=point['vapor_mole_fractions'])
                    save(self.current_folder/(unit.unit_id+'.pressure_initialization.json'),dict(
                        source_native_evidence_id=old['evidence_id'],bubble_probe_evidence_id=phase['evidence_id'],
                        estimates_only=True,profile=profile))
                request = request.model_copy(update={'initial_profile': profile,
                    'initial_estimate_source_evidence_id': old['evidence_id']})
                from ..validation.initialization import material_consistent_profile
                try:
                    profile,projection=material_consistent_profile(request)
                    request=request.model_copy(update={'initial_profile':profile})
                except ValueError as error:
                    projection=dict(estimates_only=True,projection_error=str(error),retained_resampled_profile=True)
                save(self.current_folder/(unit.unit_id+'.initialization.json'),dict(
                    source_evidence_id=old['evidence_id'],estimates_only=True,
                    source_stage_count=len(old['outputs']['stage_profiles']),
                    revised_stage_count=len(profile),material_projection=projection,profile=profile))
            try:
                native = self.call('column', request, unit.unit_id)
            except (RuntimeError,TimeoutError) as error:
                numerical_failure=isinstance(error,TimeoutError) or any(term in str(error) for term in
                    ['did not converge','Newton','projection','MESH acceptance'])
                if request.numerical_solver!='sparse_trust_region' or not numerical_failure:
                    raise
                retry=request.model_copy(update={'numerical_solver':'native','solver_preference':'default',
                    'save_path':str((self.current_folder/f'{self.sequence+1:03d}_{unit.unit_id}_native_retry.dwxmz').resolve())})
                self.emit('numerical_retry',unit_id=unit.unit_id,physical_parameters_unchanged=True,
                    proposed_solver=request.numerical_solver,retry_solver=retry.numerical_solver)
                native=self.call('column',retry,unit.unit_id+'_native_retry')
            runtime = self

            class ProbeBackend:
                def mixture_probe(self, request):
                    return runtime.call('mixture_probe', request, unit.unit_id+'_review')

            review = review_multifeed_column(native, ProbeBackend())
            save(self.current_folder/(f'{self.sequence:03d}_{unit.unit_id}.review.json'), review)
            if review['numerical_passed'] and review['independent_finite_liquid_screen_passed'] and not review['stage_equilibrium_passed'] and review['maximum_log_fugacity_residual']<.01 and request.numerical_solver=='sparse_trust_region':
                polished=request.model_copy(update={'numerical_solver':'native',
                    'initial_profile':resample_profile(native,request),'initial_estimate_source_evidence_id':native['evidence_id'],
                    'save_path':str((self.current_folder/f'{self.sequence+1:03d}_{unit.unit_id}_phase_polish.dwxmz').resolve())})
                self.emit('numerical_phase_polish',unit_id=unit.unit_id,physical_parameters_unchanged=True,
                    failed_independent_phase_residual=review['maximum_log_fugacity_residual'])
                native=self.call('column',polished,unit.unit_id+'_phase_polish')
                review=review_multifeed_column(native,ProbeBackend())
                save(self.current_folder/f'{self.sequence:03d}_{unit.unit_id}_phase_polished.review.json',review)
            if not all(review[key] for key in ['numerical_passed', 'stage_equilibrium_passed', 'independent_finite_liquid_screen_passed']):
                raise ValueError('INDEPENDENT_COLUMN_REVIEW_FAILED: '+json.dumps(review))
            self.unit_history[unit.unit_id] = native
            for name in PORTS['column']:
                port = dict(native['outputs'].get(name, native['outputs'].get('overhead_vapor') if name == 'distillate' else None))
                expected_pressure=(unit.bottom_pressure_Pa or unit.pressure_Pa) if name=='bottoms' else unit.pressure_Pa
                port.update(pressure_Pa=port.get('pressure_Pa',expected_pressure), evidence_id=native['evidence_id'])
                if abs(port['pressure_Pa']-expected_pressure)>1e-6*expected_pressure:
                    raise ValueError('NATIVE_COLUMN_PORT_PRESSURE_MISMATCH')
                port['vapor_mole_fraction']=1. if unit.column_mode=='reboiled_absorber' and name=='distillate' else 0.
                output[name] = port
        elif unit.kind=='auxiliary_feed':
            if unit.makeup_component not in basis.allowed_auxiliary_feeds:
                raise ValueError('UNREGISTERED_AUXILIARY_CHEMICAL')
            incoming[basis.components.index(unit.makeup_component)]=unit.target_component_flow_mol_s
            port=self.equilibrium_port(incoming,unit.temperature_K,unit.pressure_Pa,unit.property_card_id,unit.unit_id+'_fresh_auxiliary')
            output['out']=port;external.append(port);incoming_heat=self.heat(port)
        elif unit.kind == 'extraction':
            card, _ = mixture_card(unit.property_card_id)
            model, active = source_lle_active_model(card, incoming)
            names = [basis.components[index] for index in active]
            feed, solvent = 3.6*vectors[0][active], 3.6*vectors[1][active]
            carrier = names.index(unit.carrier_component)
            if unit.extraction_solver == 'simultaneous':
                r0, e0, flash = contact(model, feed+solvent, unit.temperature_K, unit.pressure_Pa,
                    carrier, require_qualified=False)
                floor = sum(feed+solvent)*np.exp(-50.)
                estimates = [dict(raffinate_kmol_h=np.maximum(r0, floor).tolist(),
                    extract_kmol_h=np.maximum(e0, floor).tolist()) for _ in range(unit.stages)]
                save(self.current_folder/(f'{self.sequence:03d}_{unit.unit_id}.cold_initialization.json'),
                    dict(estimates_only=True, physical_feeds_unchanged=True,
                        source_single_equilibrium_contact=flash, profiles=estimates))
                raw = extraction_simultaneous(model, feed, solvent, unit.temperature_K,
                    unit.pressure_Pa, unit.stages, carrier, estimates, require_qualified=False, max_evaluations=600)
            else:
                raw = extraction_cascade(model, feed, solvent, unit.temperature_K,
                    unit.pressure_Pa, unit.stages, carrier, names.index('Toluene'),
                    names.index('Sulfolane'), max_iterations=300, require_qualified=False)
            raw['active_original_component_indices'] = active
            raw['absent_species_policy'] = 'Exact source submatrix for truly absent species; zero components are restored on output without added material'
            save(self.current_folder/(f'{self.sequence:03d}_{unit.unit_id}.lle.json'), raw)
            if not raw['validation']['passed']:
                raise ValueError('LLE_CASCADE_NOT_CONVERGED')
            for name in PORTS['extraction']:
                vector = np.zeros(len(basis.components))
                vector[active] = np.asarray(raw[name+'_kmol_h'])/3.6
                output[name] = self.liquid_port(vector, unit.temperature_K,
                    unit.pressure_Pa, self.properties_card(), unit.unit_id+'_'+name)
        elif unit.kind == 'decanter':
            request = MixtureProbeRequest(property_card_id=unit.property_card_id,
                phase_policy='direct_lle', lle_initialization='independent_gibbs', points=[dict(
                    point_id=unit.unit_id, mole_fractions=(incoming/sum(incoming)).tolist(),
                    temperature_K=unit.temperature_K, pressure_Pa=unit.pressure_Pa, specification='TP')])
            raw = self.call('mixture_probe', request, unit.unit_id+'_split')
            row = raw['points'][0]
            if not row.get('converged') or len(row.get('phases', [])) != 2:
                raise ValueError('DECANTER_PHASE_COUNT_OR_CONVERGENCE')
            if not row.get('ideal_vapor_screen_passed'):
                raise ValueError('DECANTER_VAPOR_STABILITY: revise condensation conditions before liquid separation')
            ports=[self.liquid_port(sum(incoming)*phase['molar_fraction']*np.asarray(phase['composition']),
                unit.temperature_K,unit.pressure_Pa,self.properties_card(),unit.unit_id+'_phase_'+str(i))
                for i,phase in enumerate(row['phases'])]
            ports.sort(key=lambda port:port['density_kg_m3'])
            output.update(dict(zip(PORTS['decanter'],ports)))
        elif unit.kind == 'splitter':
            for name, fraction in [('first', unit.split_fraction), ('second', 1-unit.split_fraction)]:
                port = dict(inputs[0])
                port['flow_mol_s'] *= fraction
                port['mass_flow_kg_s'] *= fraction
                output[name] = port
        else:
            if unit.kind == 'makeup_mixer':
                if unit.makeup_component not in basis.allowed_auxiliary_feeds or unit.makeup_component not in basis.components:
                    raise ValueError('UNREGISTERED_MAKEUP_CHEMICAL')
                index = basis.components.index(unit.makeup_component)
                amount = unit.target_component_flow_mol_s-incoming[index]
                if amount < 0:
                    raise ValueError('MAKEUP_REQUIRES_PURGE: returned inventory exceeds proposed circulating target')
                if amount > 0:
                    added = np.zeros(len(incoming))
                    added[index] = amount
                    external.append(self.equilibrium_port(added, unit.temperature_K, unit.pressure_Pa,
                        self.properties_card(), unit.unit_id+'_makeup'))
                    incoming += added
                    incoming_heat += self.heat(external[-1])
            if unit.kind == 'pump':
                if inputs[0].get('vapor_mole_fraction',0.)>1e-8:
                    raise ValueError('PUMP_REQUIRES_LIQUID_INLET')
                if len(inputs[0].get('equilibrium_phases',[]))>1:
                    raise ValueError('PUMP_REQUIRES_SINGLE_LIQUID_PHASE')
                if len(inputs) != 1 or unit.pressure_Pa <= inputs[0]['pressure_Pa']:
                    raise ValueError('PUMP_PRESSURE_PRECONDITION')
                density = inputs[0].get('density_kg_m3')
                if density is None:
                    inlet = self.liquid_port(vectors[0], inputs[0]['temperature_K'], inputs[0]['pressure_Pa'],
                        self.properties_card(), unit.unit_id+'_inlet')
                    density = inlet['density_kg_m3']
                work = inputs[0]['mass_flow_kg_s']/density*(unit.pressure_Pa-inputs[0]['pressure_Pa'])/unit.efficiency/1000
            elif any(unit.pressure_Pa > port['pressure_Pa']+1 for port in inputs):
                raise ValueError('PRESSURE_LIFT_REQUIRES_PUMP')
            make_port=self.equilibrium_port if basis.design_id=='H02' else self.liquid_port
            output['out'] = make_port(incoming, unit.temperature_K, unit.pressure_Pa,
                self.properties_card(), unit.unit_id+'_out')
        total = sum(self.vector(port) for port in output.values())
        error = float(max(abs(total-incoming))/max(sum(incoming), 1e-12))
        if error > 1e-7:
            raise ValueError('UNIT_COMPONENT_BALANCE_FAILED')
        if unit.kind == 'column':
            heat = native['outputs']['reboiler_duty_kW']-native['outputs']['condenser_duty_kW']
        else:
            heat = sum(self.heat(port) for port in output.values())-incoming_heat-work
        return output, external, float(heat), float(work)

    def execute(self, graph, candidate_id, *, include_target_review=True):
        self.active_graph=graph
        checked = validate_hybrid_graph(graph, self.state.basis)
        self.current_folder = self.folder/candidate_id
        self.current_folder.mkdir(exist_ok=False)
        save(self.current_folder/'graph.json', graph.model_dump())
        basis = self.state.basis
        fresh_vector = basis.fresh_flow_mol_s*np.asarray(basis.fresh_mole_fractions)
        fresh = self.equilibrium_port(fresh_vector, basis.fresh_temperature_K, basis.fresh_pressure_Pa,
            self.properties_card(), 'fresh')
        tear_ports = {tear.tear_id: self.liquid_port(tear.component_flows_mol_s,
            tear.temperature_K, tear.pressure_Pa, self.properties_card(), tear.tear_id+'_guess') for tear in graph.tears}
        units = {unit.unit_id: unit for unit in graph.units}
        iterations = []
        for iteration in range(1,self.state.basis.budget.maximum_recycle_iterations+1):
            self.check()
            streams = {'fresh': fresh, **{'tear.'+name: port for name, port in tear_ports.items()}}
            external, heat, work = [fresh], 0., 0.
            failures=[]
            for identifier in checked['order']:
                unit = units[identifier]
                if any(stream not in streams for stream in unit.inputs):
                    failures.append(dict(unit_id=identifier,status='blocked',reason='Upstream unit failed'))
                    continue
                try:
                    output, added, q, w = self.run_unit(unit, [streams[stream] for stream in unit.inputs])
                except TopologyBudgetExceeded:raise
                except (ValueError,RuntimeError,TimeoutError) as exc:
                    failures.append(dict(unit_id=identifier,status='failed',error_type=type(exc).__name__,error=str(exc)))
                    continue
                streams.update({identifier+'.'+name: port for name, port in output.items()})
                external.extend(added)
                heat += q
                work += w
            if failures:
                partial=dict(iteration=iteration,streams=streams,unit_failures=failures,
                    scope='Partial independent branch execution; whole-process acceptance blocked.')
                save(self.current_folder/'partial_execution.json',partial)
                summary=[{**row,'error':row.get('error','')[:800]} for row in failures]
                raise ValueError('PARTIAL_PROCESS_FAILURE: '+json.dumps(summary))
            products = {name: streams[stream] for name, stream in graph.products.items()}
            returned = {tear.tear_id: streams[tear.source_stream] for tear in graph.tears}
            recycle = max([float(max(abs(self.vector(tear_ports[name])-self.vector(port)))/basis.fresh_flow_mol_s)
                for name, port in returned.items()] or [0.])
            incoming = sum(self.vector(port) for port in external)
            outgoing = sum(self.vector(port) for port in products.values())
            component = float(max(abs(incoming-outgoing))/basis.fresh_flow_mol_s)
            hin = sum(self.heat(port) for port in external)
            hout = sum(self.heat(port) for port in products.values())
            energy = abs(hin+heat+work-hout)/max(abs(hin), abs(hout), abs(heat), 1.)
            record = dict(iteration=iteration, streams=streams, external_inputs=external,
                products=products, heat_kW=heat, work_kW=work, component_residual=component,
                energy_residual=energy, recycle_residual=recycle)
            iterations.append(record)
            save(self.current_folder/'iterations.json', iterations)
            if max(component, energy, recycle) <= 1e-7:
                return dict(**record, directory=str(self.current_folder), graph_check=checked,
                    independent_review=review_hybrid_targets(basis, graph, streams, products) if include_target_review else None,
                    numerically_closed=True)
            tear_ports = copy.deepcopy(returned)
        return dict(**iterations[-1], directory=str(self.current_folder), numerically_closed=False,
            independent_review=review_hybrid_targets(basis, graph, streams, products) if include_target_review else None)


def review_hybrid_targets(basis, graph, streams, products):
    card, card_hash = mixture_card(basis.property_cards[-1])
    mw = np.asarray(card['molecular_weights_g_mol'])
    def mass_fraction(port, component):
        index = basis.components.index(component)
        z = np.asarray(port['mole_fractions'])
        return float(z[index]*mw[index]/(z@mw))
    if basis.design_id == 'H01':
        checks = {name+'_mass_purity': mass_fraction(products[name], component) >= .9985
            for name, component in [('MCH', 'Methylcyclohexane'), ('TOL', 'Toluene')]}
        values = {name+'_mass_fraction': mass_fraction(products[name], component)
            for name, component in [('MCH', 'Methylcyclohexane'), ('TOL', 'Toluene')]}
    else:
        rich = streams[graph.constraint_streams['solvent_rich']]
        recycle = streams[graph.constraint_streams['solvent_recycle']]
        mch, tol, phenol = [basis.components.index(name) for name in ['Methylcyclohexane', 'Toluene', 'Phenol']]
        values = dict(solvent_rich_MCH_mole_fraction=rich['mole_fractions'][mch],
            TOL_product_phenol_mole_fraction=products['TOL']['mole_fractions'][phenol],
            recycle_TOL_fraction_of_fresh_TOL=recycle['flow_mol_s']*recycle['mole_fractions'][tol]/
                (basis.fresh_flow_mol_s*basis.fresh_mole_fractions[tol]))
        checks = dict(solvent_rich_MCH=values['solvent_rich_MCH_mole_fraction'] <= 1e-4,
            TOL_product_phenol=values['TOL_product_phenol_mole_fraction'] <= 1e-3,
            solvent_recycle_TOL_loss=values['recycle_TOL_fraction_of_fresh_TOL'] <= 1e-3)
    return dict(passed=all(checks.values()), checks=checks, actual_values=values,
        original_requirements=basis.requirements, property_card_sha256=card_hash,
        experimental_property_qualification=False, full_equipment_qualification=False)


def candidate_counterevidence(candidate):
    """Compact measured failure feedback. Full artifacts remain on disk."""
    result={key:candidate[key] for key in ['candidate_id','status','graph','graph_check'] if key in candidate}
    if 'graph' in result:
        result['graph']=copy.deepcopy(result['graph'])
        result['graph']['units']=[{key:value for key,value in unit.items() if value is not None}
            for unit in result['graph'].get('units',[])]
    error=candidate.get('error','')
    if error:
        result['error']=error if len(error)<=3000 else error[:1200]+'\n[full error retained in raw ledger]\n'+error[-1800:]
    executed=candidate.get('result')
    if executed:
        result['actual_execution']={key:executed.get(key) for key in ['numerically_closed',
            'component_residual','energy_residual','recycle_residual','independent_review']}
        result['actual_execution']['product_ports']={name:{key:port.get(key) for key in
            ['flow_mol_s','mole_fractions','mass_flow_kg_s']} for name,port in executed.get('products',{}).items()}
    if candidate.get('partial_execution'):
        result['partial_execution']=candidate['partial_execution']
    return result


class HybridTopologyOrchestrator(TopologySynthesisOrchestrator):
    def ask(self,role,contract,context):
        maximum=self.basis.budget.maximum_recorded_tokens
        used=sum(event.get('usage',{}).get('total_tokens',0) for event in self.state.provider_events)
        if maximum is not None and used>=maximum:
            raise TopologyBudgetExceeded('RECORDED_TOKEN_BUDGET')
        visible=compact_context(context)
        if role=='thermodynamics expert':
            for key in ['previous_candidates','previous_public_expert_advice','prior_autonomous_failures',
                'latest_measured_process','available_computational_initializations']:
                visible.pop(key,None)
            visible['role_instruction']='Assess actual phase evidence, applicability and route alternatives. Avoid inventing unit IDs or copying earlier unverified parameter recommendations. Identify directly qualifying phase compositions where calculated; a whole flowsheet still needs verification.'
        elif 'revision_base' in visible:
            visible.pop('latest_measured_process',None)
            visible.pop('prior_autonomous_failures',None)
        return super().ask(role,contract,visible)

    def __init__(self, basis, backend, continue_previous=True, continuation_run_id=None,additional_evidence_paths=(), *, output_folder=None):
        EngineeringOrchestrator.__init__(self, backend=backend)
        self.basis = basis
        self.folder = Path(output_folder) if output_folder is not None else ROOT/'output/engineering/autonomous_original_cases_20261116'/basis.design_id/str(uuid4())
        self.folder.mkdir(parents=True, exist_ok=False)
        self.state = HybridState(run_id=self.folder.name, basis=basis)
        self.runtime = HybridRuntime(self.state, self.folder, MultiFeedDwsimBackend(), self.emit)
        self.event_index = 0
        self._backend.max_tokens = 6000
        self.process_skills = ProcessSkillRegistry()
        self.policy = ('Use the registered source property cards and typed units to construct a preliminary chemical separation graph. '
            'Only fresh feeds and original targets are supplied. Propose unit count, connections, auxiliary chemicals, '
            'recycle tears and numerical parameters. Retain every failure. Physical performance requires actual tools. '
            'Source model cards are conditional research hypotheses with open full-mixture qualification. '
            'Every port has one consumer. Use references fresh, U1.out, U1.distillate, U1.bottoms, '
            'U1.raffinate, U1.extract, U1.first, U1.second, U1.light, U1.heavy, tear.T1. '
            'Each tear points to an actual outlet, with a numerical cold component-flow guess, T and P. '
            'The graph.products object must contain literal keys MCH and TOL. All other external products need a waste_ prefix. '
            'The allowed_auxiliary_feeds list explicitly authorizes fresh solvent/water supply as design variables. '
            'Zero solvent in the hydrocarbon fresh feed is compatible with adding an authorized auxiliary feed '
            'through makeup_mixer. Its required flow and circulation are Agent design decisions. '
            'A recycle outlet is consumed by its tear declaration, then used as tear.T1 at the receiving unit. '
            'It cannot also be an external product. For H02 the available source model is VLE UNIFAC, '
            'so liquid-liquid extraction and decanter operations are outside its model coverage. '
            'H01 constraint_streams is an empty object. H02 constraint_streams must be an object with '
            'exact keys solvent_rich and solvent_recycle, whose values are actual unit output references. '
            'The latter source must be declared as a recycle tear. Put quantitative limits only in frozen_basis, '
            'never in constraint_streams. For a purge plus recycle, insert an explicit splitter. '
            'Use an explicit makeup_mixer to restore solvent circulation. Select feasible kinds and sources accordingly. '
            'Return concise data matching the schema. '
            'For extractive distillation, compare feeding solvent above the hydrocarbon as separate actual feeds. '
            'A combined single feed can leave the rectifying section without solvent and needs computed evidence. '
            'Model text is evidence. Never invent numeric tool outputs or executable code.')
        method_prompt=ROOT/'engineering/prompts/HYBRID_TOPOLOGY_METHOD.md'
        self.policy+='\n'+method_prompt.read_text(encoding='utf8')
        files = [path for path in (ROOT/'sepmind/engineering/topology').glob('*.py')
                 if path.name not in {'binary.py', 'binary_contracts.py'}]
        files += [ROOT/'sepmind/simulation/multifeed.py', ROOT/'sepmind/simulation/mixture.py',
                  ROOT/'sepmind/engineering/validation/dwsim_mixture.py', ROOT/'sepmind/engineering/validation/dwsim_column.py']
        files += [ROOT/'engineering/data/hybrid'/(name+'.json') for name in basis.property_cards]
        files += list((ROOT/'engineering/runtime_process_skills').glob('*/SKILL.md'))
        files += [ROOT/'engineering/data/hybrid/sulfolane_solid_phase_reference.json',
                  ROOT/'engineering/data/hybrid/mch_toluene_sulfolane_lle_ternary_brouwer2021.json',
                  ROOT/'sepmind/engineering/validation/phase_admission.py']
        files += [ROOT/name for name in ['sepmind/engineering/design/extraction.py', 'sepmind/engineering/thermo/lle.py',
            'sepmind/engineering/validation/multifeed.py', 'sepmind/engineering/validation/native_sparse.py',
            'sepmind/engineering/validation/balanced_mesh.py', 'sepmind/simulation/_dwsim_worker.py']]
        files += [ROOT/'sepmind/engineering/validation/positive_balance_seed.py',
                  ROOT/'sepmind/engineering/validation/initialization.py',ROOT/'sepmind/engineering/validation/ph_precision.py']
        files.append(ROOT/'sepmind/engineering/validation/absent_species.py')
        files.append(ROOT/'sepmind/engineering/validation/composition_roundoff.py')
        files.append(method_prompt)
        self.source_manifest = {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        save(self.folder/'source_manifest.json', self.source_manifest)
        with zipfile.ZipFile(self.folder/'source_snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(ROOT))
        save(self.folder/'input.json', dict(basis=basis.model_dump(), initial_topology=None,
            historical_profiles_or_accepted_graph_loaded=False))
        self.persist()
        self.preflight = None
        self.phase_knowledge = None
        self.lle_knowledge = None
        self.prior_attempts = []
        self.incompatible_prior_attempts=[]
        self.continuation_base=None
        self.additional_native_evidence=load_native_phase_evidence(additional_evidence_paths,ROOT,basis.property_cards)
        save(self.folder/'additional_native_evidence.json',self.additional_native_evidence)
        if continue_previous:
            root = self.folder.parent
            for old_state in sorted(root.glob('*/state.json'),key=lambda path:path.stat().st_mtime):
                if old_state.parent == self.folder:
                    continue
                previous = json.loads(old_state.read_text(encoding='utf8'))
                old_basis = previous['basis']
                fixed_fields = ['fresh_flow_mol_s', 'fresh_mole_fractions', 'fresh_temperature_K',
                                'fresh_pressure_Pa', 'property_cards', 'requirements']
                if any(old_basis.get(key) != basis.model_dump()[key] for key in fixed_fields):
                    continue
                prior_candidates=[]
                for candidate in previous.get('candidates',[]):
                    if 'UNCHANGED_FAILED_GRAPH' in candidate.get('error',''):
                        continue
                    candidate=copy.deepcopy(candidate)
                    failures=sorted((old_state.parent/candidate['candidate_id']).glob('*.failure.json'))
                    if failures and candidate.get('error','').startswith('RuntimeError: DWSIM'):
                        candidate['error']=json.loads(failures[-1].read_text(encoding='utf8'))['error']
                    prior_candidates.append(candidate_counterevidence(candidate))
                compatible=basis.design_id=='H01' or old_basis.get('fresh_state_specification')=='TP'
                if compatible:
                    self.prior_attempts.append(dict(evidence_id='prior:'+previous['run_id'],
                        status=previous['status'], candidates=prior_candidates[-4:]))
                else:
                    self.incompatible_prior_attempts.append(dict(run_id=previous['run_id'],
                        reason='Legacy forced-liquid fresh feed conflicts with original TP equilibrium; case metrics excluded'))
                for path in old_state.parent.glob('candidate_*/*_U*.json'):
                    record = json.loads(path.read_text(encoding='utf8'))
                    if record.get('status') != 'ok' or 'stage_profiles' not in record.get('outputs', {}):
                        continue
                    model = record.get('property_card_id')
                    from .hybrid_model_scope import admitted_card
                    if not admitted_card(model,basis) or record.get('parameter_sha256') != mixture_card(model)[1]:
                        continue
                    self.runtime.initialization_records[record['evidence_id']] = dict(path=str(path),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), record=record,
                        original_fresh_state_compatible=compatible)
        save(self.folder/'prior_autonomous_evidence.json', dict(attempts=self.prior_attempts,
            incompatible_case_metrics_excluded=self.incompatible_prior_attempts,
            numerical_initializations=[{key: value for key, value in entry.items() if key != 'record'} |
                {'evidence_id': identifier} for identifier, entry in self.runtime.initialization_records.items()]))
        if continuation_run_id is not None:
            if str(UUID(continuation_run_id))!=continuation_run_id:
                raise ValueError('CONTINUATION_ID: canonical run UUID required')
            path=self.folder.parent/continuation_run_id/'result.json'
            previous=json.loads(path.read_text(encoding='utf8'))
            fixed=['design_id','components','fresh_flow_mol_s','fresh_mole_fractions',
                'fresh_temperature_K','fresh_pressure_Pa','property_cards','requirements']
            if previous.get('source_integrity_passed') is not True or any(
                previous['basis'].get(key)!=basis.model_dump()[key] for key in fixed):
                raise ValueError('CONTINUATION_EVIDENCE: source integrity or immutable basis mismatch')
            prior=next((candidate for candidate in reversed(previous['candidates']) if candidate.get('graph')),None)
            if prior is None:raise ValueError('CONTINUATION_GRAPH: no prior autonomous graph')
            self.continuation_base=candidate_counterevidence(prior)
            self.continuation_base['candidate_id']='prior:'+continuation_run_id+':'+prior['candidate_id']
            save(self.folder/'continuation_base.json',self.continuation_base | {'source':str(path),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})

    def sample_solvent_vle(self):
        if self.basis.design_id=='H01':
            request=MixtureProbeRequest(property_card_id=self.basis.property_cards[-1],points=[dict(
                point_id='solvent_free_MCH_'+str(x),mole_fractions=[x,1-x,0.,0.],
                temperature_K=380.,pressure_Pa=self.basis.fresh_pressure_Pa,specification='bubble')
                for x in [.01,.05,.2,.4,.6,.8,.95,.9985]])
            record=self.runtime.call('mixture_probe',request,'hydrocarbon_vle_knowledge')
            return dict(evidence_id=record['evidence_id'],points=record['points'],
                scope='Native solvent-free hydrocarbon VLE screening. Actual solvent-bearing columns require their own rigorous calculation. Compare enrichment before choosing reflux and stages.')
        z = np.asarray(self.basis.fresh_mole_fractions)
        solvent = np.zeros(len(z))
        solvent[self.basis.components.index('Phenol')] = 1.
        request = MixtureProbeRequest(property_card_id=self.basis.property_cards[-1], points=[dict(
            point_id='solvent_fraction_'+str(fraction), mole_fractions=((1-fraction)*z+fraction*solvent).tolist(),
            temperature_K=self.basis.fresh_temperature_K, pressure_Pa=self.basis.fresh_pressure_Pa,
            specification='bubble') for fraction in [0., .25, .5, .75]])
        record = self.runtime.call('mixture_probe', request, 'solvent_vle_knowledge')
        return dict(evidence_id=record['evidence_id'], points=record['points'],
            scope='Actual native equilibrium screening at hypothetical solvent loadings, distinct from process feed specifications')

    def sample_lle_loadings(self):
        if self.basis.design_id!='H01':return None
        basis=self.basis;card,checksum=mixture_card(basis.property_cards[0]);rows=[]
        fresh=basis.fresh_flow_mol_s*np.asarray(basis.fresh_mole_fractions)
        solvent_index=basis.components.index('Sulfolane')
        for ratio in [.5,1.,2.,4.,8.]:
            self.checkpoint();solvent=np.zeros(len(fresh));solvent[solvent_index]=ratio*sum(fresh)
            model,active=source_lle_active_model(card,fresh+solvent)
            try:
                r,e,flash=contact(model,3.6*(fresh+solvent)[active],308.15,basis.fresh_pressure_Pa,
                    active.index(basis.components.index('Methylcyclohexane')),require_qualified=False)
                hydrocarbon=r[0]+r[1]
                rows.append(dict(solvent_to_fresh_molar_ratio=ratio,raffinate_kmol_h=r.tolist(),
                    extract_kmol_h=e.tolist(),raffinate_hydrocarbon_MCH_mole_fraction=float(r[0]/hydrocarbon),
                    equilibrium=flash))
            except ValueError as error:
                rows.append(dict(solvent_to_fresh_molar_ratio=ratio,error=str(error)))
        evidence=dict(evidence_id=str(uuid4()),source_card=basis.property_cards[0],parameter_sha256=checksum,
            temperature_K=308.15,points=rows,scope='Hypothetical solvent loading single-contact screening. '
            'Hydrocarbon-normalized composition excludes dissolved solvent only for diagnostic interpretation. '
            'Countercurrent stages, recovery, duties and final products still require actual process calculations.')
        save(self.folder/'preflight/lle_loading_knowledge.json',evidence)
        return evidence

    def checkpoint(self):
        self.runtime.check()

    def evidence_aliases(self):
        aliases={}
        if self.phase_knowledge:
            aliases['computed_solvent_vle']=[self.phase_knowledge['evidence_id']]
        if self.lle_knowledge:
            aliases['computed_lle_loading_screen']=[self.lle_knowledge['evidence_id']]
        if self.runtime.initialization_records:
            aliases['available_computational_initializations']=list(self.runtime.initialization_records)[-8:]
        return aliases

    def context(self):
        cards = []
        for name in self.basis.property_cards:
            card, checksum = mixture_card(name)
            cards.append({key: card.get(key) for key in ['model_id', 'model', 'native_names', 'temperature_guard_K',
                'pressure_guard_Pa', 'limitations']} | {'sha256': checksum})
        return dict(frozen_basis=self.basis.model_dump(), initial_topology=None,
            available_evidence_ids=['frozen_basis', *[c['candidate_id'] for c in self.state.candidates],
                *([self.continuation_base['candidate_id']] if self.continuation_base else []),
                *[item['evidence_id'] for item in self.additional_native_evidence],
                *self.evidence_aliases(),
                *self.basis.property_cards, *[card['sha256'] for card in cards], *self.process_skills.cards,
                *([self.preflight['evidence_id']] if self.preflight else []),
                *([self.phase_knowledge['evidence_id']] if self.phase_knowledge else []),
                *([self.lle_knowledge['evidence_id']] if self.lle_knowledge else []),
                *[attempt['evidence_id'] for attempt in self.prior_attempts],
                *self.runtime.initialization_records],
            actual_fresh_property_evidence=self.preflight,
            supplementary_actual_phase_evidence=self.additional_native_evidence,
            computed_solvent_vle=self.phase_knowledge,
            computed_lle_loading_screen=self.lle_knowledge,
            fresh_component_inventory_mol_s={name:self.basis.fresh_flow_mol_s*self.basis.fresh_mole_fractions[i]
                for i,name in enumerate(self.basis.components)},
            required_constraint_stream_roles=({'solvent_rich': 'Actual solvent-rich intermediate with a process path to TOL product',
                'solvent_recycle': 'Actual outlet registered as a tear source and returned to the process'} if self.basis.design_id == 'H02' else {}),
            near_pure_sulfolane_handling=(json.loads((ROOT/'engineering/data/hybrid/sulfolane_solid_phase_reference.json').read_text(encoding='utf8')) if self.basis.design_id == 'H01' else None),
            property_models=cards, previous_candidates=[candidate_counterevidence(candidate)
                for candidate in self.state.candidates[-4:]],
            previous_public_expert_advice=[dict(role=record['role'],recommendation=record['recommendation'][:1800],
                evidence_ids=record['evidence_ids']) for record in self.state.decisions[-3:]],
            prior_autonomous_failures=self.prior_attempts[-3:],
            latest_measured_process=next((attempt for attempt in reversed(self.prior_attempts)
                if any('actual_execution' in candidate for candidate in attempt['candidates'])),None),
            available_computational_initializations=[dict(evidence_id=identifier,
                property_card_id=entry['record']['property_card_id'],
                original_fresh_state_compatible=entry.get('original_fresh_state_compatible',True),
                equilibrium_stages=entry['record']['request']['equilibrium_stages'],
                reflux_ratio=entry['record']['request']['reflux_ratio'],
                actual_outputs={key: entry['record']['outputs'][key] for key in ['distillate', 'bottoms']},
                actual_feed_inventory_mol_s={component:sum(feed['flow_mol_s']*feed['mole_fractions'][index]
                    for feed in entry['record']['request']['feeds']) for index,component in enumerate(self.basis.components)},
                necessary_draw_bound_for_TOL_product_mol_s=(sum(feed['flow_mol_s']*(1-feed['mole_fractions'][self.basis.components.index('Phenol')])
                    for feed in entry['record']['request']['feeds'])/(1-self.basis.requirements['TOL_product_phenol_maximum_mole_fraction'])
                    if self.basis.design_id=='H02' else None),
                scope='Computed within an earlier autonomous attempt. This is starting evidence, and a new native solve plus review is required.')
                for identifier, entry in list(self.runtime.initialization_records.items())[-8:]],
            expert_process_policies=[card.model_dump() | {'procedure': self.process_skills.procedures[name],
                'sha256': self.process_skills.hashes[name]} for name, card in self.process_skills.cards.items()
                if self.basis.design_id == 'H01' or name == 'process_basis'],
            unit_library=dict(column='Multifeed native MESH, distillate/bottoms; explicit feed locations. Choose exactly one draw specification: absolute distillate_flow_mol_s, relative distillate_fraction, or distillate_inventory_components plus distillate_inventory_multiplier. The inventory rule computes draw from actual inlet molar component flows at each recycle iterate, then rigorously verifies it. Clear the other two specifications when changing draw mode. reboiled_absorber has vapor overhead, zero reflux_ratio and an explicit external reflux feed.',
                extraction='Countercurrent NRTL liquid-liquid cascade, two inputs and raffinate/extract outputs.',
                mixer='Isothermal mixing with actual native enthalpy and explicit heat duty.',
                makeup_mixer='Adds pure allowed solvent/water to meet proposed component circulation, then mixes isothermally.',
                auxiliary_feed='No inputs. Supplies an explicitly allowed fresh pure chemical at chosen flow/T/P; all added mass and enthalpy are external inputs.',
                conditioner='Temperature change or pressure reduction with explicit heat duty.',
                pump='Liquid pressure lift with proposed efficiency and explicit outlet thermal conditioning.',
                splitter='Conservative split into first/second.',
                decanter='Native two-liquid split using the LLE card only, at 293.15 to 303.15 K and 8000 to 101325 Pa. Select a supported condensation/wash temperature explicitly. Product assignment may use a directly verified phase without an unnecessary column.'),
            numerical_note='First unit starts are cold. Registered sparse_trust_region is available for columns. '
                'Its numerical_jacobian_policy can be balanced_reduced (damped Newton) or sparse_finite_difference (bounded trust region). '
                'Retained source-tagged native profiles can be resampled onto a revised stage count as numerical guesses. '
                'When an inlet depends on an unclosed recycle, product-inventory bounds are conditional diagnostics. '
                'Only closed-loop original product checks decide final acceptance. '
                'Subsequent iterations may warm-start from independently checked units generated within this same autonomous run. '
                'The simultaneous extraction solver builds numerical guesses from a computed single contact and independently re-flashes every final stage. '
                'Historical accepted designs and source stage profiles are excluded.')

    def run(self):
        self.state.status = 'running'
        try:
            self.runtime.current_folder = self.folder/'preflight'
            self.runtime.current_folder.mkdir()
            self.preflight = self.runtime.equilibrium_port(
                self.basis.fresh_flow_mol_s*np.asarray(self.basis.fresh_mole_fractions),
                self.basis.fresh_temperature_K, self.basis.fresh_pressure_Pa,
                self.basis.property_cards[-1], 'actual_fresh_feed')
            self.phase_knowledge = self.sample_solvent_vle()
            self.lle_knowledge = self.sample_lle_loadings()
            advice = self.ask('thermodynamics expert', HybridExpertAssessment, self.context())
            self.state.decisions.append({'role': 'thermodynamics', **advice.model_dump()})
            for index in range(self.basis.budget.maximum_candidates):
                candidate = dict(candidate_id=f'candidate_{index+1:02d}', status='running')
                try:
                    base=next((old for old in reversed(self.state.candidates) if old.get('graph')),self.continuation_base)
                    if self.basis.budget.incremental_revisions and base:
                        revision=self.ask('engineering expert revising the failed graph with explicit declarative edits',
                            HybridRevision,self.context() | {'revision_base':candidate_counterevidence(base),
                            'revision_instruction':'The latest actual failure overrides earlier advice. Apply changes addressing it. Return only edits referencing this base_candidate_id. All unchanged units and connections are retained.'})
                        revised=apply_revision(revision,base,HybridUnit,HybridGraph)
                        proposal=HybridProposal(graph=revised,evidence_ids=revision.evidence_ids,rationale=revision.rationale)
                        candidate['revision']=revision.model_dump()
                    else:
                        proposal = self.ask('engineering expert constructing a hybrid graph',
                            VLEProposal if self.basis.design_id == 'H02' else HybridProposal, self.context())
                    candidate['graph'] = proposal.graph.model_dump()
                    candidate['rationale'] = proposal.rationale
                    candidate['evidence_ids']=proposal.evidence_ids
                    unknown=set(proposal.evidence_ids)-set(self.context()['available_evidence_ids'])
                    if unknown:
                        raise ValueError('UNKNOWN_EVIDENCE_REFERENCE: '+str(sorted(unknown)))
                    aliases=self.evidence_aliases()
                    candidate['resolved_evidence_ids']=list(dict.fromkeys(reference for name in proposal.evidence_ids
                        for reference in aliases.get(name,[name])))
                    candidate['graph_check'] = validate_hybrid_graph(proposal.graph, self.basis)
                    advisor = self.ask('process advisor inspecting graph preconditions', HybridExpertAssessment,
                        self.context() | {'proposed_graph': proposal.graph.model_dump()})
                    self.state.decisions.append({'role': 'advisor', **advisor.model_dump()})
                    candidate['advisor_advice'] = advisor.model_dump()
                    signature=candidate['graph_check']['design_signature']
                    if any(old.get('graph_check',{}).get('design_signature') == signature for old in self.state.candidates):
                        raise ValueError('UNCHANGED_FAILED_GRAPH: revise a design or numerical choice using the retained failure before another native solve')
                    result = self.runtime.execute(proposal.graph, candidate['candidate_id'])
                    candidate['result'] = result
                    candidate['status'] = 'passed' if result['numerically_closed'] and result['independent_review']['passed'] else 'failed'
                    if candidate['status'] == 'passed':
                        self.state.accepted_candidate_id = candidate['candidate_id']
                except (ValueError, RuntimeError, TimeoutError) as exc:
                    partial=self.folder/candidate['candidate_id']/'partial_execution.json'
                    if partial.exists():
                        data=json.loads(partial.read_text(encoding='utf8'))
                        card,_=mixture_card(self.basis.property_cards[-1]);mw=np.asarray(card['molecular_weights_g_mol'])
                        candidate['partial_execution']=dict(scope=data['scope'],
                            streams={name:{key:port.get(key) for key in ['flow_mol_s','mole_fractions','temperature_K','pressure_Pa']} |
                                {'mass_fractions':(np.asarray(port['mole_fractions'])*mw/(np.asarray(port['mole_fractions'])@mw)).tolist()}
                                for name,port in data['streams'].items()},
                            unit_failures=[{**row,'error':row.get('error','')[:800]} for row in data['unit_failures']])
                    message=str(exc)
                    if len(message)>6000:
                        message=message[:2000]+'\n[complete native error in failure sidecar]\n'+message[-4000:]
                    candidate.update(status='failed', error=type(exc).__name__+': '+message)
                self.state.candidates.append(candidate)
                self.emit('candidate_end', candidate=candidate)
                if self.state.accepted_candidate_id:
                    break
                if 'BUDGET' in candidate.get('error', ''):
                    break
            self.state.status = 'passed' if self.state.accepted_candidate_id else 'failed'
        except (ValueError, RuntimeError, TimeoutError) as exc:
            self.state.status = 'blocked'
            self.state.questions.append(type(exc).__name__+': '+str(exc))
        integrity = all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == value for name, value in self.source_manifest.items())
        integrity=integrity and all(hashlib.sha256(Path(item['source']).read_bytes()).hexdigest()==item['sha256']
            for item in self.additional_native_evidence)
        if not integrity:
            self.state.status = 'blocked'
            self.state.accepted_candidate_id = None
            self.state.questions.append('SOURCE_CHANGED_DURING_RUN')
        save(self.folder/'result.json', self.state.model_dump() | {'source_integrity_passed': integrity})
        self.persist()
        return self.state
