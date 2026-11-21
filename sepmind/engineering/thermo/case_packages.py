"""Source-backed research extensions with explicit, bounded extrapolation flags.

These adapters do not widen the qualified ethanol/water pressure domain. The
reference subsets measure P-x-T, not vapor composition; DWSIM adds a separate
cross-implementation check and is not called experimental validation.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from scipy.optimize import brentq
from thermo import NRTL_gammas, VaporPressure
from thermo.interaction_parameters import IPDB
from ..schemas import EvidenceRecord, ParameterSet

DATA=Path(__file__).resolve().parents[3]/'engineering/data'

class CaseVLEPackage:
    def __init__(self,basis):
        import thermo
        self.order=[c.cas or c.canonical_id for c in basis.components]
        if set(self.order)=={'71-43-2','108-88-3'}:
            self.label,self.MODEL='benzene_toluene','Raoult'
            self.low,self.high=330.,390.
        elif set(self.order)=={'67-56-1','7732-18-5'}:
            self.label,self.MODEL='methanol_water','NRTL'
            self.low,self.high=330.,380.
        else:
            raise ValueError('DATA_PARAMETER_MISSING: unsupported research case pair')
        if 'research_scope_low_pressure_vle' not in basis.assumptions:
            raise ValueError('REQUIRES_REVIEW: research_scope_low_pressure_vle must be explicit')
        if basis.feed.pressure_kPa is None or not 106.30<=basis.feed.pressure_kPa<=106.35:
            raise ValueError('MODEL_OUT_OF_RANGE: case extension limited to task top pressure 106.325 +/- 0.025 kPa')
        self.pressures=[];cards=[]
        for cas in self.order:
            v=VaporPressure(CASRN=cas,extrapolation=None);v.method='WAGNER_MCGARRY'
            self.low=max(self.low,v.T_limits[v.method][0]);self.high=min(self.high,v.T_limits[v.method][1])
            self.pressures.append(v)
            cards.append({'cas':cas,'method':v.method,'coefficients':v.correlations[v.method][1],
                          'source_temperature_limits_K':list(v.T_limits[v.method])})
        self.bs=self.alphas=None
        if self.MODEL=='NRTL':
            for i,j in ((0,1),(1,0)):
                if not all(IPDB.has_ip_specific('ChemSep NRTL',[self.order[i],self.order[j]],k) for k in ('bij','alphaij')):
                    raise ValueError('DATA_PARAMETER_MISSING: no zero-filled NRTL parameters')
            self.bs=IPDB.get_ip_asymmetric_matrix('ChemSep NRTL',self.order,'bij')
            self.alphas=IPDB.get_ip_asymmetric_matrix('ChemSep NRTL',self.order,'alphaij')
            cards.append({'database':'ChemSep NRTL','tau_b_K':self.bs,'alpha':self.alphas,
                          'published_fit_T_interval_K':None,'convention':'tau=b/T'})
        self.reference=json.loads((DATA/self.label/'reference.json').read_text(encoding='utf-8'))
        if hashlib.sha256((DATA/self.label/'reference.xml').read_bytes()).hexdigest()!=self.reference['source_sha256']:
            raise ValueError('SOURCE_CONFLICT: experimental reference hash mismatch')
        self.caveat=self.reference['operating_domain_caveat']
        self.atmospheric=None
        if self.label=='methanol_water':
            self.atmospheric=json.loads((DATA/self.label/'atmospheric_reference.json').read_text(encoding='utf-8'))
            if not (DATA/self.label/'primary.pdf').is_file():
                raise ValueError('DATA_PARAMETER_MISSING: fetch and verify the local reference with scripts/fetch_case_property_sources.py')
            if hashlib.sha256((DATA/self.label/'primary.pdf').read_bytes()).hexdigest()!=self.atmospheric['source_sha256']:
                raise ValueError('SOURCE_CONFLICT: atmospheric source hash mismatch')
            self.caveat='Measured 101.3 kPa VLE screening; task at 106.325 kPa is a 4.96% pressure extrapolation. Separate 95.3 kPa data fail the 1 K screen and are not admitted as an operating domain; source conflict retained. '+self.atmospheric['temperature_header_issue']
        cards.append({'project_temperature_guard_K':[self.low,self.high],'project_pressure_guard_kPa':[106.3,106.35],
                      'published_fit_interval':False,'extrapolation_caveat':self.caveat})
        digest=hashlib.sha256(json.dumps(cards,sort_keys=True).encode()).hexdigest()
        self.parameters=ParameterSet(parameter_set_id=digest,model=self.MODEL,component_order=self.order,
            sources=[EvidenceRecord(evidence_id='case-vle-'+digest[:16],type='property_database',sha256=digest,
                source=f'thermo {thermo.__version__}; McGarry vapor pressures; '+('ChemSep NRTL tau=b/T; ' if self.bs else '')+'https://thermo.readthedocs.io/'),
                EvidenceRecord(evidence_id='nist-'+self.label+'-'+self.reference['source_sha256'][:12],
                    type='property_database',source=self.reference['source_url']+' dataset '+str(self.reference['dataset']),sha256=self.reference['source_sha256'])],
            correlations=cards,valid_temperature_K=[self.low,self.high],
            convention='gamma/ideal-vapor low-pressure research screening; no Poynting correction. '+self.caveat)
        if self.atmospheric:
            self.parameters.sources.append(EvidenceRecord(evidence_id='alvarez-2011-'+self.atmospheric['source_sha256'][:12],type='property_database',source=self.atmospheric['source_url']+' Table 2 methanol/water only',sha256=self.atmospheric['source_sha256']))

    def psats(self,t):
        if not self.low<=t<=self.high:raise ValueError('MODEL_OUT_OF_RANGE: research temperature guard')
        return [float(v(t)) for v in self.pressures]

    def gammas(self,xs,t):
        return NRTL_gammas(xs,[[b/t for b in row] for row in self.bs],self.alphas) if self.bs else [1.,1.]

    @lru_cache(maxsize=16000)
    def point(self,x,pressure_pa):
        if not 0<=x<=1 or not 95000<=pressure_pa<=106350:
            raise ValueError('MODEL_OUT_OF_RANGE: invalid composition or research pressure')
        xs=[x,1-x]
        residual=lambda t:sum(a*b*c for a,b,c in zip(xs,self.gammas(xs,t),self.psats(t)))-pressure_pa
        t=float(brentq(residual,self.low,self.high,xtol=1e-9))
        gamma,psat=self.gammas(xs,t),self.psats(t)
        ys=[xs[i]*gamma[i]*psat[i]/pressure_pa for i in range(2)]
        return {'x':xs,'y':ys,'temperature_K':t,'psat_Pa':psat,'activity_coefficients':gamma,
                'bubble_residual_relative':abs(residual(t))/pressure_pa,'vapor_sum_residual':abs(sum(ys)-1),
                'fugacity_residual_Pa':[ys[i]*pressure_pa-xs[i]*gamma[i]*psat[i] for i in range(2)]}

    def grid(self,pressure_pa,points=81):
        return {'points':[self.point(i/(points-1),pressure_pa) for i in range(points)],'model':self.MODEL,
                'pressure_Pa':pressure_pa,'parameter_set':self.parameters.model_dump(),'scope':self.caveat}

    def reference_check(self):
        rows=[]
        light='71-43-2' if self.label=='benzene_toluene' else '67-56-1'
        for p in self.reference['points']:
            x=p['x_light'] if self.order[0]==light else 1-p['x_light'];xs=[x,1-x]
            if self.label=='benzene_toluene':
                calc=sum(a*b*c for a,b,c in zip(xs,self.gammas(xs,p['temperature_K']),self.psats(p['temperature_K'])))
                rows.append({'x_light':p['x_light'],'relative_pressure_error':calc/p['pressure_Pa']-1})
            else:
                rows.append({'x_light':p['x_light'],'temperature_error_K':self.point(x,p['pressure_Pa'])['temperature_K']-p['temperature_K']})
        key='relative_pressure_error' if self.label=='benzene_toluene' else 'temperature_error_K'
        maximum=max(abs(r[key]) for r in rows)
        acceptance=.05 if self.label=='benzene_toluene' else 1.0
        record={'passed':maximum<=acceptance,'points':rows,'maximum_absolute_error':maximum,'metric':key,
                'acceptance':acceptance,'source_url':self.reference['source_url'],'source_sha256':self.reference['source_sha256'],
                'scope':'predeclared research P-x-T screening; no experimental vapor composition validation. '+self.caveat,
                'operating_domain_extrapolation_flag':True,'vapor_composition_experimentally_validated':False}
        if self.atmospheric:
            errors=[]
            for p in self.atmospheric['points']:
                x=p['x_light'] if self.order[0]==light else 1-p['x_light']
                calc=self.point(x,p['pressure_Pa'])
                errors.append({'x_light':p['x_light'],'temperature_error_K':calc['temperature_K']-p['temperature_K'],
                               'y_light_error':calc['y'][self.order.index(light)]-p['y_light']})
            mt=max(abs(e['temperature_error_K']) for e in errors);my=max(abs(e['y_light_error']) for e in errors)
            record={'passed':mt<=1. and my<=.025,'points':errors,'maximum_temperature_error_K':mt,'maximum_y_error':my,
                    'acceptance_K':1.,'acceptance_mole_fraction':.025,'source_url':self.atmospheric['source_url'],
                    'source_sha256':self.atmospheric['source_sha256'],'outside_admitted_domain_check_95_3_kPa':record,
                    'scope':'Conditional 101.3 kPa measured VLE screen; 106.325 kPa research extrapolation only. '+self.caveat,
                    'operating_domain_extrapolation_flag':True,'source_conflict_unresolved':True,
                    'vapor_composition_experimentally_validated_at_task_pressure':False}
        return record
