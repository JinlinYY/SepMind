"""Source-qualified atmospheric ethanol/water NRTL, conditional screening scope."""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from scipy.optimize import brentq
from thermo import NRTL_gammas, VaporPressure
from thermo.interaction_parameters import IPDB
from ..schemas import EvidenceRecord, ParameterSet

DATA = Path(__file__).resolve().parents[3]/'engineering/data/ethanol_water'


class EthanolWaterNRTL:
    MODEL = 'NRTL'

    def __init__(self, basis):
        import thermo
        self.order = [c.cas or c.canonical_id for c in basis.components]
        if set(self.order) != {'64-17-5','7732-18-5'} or len(self.order) != 2:
            raise ValueError('DATA_PARAMETER_MISSING: qualified NRTL pair is ethanol/water only')
        if basis.feed.pressure_kPa is None or abs(basis.feed.pressure_kPa*1000-101320) > 25:
            raise ValueError('MODEL_OUT_OF_RANGE: ethanol/water validation is limited to 101.320 +/- 0.025 kPa')
        self.pressures, cards = [], []
        for cas in self.order:
            v = VaporPressure(CASRN=cas, extrapolation=None)
            v.method = 'WAGNER_MCGARRY'
            self.pressures.append(v)
            cards.append({'cas':cas,'method':v.method,'coefficients':v.correlations[v.method][1],
                          'source_temperature_limits_K':list(v.T_limits[v.method])})
        for i in range(2):
            for j in range(2):
                if i != j and not all(IPDB.has_ip_specific('ChemSep NRTL',[self.order[i],self.order[j]],key)
                                      for key in ('bij','alphaij')):
                    raise ValueError('DATA_PARAMETER_MISSING: no default zero interaction parameters permitted')
        self.bs = IPDB.get_ip_asymmetric_matrix('ChemSep NRTL',self.order,'bij')
        self.alphas = IPDB.get_ip_asymmetric_matrix('ChemSep NRTL',self.order,'alphaij')
        self.low, self.high = 350., 374.
        reference = json.loads((DATA/'reference.json').read_text(encoding='utf-8'))
        if hashlib.sha256((DATA/'nist_je2005209.xml').read_bytes()).hexdigest() != reference['source_sha256']:
            raise ValueError('SOURCE_CONFLICT: retained experimental data hash mismatch')
        cards.append({'dataset':'ChemSep NRTL','tau_b_K':self.bs,'alpha':self.alphas,
                      'source_fit_temperature_limits_K':None,
                      'operational_guard_K':[self.low,self.high],
                      'guard_meaning':'project screening window around atmospheric boiling; NOT a published fit interval',
                      'pressure_guard_Pa':[101295,101345],
                      'reference_temperature_range_K':[min(p['temperature_K'] for p in reference['points']),
                                                       max(p['temperature_K'] for p in reference['points'])]})
        digest = hashlib.sha256(json.dumps(cards,sort_keys=True).encode()).hexdigest()
        self.parameters = ParameterSet(parameter_set_id=digest,model='NRTL',component_order=self.order,
            sources=[EvidenceRecord(evidence_id='chemsep-nrtl-'+digest[:12],type='property_database',sha256=digest,
                       source=f'thermo {thermo.__version__} ChemSep NRTL; DECHEMA 1 atm compilation; tau_ij=b_ij/T; https://thermo.readthedocs.io/thermo.interaction_parameters.html',
                       valid_temperature_K=[self.low,self.high]),
                     EvidenceRecord(evidence_id='nist-je2005209-'+reference['source_sha256'][:12],
                       type='property_database',source=reference['source_url']+' datasets 2/3 ONLY',
                       sha256=reference['source_sha256'])],
            correlations=cards,valid_temperature_K=[self.low,self.high],
            convention='y_i P = x_i gamma_i Psat_i; tau=b/T, b in K; ideal vapor and no Poynting correction; conditional atmospheric screening, not LLE/industrial certification')

    def psats(self, temperature):
        if not self.low <= temperature <= self.high:
            raise ValueError('MODEL_OUT_OF_RANGE: outside atmospheric screening temperature guard')
        return [float(v(temperature)) for v in self.pressures]

    def gammas(self, xs, temperature):
        return NRTL_gammas(xs, [[b/temperature for b in row] for row in self.bs], self.alphas)

    @lru_cache(maxsize=16000)
    def point(self, x, pressure_pa):
        if not 0 <= x <= 1 or abs(pressure_pa-101320) > 25:
            raise ValueError('MODEL_OUT_OF_RANGE: invalid composition or unvalidated pressure')
        xs = [float(x),1-float(x)]
        def residual(t):
            return sum(a*b*c for a,b,c in zip(xs,self.gammas(xs,t),self.psats(t)))-pressure_pa
        t = float(brentq(residual,self.low,self.high,xtol=1e-9))
        gamma, psat = self.gammas(xs,t),self.psats(t)
        ys = [xs[i]*gamma[i]*psat[i]/pressure_pa for i in range(2)]
        return {'x':xs,'y':ys,'temperature_K':t,'psat_Pa':psat,'activity_coefficients':gamma,
                'bubble_residual_relative':abs(residual(t))/pressure_pa,
                'vapor_sum_residual':abs(sum(ys)-1),
                'fugacity_residual_Pa':[ys[i]*pressure_pa-xs[i]*gamma[i]*psat[i] for i in range(2)]}

    def grid(self, pressure_pa, points=81):
        return {'points':[self.point(i/(points-1),pressure_pa) for i in range(points)],
                'model':self.MODEL,'pressure_Pa':pressure_pa,'parameter_set':self.parameters.model_dump(),
                'scope':'conditional atmospheric NRTL gamma/ideal-vapor; experimental screening errors stored in parameter qualification'}

    def reference_check(self):
        reference = json.loads((DATA/'reference.json').read_text(encoding='utf-8'))
        residuals = []
        for row in reference['points']:
            x = row['x_ethanol'] if self.order[0]=='64-17-5' else 1-row['x_ethanol']
            calc = self.point(x,reference['pressure_Pa'])
            y = calc['y'][self.order.index('64-17-5')]
            residuals.append({'x_ethanol':row['x_ethanol'],'temperature_error_K':calc['temperature_K']-row['temperature_K'],
                              'y_ethanol_error':y-row['y_ethanol']})
        max_t = max(abs(r['temperature_error_K']) for r in residuals)
        max_y = max(abs(r['y_ethanol_error']) for r in residuals)
        return {'passed': max_t <= 1.0 and max_y <= .025, 'points':residuals,
                'maximum_temperature_error_K':max_t,'maximum_y_error':max_y,
                'acceptance_K':1.0,'acceptance_mole_fraction':.025,
                'scope':'predeclared preliminary-screening tolerances, not agreement within measurement uncertainty',
                'source_url':reference['source_url'],'source_sha256':reference['source_sha256']}
