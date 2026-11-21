"""Chemical-design endpoints sharing the existing FastAPI application."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator

from sepmind.shortcut.utils.data_schemas import Contract, DesignTask, RunLimits
from sepmind.shortcut.agents import SeparationOrchestrator
from sepmind.shortcut.utils.reporting import render_report, report_data
from sepmind.shortcut.reasoning import VerificationPolicy


router = APIRouter(prefix="/separation", tags=["Chemical separation design"])


class DesignRunRequest(Contract):
    task: DesignTask
    message: str = Field(default="", max_length=20000)
    mode: Literal["rules", "llm"] = "rules"
    provider: Literal["deepseek"] = "deepseek"
    model_name: str | None = Field(default=None, min_length=1)
    limits: RunLimits = Field(default_factory=RunLimits)
    use_few_shots: bool = True
    strategy: Literal["baseline", "hypothesis"] = "baseline"
    verification_policy: VerificationPolicy = Field(default_factory=VerificationPolicy)

    @model_validator(mode="after")
    def model_configuration(self):
        if self.mode == "llm" and self.provider != "deepseek" and not self.model_name:
            raise ValueError("This provider requires model_name; keys stay in server environment variables.")
        return self


@router.get("/capabilities")
async def capabilities():
    return {"agents": ["separation_design", "process_simulation", "engineering_review"],
            "coordinator": "SeparationOrchestrator", "modes": ["rules", "llm"],
            "default_llm_provider": "deepseek",
            "llm_providers": ["deepseek"],
            "tools": ["binary_vle", "shortcut_distillation"],
            "few_shots_supported": True, "few_shots_enabled_by_default": True,
            "strategies": ["baseline", "hypothesis"],
            "verification_selection_policies": ["value_per_cost", "first_available"],
            "verification_costs_are_relative_proxies": True,
            "scope": "binary_saturated_liquid_shortcut_initialization",
            "rigorous_column_supported": False,
            "natural_language_numeric_updates_supported": False}


@router.post("/design")
async def design(request: DesignRunRequest):
    backend = None
    if request.mode == "llm":
        from sepmind.shortcut.llm import make_backend
        try:
            backend = make_backend(request.provider, request.model_name)
        except (ImportError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    team = SeparationOrchestrator(backend=backend, limits=request.limits, use_few_shots=request.use_few_shots,
                                 strategy=request.strategy, verification_policy=request.verification_policy)
    # Blocking .NET execution and provider calls do not block FastAPI's event loop.
    state = await asyncio.to_thread(team.run, request.task, message=request.message)
    return {"state": state.model_dump(), "report": report_data(state), "report_markdown": render_report(state)}
