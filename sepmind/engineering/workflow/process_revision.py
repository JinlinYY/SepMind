"""Expert actions for a checked extraction endpoint that misses its target."""
from ..schemas import Contract
from ..schemas.process import ExtractionSearch


class ExtractionRevisionChoice(Contract):
    action_id: str
    evidence_ids: list[str]
    rationale: str


def extraction_revision_options(state):
    """Return finite design experiments; do not modify the frozen design basis.

    This policy does not retry missing data, failed review, out-of-domain models
    or uncertain phase behavior as though more solvent could cure those errors.
    """
    failed=state.artifacts.get('select_extraction_candidate')
    explored=state.artifacts.get('explore_extraction_candidates')
    audited=state.artifacts.get('review_extraction_candidates')
    if not failed or failed.error_type!='EXTRACTION_TARGET_NOT_MET':return []
    if not explored or not audited or not audited.validation.get('passed'):return []
    if explored.data.get('target',{}).get('operator') not in ('>=','>'):return []
    rows=explored.data['candidates']
    if not rows or any(r['status']!='off_spec' or not r.get('independent_review',{}).get('passed') for r in rows):return []
    policy=state.basis.redesign_policy
    if len(state.revision_history)>=policy.maximum_revisions:return []
    search=state.active_search or state.basis.search
    stages=min(policy.maximum_stages,max(search.stage_candidates)*2)
    ratio=min(policy.maximum_solvent_feed_mass_ratio,max(search.solvent_feed_mass_ratios)*1.5)
    options=[]
    def add(action,ns,ratios,reason):
        if max(ns)>policy.maximum_stages or max(ratios)>policy.maximum_solvent_feed_mass_ratio:return
        raw=search.model_dump()
        raw.update(stage_candidates=ns,solvent_feed_mass_ratios=ratios,
                   maximum_candidates=min(policy.maximum_candidates_per_revision,len(ns)*len(ratios)))
        options.append({'action_id':action,'search':ExtractionSearch.model_validate(raw).model_dump(),'rationale':reason})
    if stages>max(search.stage_candidates):
        add('increase_contacts',[stages],search.solvent_feed_mass_ratios,
            'Checked contacts miss extraction recovery: test more contacts at the previous solvent ratios.')
    if ratio>max(search.solvent_feed_mass_ratios):
        add('increase_solvent',search.stage_candidates,[ratio],
            'Checked contacts miss recovery: test more solvent, retaining coextraction and regeneration trade-offs.')
    if stages>max(search.stage_candidates) and ratio>max(search.solvent_feed_mass_ratios):
        add('increase_contacts_and_solvent',[stages],[ratio],
            'Test a bounded joint revision; no energy or cost optimum is implied.')
    return options
