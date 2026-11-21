"""Registered tools used by the retained PHA calculation specialist."""
from pydantic import Field
from ..schemas import Contract, ToolResult
from .schemas import TopologyDesignBasis, IDEAL_COMPONENTS
from .graph import digest, validate_graph, screen_product_flow_bounds


class TopologyToolInput(Contract):
    basis: TopologyDesignBasis


class TopologyToolRegistry:
    input_contract = TopologyToolInput
    component_identities = IDEAL_COMPONENTS
    calculation_assumptions = ['explicit_ideal_liquid_and_vapor', 'zero_column_pressure_drop']
    TOOLS = {name: (gate, TopologyToolInput) for name, gate in [
        ('admit_topology_task', 'G0'), ('validate_topology_graph', 'G1'),
        ('execute_topology', 'G4'), ('review_topology', 'G8')]}

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, name, state, gate, arguments):
        if name not in self.TOOLS or self.TOOLS[name][0] != gate:
            raise ValueError('UNREGISTERED_TOPOLOGY_TOOL')
        parsed = self.input_contract.model_validate(arguments)
        if digest(parsed.basis.model_dump()) != self.runtime.basis_hash:
            raise ValueError('IMMUTABLE_REQUIREMENTS')
        self.runtime.check()
        result = ToolResult(status='success', tool_name=name, run_id=state.run_id,
                            assumptions=self.calculation_assumptions,
                            units={'flow': 'mol/s', 'pressure': 'Pa', 'duty': 'kW'},
                            source_or_run=state.run_id)
        try:
            if name == 'admit_topology_task':
                result.data = {'basis_sha256': self.runtime.basis_hash,
                    'component_CAS': {name: self.component_identities[name] for name in state.basis.components},
                    'property_package': state.basis.property_package,
                    'assumption_source': state.basis.ideality_assumption_source,
                    'scope': state.scope, 'experimental_property_qualification': False}
            elif name == 'validate_topology_graph':
                if 'admit_topology_task' not in state.artifacts:
                    raise ValueError('TASK_ADMISSION_REQUIRED')
                result.data = validate_graph(state.graph, state.basis)
                result.data['inventory_screen'] = screen_product_flow_bounds(state.graph, state.basis)
                if not result.data['inventory_screen']['passed']:
                    raise ValueError('PRODUCT_FLOW_BOUND: proposed outlet flows conflict with frozen purity or recovery requirements; inspect computed inventory bounds')
            elif name == 'execute_topology':
                validation = state.artifacts.get('validate_topology_graph')
                if not validation or not validation.validation.get('passed') or validation.data['design_signature'] != validate_graph(state.graph, state.basis)['design_signature']:
                    raise ValueError('GRAPH_REVALIDATION_REQUIRED')
                result.data = self.runtime.execute(state.graph, self.runtime.candidate_id)
            else:
                execution = state.artifacts.get('execute_topology')
                if not execution or execution.status != 'success':
                    raise ValueError('COMPLETE_EXECUTION_REQUIRED')
                result.data = self.runtime.review(state.graph, execution.data)
            result.validation = {'passed': result.data.get('passed', True), 'scope': state.scope}
        except (ValueError, RuntimeError, TimeoutError) as exc:
            result.status = 'failed'
            result.error_type = type(exc).__name__
            result.diagnostics = {'error': str(exc)[:5000]}
            result.validation = {'passed': False}
        state.tool_calls += 1
        state.artifacts[name] = result
        return result
