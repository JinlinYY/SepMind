"""PHA-derived three-specialist topology proposal and calculation loop."""
import copy
import json
import hashlib
import os
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4
from sepmind.llm.backend_multimodel import DeepSeekBackend, QwenBackend
from sepmind.llm.local_credentials import deepseek_key
from ..agents.orchestrator import EngineeringOrchestrator
from ..agents.specialists import EngineeringCalculationAgent
from ..schemas import ToolResult
from ..tools.atomic_recovery import save
from separation.tools.multicomponent import MultiComponentDwsimBackend
from .schemas import TopologyDesignBasis, TopologyRunState, TopologyProposal, ExpertAssessment, FlowsheetGraph
from .skills import TopologySkillRegistry, ROOT
from .tools import TopologyToolRegistry
from .executor import TopologyRuntime, TopologyBudgetExceeded
from .graph import digest


def create_topology_backend(provider='deepseek'):
    if provider == 'deepseek':
        key = deepseek_key() or os.environ.get('DEEPSEEK_API_KEY')
        return DeepSeekBackend(api_key=key, model_name=os.environ.get('DEEPSEEK_MODEL') or 'deepseek-flash',
                               temperature=.2, max_tokens=3200, json_mode=True, timeout_s=60)
    if provider == 'qwen':
        return QwenBackend(temperature=.2, max_tokens=3200, json_mode=True, timeout_s=60)
    raise ValueError('Topology provider must be DeepSeek or Qwen')


class TopologySynthesisOrchestrator(EngineeringOrchestrator):
    basis_contract = TopologyDesignBasis
    state_contract = TopologyRunState
    runtime_class = TopologyRuntime
    registry_class = TopologyToolRegistry
    proposal_contract = TopologyProposal
    graph_contract = FlowsheetGraph
    allow_initial_counterevidence = False
    excluded_source_files = ()
    extra_source_files = ()
    thermodynamic_gate_reason = 'Explicit ideal hypothesis in the registered native component and pressure domain'

    def __init__(self, basis, backend, output_dir=None, native_backend=None, stop_event=None):
        if getattr(backend, 'provider', None) not in ('deepseek', 'qwen'):
            raise ValueError('Topology synthesis requires a DeepSeek or Qwen backend')
        parsed = self.basis_contract.model_validate(basis)
        folder = Path(output_dir or ROOT/'output/engineering/topology_runs'/str(uuid4())).resolve()
        if not folder.is_relative_to(ROOT/'output'):
            raise ValueError('Topology outputs must stay in the workspace output directory')
        folder.mkdir(parents=True, exist_ok=False)
        super().__init__(backend=backend, output_dir=folder,
                         max_llm_calls=parsed.budget.maximum_llm_calls)
        self.state = self.state_contract(basis=parsed)
        self.state.run_id = folder.name
        self.basis = parsed
        self.topology_skills = TopologySkillRegistry()
        self.stop_event = stop_event or threading.Event()
        self.runtime = self.runtime_class(self.state, folder, native_backend or MultiComponentDwsimBackend(
            timeout_s=parsed.budget.native_timeout_s), self.emit, stop_event=self.stop_event)
        self.calculation_agent = EngineeringCalculationAgent(self.registry_class(self.runtime))
        self.set_agents(data_science_agent=self.calculation_agent, domain_expert_agent=self.thermodynamics_agent,
                        health_coach_agent=self.advisor_agent)
        self.policy = (ROOT/'engineering/prompts/TOPOLOGY_SYNTHESIS.md').read_text(encoding='utf8')
        self.folder = folder
        self.event_index = 0
        self.thermodynamic_advice = None
        files = [path for path in (ROOT/'sepmind/engineering/topology').glob('*.py') if path.name not in self.excluded_source_files]
        files += [ROOT/name for name in self.extra_source_files]
        files += list((ROOT/'sepmind/engineering/schemas').glob('*.py'))
        files += list((ROOT/'sepmind/engineering/skills').glob('*.py'))
        files += list((ROOT/'engineering/topology_skills').glob('*/SKILL.md'))
        files += [ROOT/path for path in [
            'engineering/prompts/TOPOLOGY_SYNTHESIS.md', 'engineering/contracts/topology_tool_registry.yaml',
            'separation/tools/multicomponent.py', 'separation/tools/_dwsim_worker.py',
            'sepmind/engineering/validation/dwsim_column.py', 'sepmind/llm/backend_multimodel.py',
            'sepmind/engineering/validation/dwsim_mixture.py', 'sepmind/llm/local_credentials.py',
            'sepmind/engineering/tools/atomic_recovery.py', 'separation/tools/dwsim.py',
            'sepmind/agents/orchestrator.py', 'sepmind/engineering/agents/orchestrator.py',
            'sepmind/engineering/agents/specialists.py']]
        self.source_manifest = {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in files}
        self.state.implementation_sha256 = digest(self.source_manifest)
        save(folder/'source_manifest.json', self.source_manifest)
        with zipfile.ZipFile(folder/'source_snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as snapshot:
            for path in files:
                snapshot.write(path, path.relative_to(ROOT))
        save(folder/'input.json', {'basis': parsed.model_dump(), 'initial_topology': None,
                                  'knowledge_sha256': self.topology_skills.knowledge_hash,
                                  'implementation_sha256': self.state.implementation_sha256,
                                  'provider': backend.provider})
        self.persist()

    def emit(self, kind, **data):
        self.event_index += 1
        event = {'event': self.event_index, 'kind': kind, 'elapsed_s': time.monotonic()-self.runtime.started, **data}
        with (self.folder/'events.jsonl').open('a', encoding='utf8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False)+'\n')
        self.persist()

    def persist(self):
        save(self.folder/'state.json', self.state.model_dump())

    def checkpoint(self):
        self.runtime.check()
        if self.stop_event.is_set():
            raise TopologyBudgetExceeded('STOP_REQUESTED')

    def ask(self, role, contract, context):
        self.checkpoint()
        if self.state.llm_calls >= self.basis.budget.maximum_llm_calls:
            raise TopologyBudgetExceeded('LLM_CALL_BUDGET')
        self.state.llm_calls += 1
        prompt = (self.policy+'\nRole\n'+role+'\nOutput schema\n'+json.dumps(contract.model_json_schema())+
                  '\nEvidence data\n'+json.dumps(context, ensure_ascii=False))
        self.emit('llm_start', role=role, request_index=self.state.llm_calls, prompt=prompt)
        start = time.monotonic()
        raw = self._call_llm(prompt, max_retries=1)
        metadata = getattr(self._backend, 'last_response_info', None) or {}
        metadata = {key: copy.deepcopy(value) for key, value in metadata.items()
                    if key in ['provider', 'requested_model', 'served_model', 'request_id', 'response_id', 'usage']}
        self.state.provider_events.append(metadata)
        self.emit('llm_end', role=role, response=raw, metadata=metadata, duration_s=time.monotonic()-start)
        if raw.startswith('Error:'):
            raise RuntimeError('LLM_PROVIDER_ERROR: '+raw[:1000])
        return contract.model_validate_json(self._clear_json_format(raw))

    def tool(self, name, gate):
        self.checkpoint()
        self.state.gates[gate].status = 'running'
        self.emit('tool_start', tool=name, gate=gate)
        result = self.calculation_agent.execute(self.state, gate, name)
        stage = self.state.gates[gate]
        stage.artifact_ids = [result.artifact_id]
        stage.status = 'passed' if result.validation.get('passed') else 'failed'
        stage.reason = result.diagnostics.get('error', result.data.get('scope', self.state.scope))
        if name == 'validate_topology_graph' and result.status == 'success':
            stage.status = 'ready'
            stage.reason = 'Graph connectivity admitted for numerical testing'
        self.emit('tool_end', tool=name, gate=gate, result=result.model_dump())
        return result

    def context(self):
        references = [self.state.artifacts['admit_topology_task'].artifact_id]
        references += [candidate['candidate_id'] for candidate in self.state.candidates]
        history = [{key: candidate.get(key) for key in ['candidate_id', 'status', 'graph', 'review',
                    'error', 'topology_signature', 'change_kind', 'graph_checks', 'advisor_advice']} for candidate in self.state.candidates]
        verified = {candidate['topology_signature'] for candidate in self.state.candidates if candidate['status'] == 'passed'}
        instruction = ('A verified design exists. The next graph must have different connectivity or product routing to satisfy the requested topology comparison.'
                       if verified and len(verified) < self.basis.budget.desired_verified_topologies else
                       'Obtain a verified design. Use computed inventory and product failures to revise draw hypotheses, stages, reflux, or connectivity.')
        return {'frozen_basis': self.basis.model_dump(), 'initial_topology': None,
                'registered_unit_library': {'distillation_column': 'one input, distillate and bottoms; total condenser and partial reboiler included'},
                'skills': self.topology_skills.context(), 'available_evidence_ids': references,
                'thermodynamic_advice': self.thermodynamic_advice,
                'previous_candidates': history,
                'search_instruction': instruction,
                'budget_remaining': {'llm': self.basis.budget.maximum_llm_calls-self.state.llm_calls,
                                     'native': self.basis.budget.maximum_native_calls-self.state.native_calls}}

    def run(self, message='Synthesize a flowsheet from the supplied feed and product requirements'):
        with self._run_lock:
            if self.state.status != 'ready':
                raise ValueError('IMMUTABLE_RUN: create a new run for another synthesis')
            self.state.status = 'running'
            accepted = []
            try:
                admitted = self.tool('admit_topology_task', 'G0')
                if not admitted.validation.get('passed'):
                    raise ValueError('TASK_ADMISSION_FAILED')
                self.state.gates['G2'].status = 'passed'
                self.state.gates['G2'].reason = self.thermodynamic_gate_reason
                advice = self.ask('thermodynamics expert', ExpertAssessment, self.context())
                if not set(advice.evidence_ids).issubset(self.context()['available_evidence_ids']):
                    raise ValueError('FABRICATED_EXPERT_EVIDENCE')
                self.thermodynamic_advice = advice.model_dump()
                self.state.decisions.append({'role': 'thermodynamics', **advice.model_dump()})
                for index in range(self.basis.budget.maximum_candidates):
                    self.checkpoint()
                    identifier = f'candidate_{index+1:02d}'
                    self.runtime.candidate_id = identifier
                    candidate = {'candidate_id': identifier, 'status': 'running'}
                    context = self.context()
                    try:
                        proposal = self.ask('engineering expert constructing a graph', self.proposal_contract,
                                            context | {'task_message': message})
                        eligible_skills = {'topology_construction'} if index == 0 and not self.allow_initial_counterevidence else {'topology_construction', 'topology_counterevidence'}
                        if proposal.skill_id not in eligible_skills or not proposal.evidence_ids or not set(proposal.evidence_ids).issubset(context['available_evidence_ids']):
                            raise ValueError('EXPERT_BINDING: cite existing evidence and the applicable topology skill')
                        self.state.graph = proposal.graph
                        candidate['graph'] = proposal.graph.model_dump()
                        self.state.decisions.append({'candidate_id': identifier, 'role': 'engineering',
                                                     'rationale': proposal.rationale, 'skill_id': proposal.skill_id,
                                                     'evidence_ids': proposal.evidence_ids})
                        self.emit('graph_proposed', candidate_id=identifier, graph=candidate['graph'], rationale=proposal.rationale)
                        for gate in ['G1', 'G4', 'G8']:
                            self.state.gates[gate].status = 'not_started'
                        validated = self.tool('validate_topology_graph', 'G1')
                        candidate['graph_checks'] = validated.data
                        if not validated.validation.get('passed'):
                            raise ValueError(validated.diagnostics.get('error', 'INVALID_TOPOLOGY'))
                        signature = validated.data['topology_signature']
                        if any(c.get('design_signature') == validated.data['design_signature'] and c.get('execution_started') for c in self.state.candidates):
                            raise ValueError('DUPLICATE_DESIGN: revise topology or numerical design hypotheses')
                        if accepted and signature in {candidate['topology_signature'] for candidate in accepted}:
                            raise ValueError('DISTINCT_TOPOLOGY_REQUESTED: generate different connectivity or product routing for the declared search comparison')
                        candidate.update(topology_signature=signature, design_signature=validated.data['design_signature'],
                            change_kind='parameter_revision' if any(c.get('topology_signature') == signature for c in self.state.candidates) else 'new_topology')
                        advisor = self.ask('process design advisor reviewing proposed connectivity and providing evidence-grounded advice for subsequent revisions', ExpertAssessment,
                            context | {'proposed_graph': candidate['graph'], 'computed_graph_checks': validated.data})
                        if not set(advisor.evidence_ids).issubset(context['available_evidence_ids']):
                            raise ValueError('FABRICATED_ADVISOR_EVIDENCE')
                        self.state.decisions.append({'candidate_id': identifier, 'role': 'process_advisor', **advisor.model_dump()})
                        candidate['advisor_advice'] = advisor.model_dump()
                        candidate['execution_started'] = True
                        execution = self.tool('execute_topology', 'G4')
                        if execution.status != 'success':
                            raise RuntimeError(execution.diagnostics.get('error', 'EXECUTION_FAILED'))
                        review = self.tool('review_topology', 'G8')
                        candidate['review'] = review.data
                        candidate['status'] = 'passed' if review.validation.get('passed') else 'failed'
                        if review.status != 'success':
                            candidate['error'] = review.diagnostics.get('error', 'REVIEW_FAILED')
                        candidate['artifacts'] = {name: result.model_dump() for name, result in self.state.artifacts.items()}
                        if candidate['status'] == 'passed':
                            accepted.append(candidate)
                    except (ValueError, RuntimeError, TimeoutError) as exc:
                        candidate.update(status='failed', error=type(exc).__name__+': '+str(exc)[:5000])
                    self.state.candidates.append(candidate)
                    self.emit('candidate_end', candidate=candidate)
                    if len({c['topology_signature'] for c in accepted}) >= self.basis.budget.desired_verified_topologies:
                        break
                    if 'BUDGET' in candidate.get('error', '') or 'LLM_PROVIDER_ERROR' in candidate.get('error', ''):
                        self.state.questions.append(candidate['error'])
                        break
                self.state.status = 'failed'
            except (ValueError, RuntimeError, TimeoutError) as exc:
                self.state.status = 'blocked'
                self.state.questions.append(type(exc).__name__+': '+str(exc)[:2000])
            if accepted:
                selected = min(accepted, key=lambda c: (c['review']['duties']['reboiler_kW'], len(c['graph']['columns'])))
                self.state.accepted_candidate_id = selected['candidate_id']
                self.state.graph = self.graph_contract.model_validate(selected['graph'])
                self.state.artifacts = {name: ToolResult.model_validate(value) for name, value in selected['artifacts'].items()}
                self.state.status = 'passed'
                for gate in ['G1', 'G4', 'G8']:
                    self.state.gates[gate].status = 'passed'
                    self.state.gates[gate].reason = 'Selected candidate independently verified under the declared model hypothesis'
                    tool_name = {'G1': 'validate_topology_graph', 'G4': 'execute_topology', 'G8': 'review_topology'}[gate]
                    self.state.gates[gate].artifact_ids = [self.state.artifacts[tool_name].artifact_id]
            from .reporting import render_report, render_svg, render_mermaid
            self.state.source_integrity_passed = all((ROOT/name).is_file() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == value
                                                    for name, value in self.source_manifest.items())
            if not self.state.source_integrity_passed:
                self.state.status = 'blocked'
                self.state.accepted_candidate_id = None
                self.state.questions.append('SOURCE_CHANGED_DURING_RUN: create a new immutable run')
                for gate in ['G1', 'G4', 'G8']:
                    self.state.gates[gate].status = 'blocked'
                    self.state.gates[gate].reason = 'Source integrity check failed'
            self.state.report_markdown = render_report(self.state)
            save(self.folder/'result.json', self.state.model_dump())
            (self.folder/'report.md').write_text(self.state.report_markdown, encoding='utf8')
            if self.state.graph is not None:
                (self.folder/'flowsheet.svg').write_text(render_svg(self.state), encoding='utf8')
                (self.folder/'flowsheet.mmd').write_text(render_mermaid(self.state), encoding='utf8')
            self.state.gates['G9'].status = 'passed'
            self.state.gates['G9'].reason = 'Report and computed graph artifacts written'
            self.persist()
            save(self.folder/'result.json', self.state.model_dump())
            return self.state
