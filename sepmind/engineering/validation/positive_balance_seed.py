"""Relative-entropy feasible liquid-flow seed for a no-side-draw stripper.

This convex projection uses physical feed vectors only as balance constraints.
It predicts neither equilibrium nor product performance. The following native
MESH solve and independent review remain mandatory.
"""
import numpy as np
from scipy.optimize import minimize,LinearConstraint,Bounds
from .balanced_mesh import BalancedCoordinates


def positive_balance_seed(estimate,feeds,vapor_scale,liquid_scale,bottoms_flow,reflux_ratio=None,allow_feasible_fallback=False):
    feeds=np.asarray(feeds,dtype=float);n,c=feeds.shape;block=2*c+1
    total=feeds.sum(axis=0)
    if min(total)<=0 or not np.isfinite(feeds).all() or min(feeds.ravel())<0:
        raise ValueError('Positive overall amount of every declared species required')
    a=np.asarray(estimate).reshape(n,block);q0=(a[:,c+1:]*liquid_scale/total).ravel()
    below=np.cumsum(feeds[::-1],axis=0)[::-1]/total
    matrix=np.zeros((n*c,n*c))
    for i in range(n):
        for j in range(c):
            matrix[i*c+j,(n-1)*c+j]-=1
            if i:matrix[i*c+j,(i-1)*c+j]+=1
    offset=below.ravel();draw=np.zeros(n*c);draw[-c:]=total/sum(total)
    floor=1e-20
    incoming_vapor=a[:,1:c+1]*vapor_scale/total
    vapor_floor=np.maximum(floor,1e-3*incoming_vapor.ravel())
    liquid_floor=np.maximum(floor,1e-3*q0)
    # A warm restart often needs only a tiny bottom-draw correction. Preserve
    # all trace-component ratios if that simple correction is already feasible;
    # avoid an ill-conditioned optimization on an almost unchanged solution.
    candidate=q0.copy();candidate[-c:]*=bottoms_flow/(candidate[-c:]@total)
    if (np.isfinite(candidate).all() and np.min(candidate-liquid_floor)>=0
            and np.min(matrix@candidate+offset-vapor_floor)>=0):
        coordinates=BalancedCoordinates(feeds,vapor_scale,liquid_scale,0.,True)
        full=coordinates.expand(np.r_[a[:,0],(candidate.reshape(n,c)*total/liquid_scale).ravel()])
        if reflux_ratio is not None:
            coordinates=BalancedCoordinates(feeds,vapor_scale,liquid_scale,reflux_ratio)
            full=coordinates.expand(coordinates.reduce(full))
        if min(full)>0:
            return full,dict(estimates_only=True,algorithm='feasible_trace_preserving_bottom_draw_rescale',
                             maximum_scaled_adjustment=float(max(abs(candidate-q0))),
                             bottom_draw_residual=float(abs(candidate[-c:]@total-bottoms_flow)))
    # Relative entropy preserves trace-species structure. An unweighted norm
    # can allocate a small bottom-draw correction to an almost absent species,
    # destroying an otherwise close equilibrium estimate.
    weights=np.tile(total/sum(total),n)
    reference=np.maximum(q0,floor)
    objective=lambda q:float(weights@(q*np.log(q/reference)-q+reference))
    sol=minimize(objective,q0,jac=lambda q:weights*np.log(q/reference),method='SLSQP',bounds=Bounds(liquid_floor,np.inf),
                 constraints=[LinearConstraint(matrix,vapor_floor-offset,np.inf),
                              LinearConstraint(draw,bottoms_flow/sum(total),bottoms_flow/sum(total))],
                 options={'ftol':1e-13,'maxiter':300})
    optimization_failed=not sol.success or np.min(matrix@sol.x+offset)<-1e-12 or abs(draw@sol.x-bottoms_flow/sum(total))>1e-10
    if optimization_failed and not allow_feasible_fallback:
        raise ValueError('Positive balance projection failed: '+str(sol.message))
    # A strictly positive interior blend removes SLSQP endpoint roundoff. Both
    # the projection and this simple feasible point satisfy the exact draw.
    interior=np.tile(total*(bottoms_flow/sum(total)),(n,1))
    # Increasing upper-stage liquid by remaining feed provides positive V.
    interior[:-1]+=np.cumsum(feeds[::-1],axis=0)[::-1][1:]
    interior[:-1]+=total
    liquid=interior.copy() if optimization_failed else sol.x.reshape(n,c)*total
    liquid=(1-1e-10)*liquid+1e-10*interior
    reduced=np.r_[a[:,0],(liquid/liquid_scale).ravel()]
    coordinates=BalancedCoordinates(feeds,vapor_scale,liquid_scale,0.,True)
    full=coordinates.expand(reduced)
    if reflux_ratio is not None:
        coordinates=BalancedCoordinates(feeds,vapor_scale,liquid_scale,reflux_ratio)
        full=coordinates.expand(coordinates.reduce(full))
    if np.min(full)<=0:raise ValueError('Projection has a vanished numerical phase coordinate')
    return full,dict(estimates_only=True,algorithm='analytic_feasible_balance_seed' if optimization_failed else 'positive_relative_entropy_balance_projection',
                     optimization_message=str(sol.message),
                     maximum_scaled_adjustment=float(max(abs((liquid/total).ravel()-q0))),
                     bottom_draw_residual=float(abs(liquid[-1].sum()-bottoms_flow)))
