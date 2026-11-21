from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib, json

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TASKS = {'D01':'case-1a','D02':'case-1b','D03':'case-2','D04':'case-3'}
MODELS = {'D01':'Raoult','D02':'Raoult','D03':'NRTL','D04':'NRTL'}

@dataclass(frozen=True)
class Budget:
    llm: int = 24
    actions: int = 32
    tools: int = 96
    native: int = 6
    columns: int = 4
    vle: int = 2
    native_timeout_s: int = 180
    episode_timeout_s: int = 1800
    llm_timeout_s: int = 60
    max_output_tokens: int = 2048

@dataclass(frozen=True)
class Arm:
    id: str
    label: str
    topology: str
    expert: bool
    review: bool
    classified_revision: bool
    dependency_reuse: bool

def arms():
    return {p.stem:Arm(**json.loads(p.read_text(encoding='utf8'))) for p in sorted((HERE/'configs').glob('*.json'))}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def task_basis(case):
    from pha.engineering.schemas import DesignBasis
    source=ROOT/'case/curated'/TASKS[case]/'agent_input.json'
    raw=json.loads(source.read_text(encoding='utf8'))
    original=json.loads(json.dumps(raw))
    # Freeze method to the original comparison; change endpoint scope only.
    raw['thermodynamic_model']=MODELS[case]
    raw['design_level']='preliminary_process'
    return DesignBasis.model_validate(raw), {'source':str(source.relative_to(ROOT)),
        'source_sha256':digest(source),'original_input':original,
        'endpoint_scope':'fixed-design strict binary column, not equipment',
        'frozen_property_model':MODELS[case]}

def knowledge():
    from pha.engineering.skills import ExpertSkillRegistry
    from pha.engineering.knowledge import MODEL_CARDS
    registry=ExpertSkillRegistry()
    result={'runtime_skills':[{'card':v.model_dump(),'procedure':registry.procedures[k],
        'sha256':registry.hashes[k]} for k,v in registry.cards.items()],
        'model_cards':json.loads(MODEL_CARDS.read_text(encoding='utf8')),
        'knowledge_sha256':registry.knowledge_hash}
    return result
