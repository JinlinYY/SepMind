"""Multicomponent NRTL liquid splitting with explicit numerical acceptance.

Isothermal/isobaric LLE only. Multistart Gibbs/TPD screens are finite numerical
tests, not a global phase-stability proof or a vapour/enthalpy model.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize, least_squares
from scipy.special import softmax
from thermo import NRTL_gammas


@dataclass
class NRTLModel:
    card: dict

    def __post_init__(self):
        self.order=self.card['component_order']
        self.A=np.array(self.card['A'],dtype=float)
        self.B=np.array(self.card['B_K'],dtype=float)
        self.alpha=np.array(self.card['alpha'],dtype=float)
        n=len(self.order)
        if len(set(self.order))!=n or any(a.shape!=(n,n) or not np.isfinite(a).all() for a in (self.A,self.B,self.alpha)):
            raise ValueError('INVALID_PROPERTY_CARD: explicit finite square matrices and unique components required')
        if not np.allclose(self.alpha,self.alpha.T) or np.min(self.alpha)<0 or np.max(self.alpha)>1:
            raise ValueError('INVALID_PROPERTY_CARD: nonrandomness coefficients must be symmetric in [0,1]')
        self.mw=np.array(self.card['molecular_weights_g_mol'],dtype=float)
        if len(self.mw)!=n or not np.isfinite(self.mw).all() or np.min(self.mw)<=0:
            raise ValueError('INVALID_PROPERTY_CARD: molecular weights must be positive and source-tagged')
        self.digest=hashlib.sha256(json.dumps(self.card,sort_keys=True).encode()).hexdigest()

    def check_domain(self,T,P,require_qualified=True):
        if not np.isfinite([T,P]).all():raise ValueError('MODEL_OUT_OF_RANGE: nonfinite state')
        lo,hi=self.card['temperature_guard_K'];pmin,pmax=self.card['pressure_guard_Pa']
        if not lo<=T<=hi or not pmin<=P<=pmax:raise ValueError('MODEL_OUT_OF_RANGE: LLE state outside qualified project guard')
        if require_qualified and 'LLE' not in self.card.get('admitted_phases',[]):
            raise ValueError('PROPERTY_UNQUALIFIED: candidate parameters are not executable production evidence')

    def lngamma(self,x,T):
        x=np.asarray(x,dtype=float)
        b=self.B
        if self.card.get('temperature_parameter_knots'):
            knots=self.card['temperature_parameter_knots']
            ts=[k['temperature_K'] for k in knots]
            if not min(ts)<=T<=max(ts):raise ValueError('MODEL_OUT_OF_RANGE: parameter interpolation cannot extrapolate')
            arrays=np.array([k['B_K'] for k in knots],dtype=float)
            b=np.array([[np.interp(T,ts,arrays[:,i,j]) for j in range(len(x))] for i in range(len(x))])
        return np.log(np.asarray(NRTL_gammas(x.tolist(),(self.A+b/T).tolist(),self.alpha.tolist())))

    def mu(self,x,T):return np.log(np.maximum(x,1e-300))+self.lngamma(x,T)

    def g(self,x,T):return float(np.dot(x,self.mu(x,T)))


def _composition(value,n):
    z=np.asarray(value,dtype=float)
    if z.shape!=(n,) or not np.isfinite(z).all() or min(z)<0 or abs(sum(z)-1)>1e-9:
        raise ValueError('INVALID_COMPOSITION: fractions must match order and sum to one without silent normalization')
    return z


def load_lle_model(model_id):
    root=Path(__file__).resolve().parents[3]
    allowed={'acid_lle_colombo1999_v1':root/'engineering/data/hybrid/acid_lle_colombo1999_v1.json'}
    if model_id not in allowed:raise ValueError('PROPERTY_UNQUALIFIED: no approved LLE model for the requested identity')
    card=json.loads(allowed[model_id].read_text(encoding='utf8'))
    report_path=root/card['qualification_report']
    if not report_path.resolve().is_relative_to(root/'engineering/data/hybrid'):
        raise ValueError('SOURCE_CONFLICT: qualification must be retained with versioned property evidence')
    raw=report_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=card['qualification_sha256']:raise ValueError('SOURCE_CONFLICT: LLE qualification hash mismatch')
    report=json.loads(raw)
    core={k:card[k] for k in ('A','B_K','alpha','component_order','molecular_weights_g_mol','temperature_parameter_knots')}
    if not report['passed'] or hashlib.sha256(json.dumps(core,sort_keys=True).encode()).hexdigest()!=report['parameter_core_sha256']:
        raise ValueError('SOURCE_CONFLICT: current parameters differ from the qualified model')
    return NRTLModel(card)


def stability_screen(model,x,T,starts=5):
    """Minimize tangent-plane distance from explicit deterministic starts."""
    x=_composition(x,len(model.order));active=np.flatnonzero(x>0)
    if len(active)<len(x):
        # An exactly absent species cannot be created by an isochemical split.
        # Minimize on the available-species face, without adding trace material.
        class FaceModel:
            order=list(active)
            def mu(self,y,temp):
                full=np.zeros_like(x);full[active]=y
                return model.mu(full,temp)[active]
        result=stability_screen(FaceModel(),x[active],T,starts)
        for row in result['minima']:
            full=np.zeros_like(x);full[active]=row['composition'];row['composition']=full.tolist()
        result['available_component_indices']=active.tolist()
        return result
    n=len(x);mu=model.mu(x,T)
    if n==1:return dict(minimum_tpd=0.,starts=1,minima=[dict(tpd=0.,composition=x.tolist(),converged=True)],scope='Pure available-species face')
    seeds=[x,np.full(n,1/n)]+[.98*np.eye(n)[i]+.02/n for i in range(n)]
    minima=[]
    for seed in seeds[:max(starts,n+2)]:
        initial=np.log(seed[:-1]/seed[-1])
        def f(v):
            y=softmax(np.r_[v,0.]);return float(y@(model.mu(y,T)-mu))
        sol=minimize(f,initial,method='L-BFGS-B',bounds=[(-35,35)]*(n-1),options={'ftol':1e-13,'gtol':1e-9,'maxiter':160})
        minima.append({'tpd':float(sol.fun),'composition':softmax(np.r_[sol.x,0.]).tolist(),'converged':bool(sol.success)})
    return {'minimum_tpd':min(r['tpd'] for r in minima),'starts':len(minima),'minima':minima,
            'scope':'finite multistart local optimization; not a global stability certificate'}


def flash_lle(model,z,T,P,require_qualified=True,check_stability=True):
    model.check_domain(T,P,require_qualified)
    z=_composition(z,len(model.order))
    active=np.where(z>1e-14)[0]
    if len(active)!=len(z):
        raise ValueError('UNSUPPORTED_ZERO_COMPONENT: this LLE solver requires all declared species present; omit truly absent species in a separately qualified model')
    g_single=model.g(z,T)
    def values(q):
        beta=float(sum(q));a=q/beta;b=(z-q)/(1-beta)
        return beta,a,b
    def objective(q):
        beta,a,b=values(q)
        return beta*model.g(a,T)+(1-beta)*model.g(b,T)
    def jac(q):
        _,a,b=values(q);return model.mu(a,T)-model.mu(b,T)
    eps=np.minimum(z*1e-9,1e-12)
    bounds=list(zip(eps,z-eps))
    seeds=[np.full(len(z),.5)]+[np.where(np.arange(len(z))==i,.98,.02) for i in range(len(z))]
    solutions=[minimize(objective,z*s,jac=jac,bounds=bounds,method='L-BFGS-B',
                       options={'ftol':1e-14,'gtol':1e-9,'maxiter':350,'maxls':40}) for s in seeds]
    sol=min(solutions,key=lambda r:r.fun)
    beta,a,b=values(sol.x)
    gap=float(np.max(abs(a-b)))
    if sol.fun>=g_single-1e-9 or min(beta,1-beta)<1e-7 or gap<1e-5:
        screen=stability_screen(model,z,T) if check_stability else None
        if screen and screen['minimum_tpd'] < -1e-6:
            raise ValueError('LLE_UNRESOLVED: Gibbs solve did not resolve a split indicated by the TPD screen')
        return {'phase_count':1,'phases':[{'fraction':1.,'composition':z.tolist()}],
                'validation':{'passed':True,'mass_residual':0.,'stability_screen':screen},
                'model_id':model.card['model_id'],'parameter_sha256':model.digest}
    # Polish equality of all activities and the lever rule, retaining nontrivial
    # phases. This solves equations; it does not turn a local root into stability.
    n=len(z)
    def unpack(v):return softmax(np.r_[v[:n-1],0.]),softmax(np.r_[v[n-1:2*n-2],0.]),float(1/(1+np.exp(-v[-1])))
    v=np.r_[np.log(a[:-1]/a[-1]),np.log(b[:-1]/b[-1]),np.log(beta/(1-beta))]
    def residual(v):
        aa,bb,f=unpack(v)
        return np.r_[model.mu(aa,T)-model.mu(bb,T),(f*aa+(1-f)*bb-z)[:-1]*10]
    polished=least_squares(residual,v,bounds=(-40,40),xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=140)
    a,b,beta=unpack(polished.x)
    eq=float(max(abs(model.mu(a,T)-model.mu(b,T))))
    mass=float(max(abs(beta*a+(1-beta)*b-z)))
    delta=beta*model.g(a,T)+(1-beta)*model.g(b,T)-g_single
    if not np.isfinite(np.r_[a,b,beta,eq,mass,delta]).all() or eq>1e-6 or mass>1e-8 or delta>=-1e-9 or max(abs(a-b))<1e-5:
        raise ValueError(f'LLE_NONCONVERGENCE: equality={eq:g}, closure={mass:g}, dG={delta:g}')
    screen=stability_screen(model,a,T) if check_stability else None
    if screen and screen['minimum_tpd'] < -1e-6:
        raise ValueError('LLE_STABILITY_SCREEN_FAILED: another candidate composition lowers the tangent plane')
    return {'phase_count':2,'phases':[{'fraction':beta,'composition':a.tolist()},{'fraction':1-beta,'composition':b.tolist()}],
            'validation':{'passed':True,'mass_residual':mass,'maximum_log_activity_residual':eq,
                          'gibbs_change_RT_per_mol':float(delta),'stability_screen':screen},
            'model_id':model.card['model_id'],'parameter_sha256':model.digest,
            'limits':['isothermal LLE only; no vapour, duty, transport or global stability claim']}
