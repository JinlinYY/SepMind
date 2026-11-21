"""Versioned expert policies with bindings to executable topology tools."""
import hashlib
from pathlib import Path
import yaml
from ..skills import RuntimeSkill

ROOT = Path(__file__).resolve().parents[3]


class TopologySkillRegistry:
    def __init__(self):
        from .tools import TopologyToolRegistry
        self.cards = {}
        self.procedures = {}
        digest = hashlib.sha256()
        for path in sorted((ROOT/'engineering/topology_skills').glob('*/SKILL.md')):
            raw = path.read_bytes()
            parts = raw.decode('utf8').split('---', 2)
            if len(parts) != 3 or parts[0].strip():
                raise ValueError('INVALID_TOPOLOGY_SKILL')
            card = RuntimeSkill.model_validate(yaml.safe_load(parts[1]))
            if card.skill_id != path.parent.name or card.skill_id in self.cards:
                raise ValueError('INVALID_TOPOLOGY_SKILL_ID')
            if any(tool not in TopologyToolRegistry.TOOLS or TopologyToolRegistry.TOOLS[tool][0] not in card.gates for tool in card.tools):
                raise ValueError('INVALID_TOPOLOGY_TOOL_BINDING')
            self.cards[card.skill_id] = card
            self.procedures[card.skill_id] = parts[2].strip()
            digest.update(raw)
        if set(self.cards) != {'topology_construction', 'topology_counterevidence', 'topology_independent_review'}:
            raise ValueError('INCOMPLETE_TOPOLOGY_SKILLS')
        self.knowledge_hash = digest.hexdigest()

    def context(self):
        return [card.model_dump() | {'procedure': self.procedures[name]}
                for name, card in self.cards.items()]
