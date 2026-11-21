"""Opt-in pressure sensitivity with identical, hash-pinned physical model.

An expanded computational guard is not experimental property qualification.
Only the already retained H02 hydraulic card may be used by this adapter.
"""
from separation.tools.mixture import mixture_card

H02_HYDRAULIC_CARD='mch_toluene_phenol_hydraulic_sensitivity_v2'
_METADATA={'model_id','status','temperature_guard_K','pressure_guard_Pa','limitations',
           'parent_model_id','parent_parameter_sha256'}


def admitted_card(model_id,basis):
    if model_id in basis.property_cards:return True
    if not getattr(basis.budget,'hydraulic_pressure_sensitivity',False) or basis.design_id!='H02' or model_id!=H02_HYDRAULIC_CARD:
        return False
    card,_=mixture_card(model_id)
    parent_id=card.get('parent_model_id')
    if parent_id not in basis.property_cards:return False
    parent,digest=mixture_card(parent_id)
    return (card.get('status')=='unqualified_pressure_feedback_sensitivity' and
            card.get('parent_parameter_sha256')==digest and
            {k:v for k,v in card.items() if k not in _METADATA}=={k:v for k,v in parent.items() if k not in _METADATA})


def same_source_physics(first,second,basis):
    if first==second:return admitted_card(first,basis)
    if not admitted_card(first,basis) or not admitted_card(second,basis):return False
    one,_=mixture_card(first);two,_=mixture_card(second)
    return {k:v for k,v in one.items() if k not in _METADATA}=={k:v for k,v in two.items() if k not in _METADATA}
