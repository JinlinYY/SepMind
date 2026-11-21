"""Engineering endpoints on the original PHA session service and FastAPI app."""

import asyncio
import csv
import io
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field
from sepmind.engineering.schemas import Contract,DesignBasis
from sepmind.engineering.tools import EngineeringToolRegistry
from sepmind.engineering.skills import ExpertSkillRegistry

router = APIRouter(prefix="/engineering",tags=["PHA engineering extension"])
ROOT = Path(__file__).resolve().parents[1]


class RunRequest(Contract):
    message: str = Field(default="执行当前设计依据",max_length=20000)
    task_updates: dict | None = None


def session_for(identifier):
    from .main import sessions
    session = sessions.get(identifier)
    if session is None or session.config.workspace != "engineering":
        raise HTTPException(status_code=404,detail="Engineering session not found")
    return session


@router.get("/capabilities")
async def capabilities():
    skills = ExpertSkillRegistry()
    return {"derived_from":"Google-Health/consumer-health-research/personal_health_agent",
            "providers":["deepseek","qwen","deterministic"],
            "default_provider":"deepseek",
            "default_model":os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash",
            "tools":EngineeringToolRegistry().capabilities(), "qualified_models":["Raoult","NRTL"],
            "qualified_component_pairs":[["142-82-5","111-84-2"],["64-17-5","7732-18-5"]],
            "autonomous_scheme_synthesis":True,
            "flowsheet_topology_synthesis":{"implemented":True,
                "scope":"bounded acyclic ideal multicomponent distillation graphs",
                "endpoint":"/api/engineering/topology/runs",
                "unit_library":["equilibrium_distillation_column"]},
            "runtime_expert_skills":len(skills.cards),
            "expert_knowledge_hash":skills.knowledge_hash,
            "NRTL_scope":"ethanol/water 101.320 +/- 0.025 kPa; 350-374 K project screening guard; measured-data check, source fit T limits unpublished",
            "available_architectures":["expert_guided"],
            "engineering_baseline_comparison_qualified":False,
            "energy_hydraulics_equipment_implemented":True,
            "design_levels":["preliminary_process","preliminary_equipment"],
            "rigorous_column_backend":"native DWSIM fixed-design equilibrium column with bounded redesign",
            "full_hydraulic_validation":False,"vendor_equipment_selection":False,
            "equipment_assumptions":"explicit agent-proposed estimates, editable in design_basis.equipment",
            "scope":"binary process screening plus optional native MESH, enthalpy balance and preliminary equipment estimates",
            "process_extension":{"families":["liquid_liquid_extraction","extraction_distillation"],
                "implemented_scope":"conditional ternary isothermal LLE and bounded crosscurrent/countercurrent extraction section",
                "complete_hybrid_design":False,"qualified_lle_model":"acid_lle_colombo1999_v1",
                "pending":["qualified downstream VLE/vapour association","regeneration and full recycle","hybrid energy and equipment"]}}


@router.get('/skills')
async def expert_skills():
    skills = ExpertSkillRegistry()
    return {'knowledge_hash':skills.knowledge_hash,
            'skills':[card.model_dump() | {'sha256':skills.hashes[card.skill_id],
                       'procedure':skills.procedures[card.skill_id]} for card in skills.cards.values()]}


@router.post('/equipment-policy')
async def equipment_policy(basis: DesignBasis):
    from sepmind.engineering.design.equipment import equipment_policy_for
    options,origin=equipment_policy_for(basis)
    return {'equipment':options.model_dump(),'origin':origin,
            'scope':'teaching assumptions only; no process computation or LLM call is performed'}


@router.get("/example")
async def example(case: str = 'water_ethanol'):
    if case in ('case-5','case-6'):
        return json.loads((ROOT/'case/curated/hybrid-extraction-distillation'/case/'process_input.json').read_text(encoding='utf8'))
    if case in ('case-1a','case-1b','case-2','case-3'):
        return json.loads((ROOT/'case/curated'/case/'agent_input.json').read_text(encoding='utf-8'))
    names = {'water_ethanol':'water_ethanol_autonomous.json','heptane_nonane':'heptane_nonane.json'}
    if case not in names:
        raise HTTPException(status_code=404,detail='Unknown qualified example')
    return json.loads((ROOT/'engineering/examples'/names[case]).read_text(encoding='utf-8'))


@router.get("/sessions/{identifier}/state")
async def state(identifier: str):
    session = session_for(identifier)
    agent = session.agent
    from sepmind.engineering.schemas import DesignBasis
    from sepmind.engineering.tools.registry import missing_specifications
    from sepmind.engineering.workflow.intake import describe_missing
    from sepmind.engineering.schemas.process import parse_process_basis, ProcessDesignBasis
    from sepmind.engineering.tools.process import missing_process_inputs
    basis = agent.basis if agent is not None else parse_process_basis(session.config.engineering_basis or {})
    process=isinstance(basis,ProcessDesignBasis)
    missing=missing_process_inputs(basis) if process else missing_specifications(basis)
    return {"session_id":identifier,"run":agent.state.model_dump() if agent and agent.state else None,
            'design_basis':basis.model_dump(),'missing_fields':missing,'missing_inputs':missing if process else describe_missing(missing),
            "run_history":[{"run_id":s.run_id,"revision":s.revision,"status":s.status} for s in agent.runs] if agent else []}


@router.post("/sessions/{identifier}/run")
async def run(identifier: str,request: RunRequest):
    session = session_for(identifier)
    if not hasattr(session,"engineering_lock"):
        session.engineering_lock = asyncio.Lock()
    async with session.engineering_lock:
        try:
            await session.send_message(request.message,task_updates=request.task_updates)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from exc
    return await state(identifier)


@router.get("/sessions/{identifier}/export/{format}")
async def export(identifier: str,format: str):
    session = session_for(identifier)
    state = session.agent.state if session.agent else None
    if state is None:
        raise HTTPException(status_code=409,detail="No actual run to export")
    headers = {"Content-Disposition":f'attachment; filename="{state.run_id}.{format}"'}
    if format == "json":
        return Response(state.model_dump_json(indent=2),media_type="application/json",headers=headers)
    if format == "md":
        return Response(state.report_markdown,media_type="text/markdown; charset=utf-8",headers=headers)
    if format == "csv":
        selected=state.artifacts.get('select_extraction_candidate')
        if selected and selected.status=='success' and selected.validation.get('passed'):
            raw=selected.data['selected_candidate']['raw']
            order=state.artifacts['calculate_process_feed_inventory'].data['component_order']
            output=io.StringIO();writer=csv.writer(output)
            writer.writerow(['stream','component_canonical_id','flow_kmol_h','artifact_id'])
            for stream,key in [('feed','feed_kmol_h'),('solvent','solvent_kmol_h'),('extract','extract_kmol_h'),('raffinate','raffinate_kmol_h')]:
                for component,value in zip(order,raw[key]):writer.writerow([stream,component,value,selected.artifact_id])
            return Response(output.getvalue(),media_type='text/csv',headers=headers)
        artifact = state.artifacts.get("calculate_material_balance")
        if artifact is None or artifact.status != "success" or not artifact.validation.get("passed"):
            raise HTTPException(status_code=409,detail="No validated material balance to export")
        output = io.StringIO();writer = csv.writer(output)
        writer.writerow(["stream","flow_kmol_h","light_key_mole_fraction","heavy_key_mole_fraction","artifact_id"])
        for row in artifact.data["streams"]:
            writer.writerow([row["id"],row["flow_kmol_h"],*row["composition"],artifact.artifact_id])
        return Response(output.getvalue(),media_type="text/csv",headers=headers)
    raise HTTPException(status_code=400,detail="Supported exports: json, csv, md")
