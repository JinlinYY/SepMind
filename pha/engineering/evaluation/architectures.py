"""Explicit planning topologies over identical registered physical computations.

Role variants change the candidate-planning message graph, not DWSIM physics.
All have access to the same bounded-redesign tool and hard safety/physics checks.
The paired supervisor_guided arm adds runtime Skill contexts and observations.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import copy
import json,threading
from pydantic import Field
from ..agents.orchestrator import EngineeringOrchestrator
from ..schemas import Contract

ROLES=('thermodynamics','calculation','process_advisor')
METHODS=('sepmind','pipeline_roles','parallel_roles','supervisor_roles',
         'hierarchical_roles','peer_roles','adaptive_graph_roles','supervisor_guided')
INSTRUCTIONS={
 'thermodynamics':'Review thermodynamic admissibility, phase limits, model assumptions and achievable separation.',
 'calculation':'Review computed stages, operating constraints, material balance, vapor load and numerical feasibility.',
 'process_advisor':'Select a defensible preliminary process scheme, considering separation targets and stage/load tradeoffs.'}


class CandidateProposal(Contract):
    candidate_id:str
    rationale:str=Field(min_length=1,max_length=4000)
    concerns:list[str]=Field(default_factory=list,max_length=12)
    evidence_ids:list[str]=Field(default_factory=list,max_length=40)


class Delegation(Contract):
    role_order:list[str]=Field(min_length=3,max_length=3)
    rationale:str=Field(min_length=1,max_length=3000)


class PlanningGraph(Delegation):
    edges:list[list[str]]=Field(default_factory=list,max_length=3)


class ArchitectureOrchestrator(EngineeringOrchestrator):
    def __init__(self,*args,architecture,**kwargs):
        if architecture not in METHODS or architecture=='sepmind':raise ValueError('Use the original orchestrator for the sepmind arm')
        self.architecture=architecture
        self.guided=architecture=='supervisor_guided'
        self.coordination_log=[];self._budget_lock=threading.Lock()
        super().__init__(*args,**kwargs)

    def _skill_context(self,state,gate,tool):
        return super()._skill_context(state,gate,tool) if self.guided else None

    def _query(self,state,role,context,schema=CandidateProposal):
        for attempt in range(2):
            try:return self._query_once(state,role,context,schema)
            except ValueError as exc:
                with self._budget_lock:
                    state.rejected_planner_proposals.append({'gate':'G4','tool_name':'select_process_design',
                        'role':role,'attempt':attempt+1,'reason':str(exc)[:1500]})
                if attempt or str(exc).startswith('LLM_BUDGET'):raise
                context={**context,'rejected_proposal_feedback':str(exc)[:1500],
                         'correction_instruction':'Correct your structured proposal using only actual roles, feasible candidates and available evidence.'}

    def _query_once(self,state,role,context,schema=CandidateProposal):
        with self._budget_lock:
            if state.llm_calls>=self.max_llm_calls:raise ValueError('LLM_BUDGET: architecture planner exhausted')
            state.llm_calls+=1;index=state.llm_calls
        prompt=('You are a chemical separation design '+role+'. '+INSTRUCTIONS.get(role,'Coordinate expert reports and select a defensible computed candidate.')+
                '\nReturn exactly one JSON object matching the schema. Use only supplied candidate/evidence identifiers. '
                'All reported physical quantities must already exist in the tool evidence. '
                'All arms have the same registered numerical tools, bounded native redesign and independent checks. '
                'Do not claim global optimality.\n'+json.dumps({'context':context,'output_schema':schema.model_json_schema()},ensure_ascii=False))
        backend=copy(self._backend);backend.last_response_info=None
        raw=backend.generate(prompt)
        metadata=getattr(backend,'last_response_info',{}) or {}
        with self._budget_lock:
            state.provider_events.append({k:v for k,v in metadata.items() if k in {'provider','requested_model','served_model','request_id','response_id','usage'}})
            self.coordination_log.append({'call':index,'role':role,'context':context,'response':raw,
                                          'metadata':{k:v for k,v in metadata.items() if k!='api_key'}})
        result=schema.model_validate_json(self._clear_json_format(raw))
        if isinstance(result,CandidateProposal):
            allowed={r['candidate_id'] for r in context['computed_candidates'] if r['status']=='feasible'}
            if result.candidate_id not in allowed:raise ValueError('INVALID_DESIGN_SELECTION: planner proposed a non-feasible candidate')
            if not set(result.evidence_ids)<=set(context['available_evidence_ids']):raise ValueError('EVIDENCE_PRECONDITION: unknown planner citation')
        else:
            if set(result.role_order)!=set(ROLES):raise ValueError('INVALID_DELEGATION: each actual specialist must appear exactly once')
            if isinstance(result,PlanningGraph):
                order={r:i for i,r in enumerate(result.role_order)}
                if any(len(e)!=2 or any(x not in order for x in e) or order[e[0]]>=order[e[1]] for e in result.edges):
                    raise ValueError('INVALID_GRAPH: use acyclic forward edges over the three actual roles')
        return result.model_dump()

    def _gate(self,state,gate,tools):
        result=super()._gate(state,gate,tools)
        if self.guided:
            for record in state.expert_records:
                if record.selected_by!='counterevidence_rule':record.selected_by='expert_rules'
        return result

    def _decide(self,state,gate,tool,skill_context=None):
        skill=skill_context['eligible_skills'][0]['skill_id'] if skill_context else None
        if tool!='select_process_design':
            return 'Execute the shared registered tool and hard physical/data validation; candidate-planning topology is controlled separately.',skill
        choices=state.artifacts['explore_reflux_candidates'].data
        if not choices.get('candidates'):return 'User-specified operating condition retained.',skill
        # Input source labels are legitimate, separately identified provenance,
        # not invented solver evidence. Accept them consistently in all planners.
        refs=sorted(set(state.basis.source_ids)|{x for a in state.artifacts.values() for x in [a.artifact_id]+[e.evidence_id for e in a.evidence]})
        context={'basis':state.basis.model_dump(),'computed_candidates':choices['candidates'],
                 'screening_policy':choices.get('policy'),'available_evidence_ids':refs,
                 'available_tools':[{'name':name,'gate':g} for name,(g,_) in self.calculation_agent.registry.TOOLS.items()],
                 'shared_validation':'Fixed source-qualified model/parameter guards; original strict product targets; native MESH and independent closure; bounded redesign available to every arm.',
                 'output_task':'Choose a feasible candidate_id from the actual numerical candidates; explain stage/load tradeoffs.'}
        context['citation_instruction']='evidence_ids may contain only exact available_evidence_ids; candidate identifiers are not citations; use [] when unsure.'
        if self.guided:context['expert_skill_context']=skill_context
        architecture='supervisor_roles' if self.guided else self.architecture
        reports=[]
        if architecture in ('parallel_roles','peer_roles','hierarchical_roles'):
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(self._query,state,role,dict(context)) for role in ROLES]
                reports=[f.result() for f in futures]
        elif architecture=='pipeline_roles':
            for role in ROLES:reports.append(self._query(state,role,{**context,'previous_reports':reports.copy()}))
        else:
            graph=architecture=='adaptive_graph_roles'
            delegated=self._query(state,'supervisor',{**context,'delegation_task':'Choose role_order containing each role once; for a graph add only acyclic forward information-sharing edges.','roles':list(ROLES)},PlanningGraph if graph else Delegation)
            report_by_role={}
            for role in delegated['role_order']:
                parents=[a for a,b in delegated.get('edges',[]) if b==role] if graph else list(report_by_role)
                reports.append(self._query(state,role,{**context,'upstream_reports':{p:report_by_role[p] for p in parents}}))
                report_by_role[role]=reports[-1]
        if architecture=='peer_roles':
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(self._query,state,role,{**context,'peer_reports':reports,'task':'Review peers and submit your final candidate vote.'}) for role in ROLES]
                votes=[f.result() for f in futures]
            counts=Counter(v['candidate_id'] for v in votes)
            default_order={r['candidate_id']:i for i,r in enumerate(choices['candidates'])}
            winner=min(counts,key=lambda k:(-counts[k],default_order[k]))
            final=next(v for v in votes if v['candidate_id']==winner)
        else:
            if architecture=='hierarchical_roles':
                reports=[self._query(state,'technical_lead',{**context,'team_reports':reports[:2]}),
                         self._query(state,'process_lead',{**context,'team_reports':reports[2:]})]
            final=self._query(state,'supervisor',{**context,'specialist_reports':reports,'task':'Synthesize the reports and select a feasible computed scheme.'})
        state.design_preferences={'candidate_id':final['candidate_id'],'rationale':final['rationale']}
        return final['rationale'],skill
