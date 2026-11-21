"""Inspect numerical initialization evidence for the experimental controller."""

import math
from pathlib import Path


LEGACY_POLICY = 'legacy'
EVIDENCE_POLICY = 'evidence_v2'
POLICIES = (LEGACY_POLICY, EVIDENCE_POLICY)
POLICY_DIRECTORY = Path(__file__).with_name('policies')
ENTHALPY_FIELDS = ('liquid_enthalpy_kJ_mol', 'vapor_enthalpy_kJ_mol')


class InitializationEvidenceMissing(ValueError):
    """A requested numerical seed lacks prerequisites."""


def profile_capabilities(native):
    points = native.get('points', ()) if native else ()
    sampled = bool(points and native.get('evidence_id'))
    enthalpy_available = sampled and all(
        isinstance(point.get(field), (int, float)) and math.isfinite(point[field])
        for point in points for field in ENTHALPY_FIELDS
    )
    return {
        'default': {'available': True, 'requires': 'No sampled initialization evidence'},
        'native_cmo': {'available': sampled, 'requires': 'Sampled native VLE and a feasible CMO screen'},
        'native_enthalpy': {'available': enthalpy_available,
                            'requires': 'Sampled native VLE with finite liquid and vapor enthalpies at every point'},
    }
