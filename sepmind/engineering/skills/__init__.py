"""Runtime expert skills: eligibility, evidence tests and public decision records.

SKILL.md cards are approved local policies, never executable scripts. They only
bind existing registered tools; numerical adapters remain the source of values.
"""
import hashlib
from pathlib import Path
from typing import Literal
import yaml
from pydantic import Field
from ..schemas import Contract, ExpertSkillRecord
from ..knowledge import assess_models, MODEL_CARDS

SKILL_ROOT = Path(__file__).resolve().parents[3]/'engineering/runtime_skills'


class RuntimeSkill(Contract):
    skill_id: str = Field(pattern=r'^[a-z][a-z0-9_]+$')
    version: str
    title: str
    owner: Literal['thermodynamics','process_advisor','expert_review']
    applies_to: Literal['nonideal','ideal','unsupported','any','failure']
    gates: list[str]
    tools: list[str]
    checks: list[str]
    hypothesis: str


class ExpertSkillRegistry:
    def __init__(self, root=None):
        self.root = Path(root or SKILL_ROOT)
        self.reload()

    def reload(self):
        from ..tools.registry import EngineeringToolRegistry
        cards, procedures, hashes = {},{},{}
        digest = hashlib.sha256(MODEL_CARDS.read_bytes())
        for path in sorted(self.root.glob('*/SKILL.md')):
            raw = path.read_bytes()
            parts = raw.decode('utf-8').split('---',2)
            if len(parts)!=3 or parts[0].strip():
                raise ValueError('INVALID_RUNTIME_SKILL: YAML frontmatter required')
            skill = RuntimeSkill.model_validate(yaml.safe_load(parts[1]))
            if skill.skill_id != path.parent.name or skill.skill_id in cards:
                raise ValueError('INVALID_RUNTIME_SKILL: duplicate/mismatched skill identity')
            if any(tool not in EngineeringToolRegistry.TOOLS or EngineeringToolRegistry.TOOLS[tool][0] not in skill.gates for tool in skill.tools):
                raise ValueError('INVALID_RUNTIME_SKILL: tool bindings must reference registered tools at their actual gates')
            cards[skill.skill_id] = skill
            procedures[skill.skill_id] = parts[2].strip()
            hashes[skill.skill_id] = hashlib.sha256(raw).hexdigest()
            digest.update(path.parent.name.encode()+raw)
        if 'counterevidence_recovery' not in cards:
            raise ValueError('INVALID_RUNTIME_SKILL: counterevidence policy missing')
        self.cards,self.procedures,self.hashes = cards,procedures,hashes
        self.knowledge_hash = digest.hexdigest()

    def context(self, state, gate, tool, owner):
        assessment = assess_models(state.basis)
        selected = state.basis.thermodynamic_model or assessment['selected_model']
        family = 'nonideal' if selected=='NRTL' else 'ideal' if selected=='Raoult' else 'unsupported'
        skills = []
        for card in self.cards.values():
            if card.owner != owner or gate not in card.gates or tool not in card.tools:
                continue
            if card.applies_to not in ('any',family):
                continue
            skills.append(card.model_dump() | {'procedure':self.procedures[card.skill_id],
                                                'sha256':self.hashes[card.skill_id]})
        if not skills:
            raise ValueError('SKILL_COVERAGE_MISSING: no eligible expert policy for '+tool)
        return {'eligible_skills':skills,'model_assessment':assessment,
                'instruction':'Choose one eligible skill_id. Apply its checks and keep its stated limitations; the executor will verify numerical evidence.'}

    def observe(self, state, gate, tool, context, skill_id, result):
        allowed = {s['skill_id'] for s in context['eligible_skills']}
        if skill_id not in allowed:
            raise ValueError('SKILL_PRECONDITION: ineligible skill cannot claim this result')
        card = self.cards[skill_id]
        passed = result.status=='success' and result.validation.get('passed') is True
        assessment = context['model_assessment']
        limits = [limit for c in assessment['model_options'] if c['model']==assessment['selected_model']
                  for limit in c['limitations']]
        observations = {'tool_status':result.status,'error_type':result.error_type,
                        'verification':result.validation,'warnings':result.warnings}
        for name in ('selected_model','minimum_reflux_ratio','conditional_feasible',
                     'azeotropic_compositions_under_model','feasible_interval_checked',
                     'selected_reflux_ratio','candidate_id','theoretical_stages_rounded_up','feed_stage_from_top'):
            if name in result.data:
                observations[name] = result.data[name]
        if 'experimental_reference_check' in result.data:
            reference = result.data['experimental_reference_check']
            observations['experimental_reference'] = {k:v for k,v in reference.items() if k!='points'}
            observations['experimental_reference']['point_count'] = len(reference['points'])
        if 'candidates' in result.data:
            observations['computed_candidates'] = result.data['candidates']
        if 'attempts' in result.data:
            observations['rigorous_counterexamples'] = [{k:v for k,v in row.items() if k!='outputs'}
                                                        for row in result.data['attempts']]
        for name in ('selected_candidate','condenser_duty_kW','reboiler_duty_kW',
                     'diameter_m','actual_trays_estimate','unresolved_checks'):
            if name in result.data:
                observations[name]=result.data[name]
        conclusion = ('admitted_for_test' if tool=='select_thermodynamic_model' and passed
                      else 'supported_conditionally' if passed
                      else 'needs_input' if result.status=='needs_input'
                      else 'refuted' if result.error_type in ('FEAS_AZEOTROPE','PROPERTY_REFERENCE_MISMATCH','STAGE_PINCH')
                      else 'blocked')
        record = ExpertSkillRecord(source_run_id=state.run_id,skill_id=card.skill_id,
            skill_version=card.version,skill_sha256=self.hashes[card.skill_id],title=card.title,
            owner=card.owner,gate=gate,tool_name=tool,selected_by=state.provider if state.provider in ('deepseek','qwen') else 'expert_rules',
            hypothesis=card.hypothesis,procedure=self.procedures[card.skill_id],criteria=card.checks,input_facts=assessment['profile'],
            model_options=assessment['model_options'] if tool=='select_thermodynamic_model' else [],
            evidence_before=[state.basis.design_id]+[a.artifact_id for a in state.artifacts.values() if a.status=='success' and a.artifact_id!=result.artifact_id],
            evidence_after=[result.artifact_id]+[e.evidence_id for e in result.evidence],artifact_id=result.artifact_id,
            observations=observations,conclusion=conclusion,
            next_action='continue_only_with_declared_assumptions' if passed else 'invoke_counterevidence_policy',
            limitations=limits+['Numerical self-consistency is not industrial or global phase-stability validation.'])
        state.expert_records.append(record)
        failed_candidates = [c for c in result.data.get('candidates',[])+result.data.get('attempts',[]) if c.get('status') in ('rejected','solver_failed')]
        if not passed or failed_candidates:
            self._counterevidence(state,record,result,failed_candidates)
        return record

    def _counterevidence(self,state,record,result,failed_candidates):
        card = self.cards['counterevidence_recovery']
        actions = {'MODEL_OUT_OF_RANGE':'request_operating_domain_evidence',
                   'DATA_PARAMETER_MISSING':'request_qualified_parameters_or_other_qualified_model',
                   'REQUIRES_REVIEW':'request_explicit_assumptions_or_model_review',
                   'PROPERTY_REFERENCE_MISMATCH':'reject_parameter_hypothesis_and_review_model',
                   'FEAS_AZEOTROPE':'reject_ordinary_column_and_review_alternative_routes',
                   'SOURCE_CONFLICT':'reconcile_conflicting_inputs_before_recomputation',
                   'STAGE_PINCH':'review_reflux_or_stage_constraints'}
        action = ('exclude_rejected_computed_candidates' if failed_candidates else
                  actions.get(result.error_type,'stop_and_review_evidence'))
        state.expert_records.append(ExpertSkillRecord(source_run_id=state.run_id,skill_id=card.skill_id,
            skill_version=card.version,skill_sha256=self.hashes[card.skill_id],title=card.title,
            owner=card.owner,gate=record.gate,tool_name=record.tool_name,selected_by='counterevidence_rule',
            hypothesis=card.hypothesis,procedure=self.procedures[card.skill_id],criteria=card.checks,artifact_id=result.artifact_id,
            input_facts=record.input_facts,evidence_before=[result.artifact_id],evidence_after=[record.record_id],
            observations={'error_type':result.error_type,'errors':[e.model_dump() for e in result.errors],
                          'rejected_candidates':failed_candidates,'alternatives':result.data.get('alternatives',[])},
            conclusion='supported_conditionally' if failed_candidates else record.conclusion,
            next_action=action,action_status='constraint_applied' if failed_candidates else 'recommendation_only',
            limitations=['A recommendation to acquire data or change route has not itself executed a new process design.']))
