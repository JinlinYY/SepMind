"""Runtime process policies bound to registered tools, not executable Markdown."""
import hashlib
from pathlib import Path
from typing import Literal
import yaml
from pydantic import Field
from ..schemas import Contract


class ProcessSkill(Contract):
    skill_id: str
    version: str
    owner: Literal['thermodynamics','engineering','process_advisor','expert_review']
    gates: list[str]
    tools: list[str]
    checks: list[str]
    hypothesis: str


class ProcessSkillRegistry:
    def __init__(self):
        from ..tools.process import ProcessToolRegistry
        root=Path(__file__).resolve().parents[3]/'engineering/runtime_process_skills'
        self.cards={};self.hashes={};self.procedures={}
        for path in sorted(root.glob('*/SKILL.md')):
            raw=path.read_bytes();parts=raw.decode().split('---',2)
            card=ProcessSkill.model_validate(yaml.safe_load(parts[1]))
            if card.skill_id!=path.parent.name or card.skill_id in self.cards:raise ValueError('INVALID_PROCESS_SKILL')
            if any(t not in ProcessToolRegistry.TOOLS or ProcessToolRegistry.TOOLS[t][0] not in card.gates for t in card.tools):
                raise ValueError('INVALID_PROCESS_SKILL_BINDING')
            self.cards[card.skill_id]=card;self.hashes[card.skill_id]=hashlib.sha256(raw).hexdigest();self.procedures[card.skill_id]=parts[2].strip()
        if {t for c in self.cards.values() for t in c.tools}!=set(ProcessToolRegistry.TOOLS):raise ValueError('PROCESS_SKILL_COVERAGE_MISSING')

    def for_tool(self,tool):
        return [c.model_dump()|{'sha256':self.hashes[c.skill_id],'procedure':self.procedures[c.skill_id]} for c in self.cards.values() if tool in c.tools]
