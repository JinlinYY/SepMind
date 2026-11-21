"""Audited representation of machine-roundoff-only composition excursions."""
import numpy as np


def canonicalize_roundoff(values):
    raw=np.asarray(values,dtype=float)
    limit=32*np.spacing(1.)
    if not np.isfinite(raw).all() or min(raw)<-limit or max(raw)>1+limit:
        return list(values),None
    if min(raw)>=0 and max(raw)<=1:return list(values),None
    corrected=np.clip(raw,0.,1.)
    if abs(sum(corrected)-1)>limit:return list(values),None
    corrected/=sum(corrected)
    change=float(max(abs(corrected-raw)))
    if change>limit:return list(values),None
    return corrected.tolist(),dict(original_native_composition=raw.tolist(),represented_composition=corrected.tolist(),
        maximum_absolute_change=change,maximum_permitted_change=limit,
        scope='Only excursions within 32 machine spacings at unity. Positive trace inventory retained; original target and numerical acceptance unchanged.')
