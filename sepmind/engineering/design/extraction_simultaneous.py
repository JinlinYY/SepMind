"""Simultaneous isothermal countercurrent LLE, independently re-flashed.

Solves component balances and equality of chemical potentials. Logarithmic
flow coordinates keep both phases positive; a homogeneous/unstable root is
rejected. This numerical algorithm does not qualify a property model.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from .extraction import contact


def extraction_simultaneous(model,feed,solvent,T,P,stages,carrier_index,initial_profiles,*,require_qualified=True,max_evaluations=300):
    model.check_domain(T,P,require_qualified)
    f=np.asarray(feed,dtype=float);s=np.asarray(solvent,dtype=float);c=len(model.order)
    if type(stages) is not int or not 1<=stages<=30 or len(initial_profiles)!=stages:raise ValueError('Full bounded numerical profiles required')
    if f.shape!=(c,) or s.shape!=(c,) or not np.isfinite(np.r_[f,s]).all() or min(f)<0 or min(s)<0 or min(sum(f),sum(s))<=0:raise ValueError('Invalid physical feed')
    if np.any(f+s<=0):raise ValueError('Use an explicit model projection for exactly absent species')
    scale=float(sum(f+s))
    r0=np.asarray([p['raffinate_kmol_h'] for p in initial_profiles]);e0=np.asarray([p['extract_kmol_h'] for p in initial_profiles])
    if r0.shape!=(stages,c) or e0.shape!=r0.shape or min(r0.min(),e0.min())<=0:raise ValueError('Positive numerical estimates required')
    x0=np.log(np.stack([r0,e0],axis=1).ravel()/scale)
    if min(x0)<-60 or max(x0)>2:raise ValueError('Numerical estimates outside solver coordinates')
    def unpack(x):return np.exp(x.reshape(stages,2,c))*scale
    def residual(x):
        streams=unpack(x);out=[]
        for i in range(stages):
            r,e=streams[i];incoming=(f if i==0 else streams[i-1,0])+(s if i==stages-1 else streams[i+1,1])
            out.extend((incoming-r-e)/scale*20)
            out.extend(model.mu(r/sum(r),T)-model.mu(e/sum(e),T))
        return np.asarray(out)
    size=stages*2*c;pattern=lil_matrix((size,size),dtype=int)
    for i in range(stages):
        pattern[i*2*c:(i+1)*2*c,i*2*c:(i+1)*2*c]=1
        if i:pattern[i*2*c:i*2*c+c,(i-1)*2*c:(i-1)*2*c+c]=1
        if i<stages-1:pattern[i*2*c:i*2*c+c,(i+1)*2*c+c:(i+2)*2*c]=1
    sol=least_squares(residual,x0,bounds=(-60,2),jac_sparsity=pattern.tocsr(),x_scale='jac',
                      tr_options={'atol':1e-12,'btol':1e-12,'maxiter':size*3},
                      ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=max_evaluations)
    streams=unpack(sol.x);errors=residual(sol.x).reshape(stages,2*c)
    closure=float(np.max(abs(errors[:,:c]))/20);equilibrium=float(np.max(abs(errors[:,c:])))
    if closure>1e-8 or equilibrium>1e-6:raise ValueError(f'SIMULTANEOUS_LLE_NONCONVERGENCE: closure={closure}, equilibrium={equilibrium}, {sol.message}')
    profiles=[]
    for i in range(stages):
        r,e=streams[i];incoming=(f if i==0 else streams[i-1,0])+(s if i==stages-1 else streams[i+1,1])
        independent_r,independent_e,flash=contact(model,incoming,T,P,carrier_index,require_qualified=require_qualified)
        if max(max(abs(independent_r-r)),max(abs(independent_e-e)))/scale>1e-7:
            raise ValueError('SIMULTANEOUS_LLE_RECHECK_FAILED: stable independent flash differs from root')
        profiles.append(dict(stage=i+1,inlet_kmol_h=incoming.tolist(),raffinate_kmol_h=r.tolist(),extract_kmol_h=e.tolist(),equilibrium=flash))
    raff=streams[-1,0];extract=streams[0,1]
    overall=float(max(abs(f+s-raff-extract))/scale)
    if overall>1e-7:raise ValueError('SIMULTANEOUS_LLE_OVERALL_NONCLOSURE')
    return dict(configuration='countercurrent',algorithm='simultaneous_component_balances_and_chemical_potentials',stages=stages,
                feed_kmol_h=f.tolist(),solvent_kmol_h=s.tolist(),raffinate_kmol_h=raff.tolist(),extract_kmol_h=extract.tolist(),
                raffinate_mass_fractions=(raff*model.mw/(raff@model.mw)).tolist(),extract_mass_fractions=(extract*model.mw/(extract@model.mw)).tolist(),
                profiles=profiles,evaluations=sol.nfev,property_qualification_required=require_qualified,
                validation=dict(passed=True,component_relative_residual=overall,maximum_stage_relative_residual=closure,maximum_log_activity_residual=equilibrium),
                model_admitted_for_LLE='LLE' in model.card.get('admitted_phases',[]))
