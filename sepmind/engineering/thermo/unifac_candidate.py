"""Independent original-UNIFAC equation for explicitly conditional experiments.

Subgroup IDs are implementation-specific. Cards separately declare DWSIM and
standard UFSG identities; never copy numeric IDs between the two libraries.
"""
import hashlib
import json
import numpy as np
from thermo.unifac import UNIFAC,UFIP,UFSG
from .lle import NRTLModel


class UNIFACCandidateModel:
    def __init__(self,card):
        if card['model']!='UNIFAC':raise ValueError('Only original UNIFAC supported')
        self.card=card;self.order=card['component_order'];self.mw=np.asarray(card['molecular_weights_g_mol'],dtype=float)
        self.groups=[{int(k):v for k,v in row.items()} for row in card['standard_UNIFAC_groups']]
        if len(self.groups)!=len(self.order) or len(self.mw)!=len(self.order) or not np.isfinite(self.mw).all() or min(self.mw)<=0:
            raise ValueError('Incomplete UNIFAC component specification')
        if any(not row or any(k not in UFSG or type(v) is not int or v<=0 for k,v in row.items()) for row in self.groups):
            raise ValueError('Unknown UNIFAC group or invalid count')
        self.digest=hashlib.sha256(json.dumps(card,sort_keys=True).encode()).hexdigest()
        self._prototype=UNIFAC.from_subgroups(T=300.,xs=[1/len(self.order)]*len(self.order),
            chemgroups=self.groups,interaction_data=UFIP,subgroups=UFSG,version=0)

    check_domain=NRTLModel.check_domain
    mu=NRTLModel.mu
    g=NRTLModel.g

    def lngamma(self,x,T):
        return np.asarray(self._prototype.to_T_xs(T=T,xs=list(x)).lngammas())
