"""Runtime model constraints, distinct from prompts and numerical adapters."""
import hashlib
from pathlib import Path
from ..schemas import Contract

MODEL_CARDS = Path(__file__).resolve().parents[3]/'engineering/knowledge/thermodynamic_models.json'


class ModelCard(Contract):
    model: str
    implemented: bool
    priority: int
    component_pairs: list[list[str]]
    mixture_class: str
    pressure_kPa: list[float] | None
    required_assumptions: list[str]
    hypothesis: str
    source_ids: list[str]
    limitations: list[str]


class ModelCatalog(Contract):
    version: str
    scope: str
    cards: list[ModelCard]


def assess_models(basis):
    raw = MODEL_CARDS.read_bytes()
    catalog = ModelCatalog.model_validate_json(raw)
    # A knowledge card can constrain an implementation, never add executable code.
    adapters = {'NRTL','Raoult'}
    pair = {c.cas or c.canonical_id for c in basis.components}
    options = []
    for card in sorted(catalog.cards,key=lambda c:c.priority):
        reasons,code = [],None
        pair_matches = len(basis.components)==2 and any(pair==set(p) for p in card.component_pairs)
        if not card.implemented or card.model not in adapters:
            code = 'DATA_PARAMETER_MISSING'
            reasons.append('No qualified numerical adapter and parameter set registered in this project.')
        elif not pair_matches:
            code = 'DATA_PARAMETER_MISSING'
            reasons.append('This component pair is outside the source-qualified model card.')
        elif card.pressure_kPa and (basis.feed.pressure_kPa is None or not card.pressure_kPa[0] <= basis.feed.pressure_kPa <= card.pressure_kPa[1]):
            code = 'MODEL_OUT_OF_RANGE'
            reasons.append('Operating pressure is outside the independently screened domain.')
        elif not set(card.required_assumptions).issubset(basis.assumptions):
            code = 'REQUIRES_REVIEW'
            reasons.append('Required explicit assumptions missing: '+', '.join(sorted(set(card.required_assumptions)-set(basis.assumptions))))
        else:
            reasons.append('Pair, domain and required assumptions admit a numerical test; model adequacy still needs evidence.')
        options.append({'model':card.model,'eligible':code is None,'reason_code':code or 'ELIGIBLE_FOR_TEST',
                        'reasons':reasons,'hypothesis':card.hypothesis,'limitations':card.limitations,
                        'source_ids':card.source_ids,'pair_matches':pair_matches,'mixture_class':card.mixture_class})
    requested = basis.thermodynamic_model
    if requested:
        chosen = next((c for c in options if c['model']==requested and c['eligible']),None)
    elif basis.design_mode=='autonomous':
        chosen = next((c for c in options if c['eligible']),None)
    else:
        chosen = None
    return {'catalog_version':catalog.version,'catalog_sha256':hashlib.sha256(raw).hexdigest(),
            'profile':{'component_order':[c.cas or c.canonical_id for c in basis.components],
                       'mixture_class':next((c['mixture_class'] for c in options if c['pair_matches']),'outside_qualified_catalog'),
                       'pressure_kPa':basis.feed.pressure_kPa,'phase_scope':'binary_molecular_VLE',
                       'requested_model':requested,'design_mode':basis.design_mode},
            'model_options':options,'selected_model':chosen['model'] if chosen else None,
            'selection_status':'eligible_for_numerical_test' if chosen else 'needs_evidence_or_review'}


def choose_model(basis):
    assessment = assess_models(basis)
    if assessment['selected_model']:
        return assessment['selected_model']
    if basis.thermodynamic_model:
        rejected = next((r for r in assessment['model_options'] if r['model']==basis.thermodynamic_model and r['pair_matches']),None)
        if rejected is None:
            rejected = next((r for r in assessment['model_options'] if r['model']==basis.thermodynamic_model),None)
    elif basis.design_mode=='specified':
        raise ValueError('REQUIRES_REVIEW: select a thermodynamic model in specified mode')
    else:
        rejected = next((r for r in assessment['model_options'] if r['pair_matches']),None)
    if rejected:
        raise ValueError(rejected['reason_code']+': '+'; '.join(rejected['reasons']))
    raise ValueError('DATA_PARAMETER_MISSING: no eligible source-backed model for this task')
