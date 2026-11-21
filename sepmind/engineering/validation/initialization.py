"""Material-consistent numerical seeds; these are never process results.

Project interpolated component-flow profiles onto stage balances and endpoint
draw constraints. Equilibrium ratios come ONLY from the supplied numerical
seed, not invented property data. Native MESH must subsequently be solved.
"""
import numpy as np
from scipy.optimize import brentq


def material_consistent_profile(request):
    if not request.initial_profile:raise ValueError('Source-tagged numerical profile required')
    rows=request.initial_profile;n=len(rows);c=len(request.components)
    stripper=getattr(request,'column_mode','total_condenser')=='reboiled_absorber'
    if n!=request.equilibrium_stages+(not stripper):raise ValueError('Full initial profile required')
    feeds=np.zeros((n,c))
    for stream in request.feeds:
        feeds[stream.stage_index]+=stream.flow_mol_s*np.asarray(stream.mole_fractions)
    x=np.array([r['liquid_mole_fractions'] for r in rows]);y=np.array([r['vapor_mole_fractions'] for r in rows])
    lf=np.array([r['liquid_flow_mol_s'] for r in rows]);vf=np.array([r['vapor_flow_mol_s'] for r in rows])
    if np.min(x)<=0 or np.min(y[1:])<=0 or np.min(lf)<=0 or np.min(vf[1:])<=0:
        raise ValueError('Positive component/phase estimates required for projection; physical feeds are not altered')
    start=0 if stripper else 1
    alpha=(vf[start:,None]/lf[start:,None])*(y[start:]/x[start:])
    def solve(multiplier):
        ratios=multiplier*alpha if stripper else np.vstack([np.full(c,1/request.reflux_ratio),multiplier*alpha])
        liquid=np.empty((n,c))
        for j in range(c):
            matrix=np.diag(1+ratios[:,j])+np.diag(np.full(n-1,-1.),-1)+np.diag(-ratios[1:,j],1)
            liquid[:,j]=np.linalg.solve(matrix,feeds[:,j])
        vapor=ratios*liquid
        if not np.isfinite(liquid).all() or not np.isfinite(vapor).all() or min(liquid.min(),vapor.min())<0:
            raise ValueError('Nonphysical numerical projection')
        return liquid,vapor
    def mismatch(q):return sum(solve(q)[1][0])-request.distillate_flow_mol_s
    lo,hi=.01,100.
    if mismatch(lo)*mismatch(hi)>0:raise ValueError('Projected draw not bracketed; reject this initialization')
    multiplier=brentq(mismatch,lo,hi,xtol=1e-13,rtol=1e-13)
    liquid,vapor=solve(multiplier);output=[];residual=[]
    for i,row in enumerate(rows):
        l=float(sum(liquid[i]));v=float(sum(vapor[i]))
        if min(l,v)<=0:raise ValueError('Vanished phase in numerical initialization')
        output.append(dict(temperature_K=row['temperature_K'],liquid_flow_mol_s=l,
            vapor_flow_mol_s=0. if i==0 and not stripper else v,
            liquid_mole_fractions=(liquid[i]/l).tolist(),vapor_mole_fractions=(vapor[i]/v).tolist()))
        residual.append(liquid[i]+vapor[i]-feeds[i]-(liquid[i-1] if i else 0)-(vapor[i+1] if i<n-1 else 0))
    maximum=float(np.max(abs(np.array(residual))))
    if maximum>1e-8 or abs(sum(liquid[-1])-(request.feed_molar_flow_mol_s-request.distillate_flow_mol_s))>1e-8:
        raise ValueError('Numerical projection does not close')
    return output,dict(estimates_only=True,source_evidence_id=request.initial_estimate_source_evidence_id,
        numerical_vapor_liquid_ratio_multiplier=multiplier,maximum_stage_component_residual_mol_s=maximum,
        distillate_guess_mol_s=float(sum(vapor[0])),bottoms_guess_mol_s=float(sum(liquid[-1])),
        scope='Initialization projection only; no new equilibrium, duty or accepted product calculation')
