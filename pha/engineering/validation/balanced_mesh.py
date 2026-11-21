"""Damped Newton on native MESH with linear stage balances eliminated.

Only a numerical coordinate change: the residual function is still DWSIM's.
The condenser vapor coordinate is its liquid distillate, as in native NS.
"""
import numpy as np


class BalancedCoordinates:
    def __init__(self, feeds, vapor_scale, liquid_scale, reflux_ratio, reboiled_absorber=False):
        self.feeds=np.asarray(feeds,dtype=float)
        self.n,self.c=self.feeds.shape
        self.block=2*self.c+1
        self.vapor_scale=vapor_scale
        self.liquid_scale=liquid_scale
        self.reflux_ratio=reflux_ratio
        self.reboiled_absorber=reboiled_absorber
        self.below=np.cumsum(self.feeds[::-1],axis=0)[::-1]

    def reduce(self, full):
        a=np.asarray(full).reshape(self.n,self.block)
        if self.reboiled_absorber:return np.r_[a[:,0],a[:,self.c+1:].ravel()]
        return np.r_[a[:,0],a[1:,self.c+1:].ravel()]

    def expand(self, reduced):
        a=np.asarray(reduced)
        liquid=np.empty((self.n,self.c))
        if self.reboiled_absorber:liquid[:]=a[self.n:].reshape(self.n,self.c)*self.liquid_scale
        else:
            liquid[1:]=a[self.n:].reshape(self.n-1,self.c)*self.liquid_scale
            liquid[0]=self.reflux_ratio*(self.below[0]-liquid[-1])
        vapor=np.empty_like(liquid)
        vapor[0]=self.below[0]-liquid[-1]
        vapor[1:]=liquid[:-1]+self.below[1:]-liquid[-1]
        return np.column_stack([a[:self.n],vapor/self.vapor_scale,liquid/self.liquid_scale]).ravel()

    def residual(self, full_residual):
        a=np.asarray(full_residual).reshape(self.n,self.block)
        if self.reboiled_absorber:return np.r_[a[:,0],a[:,self.c+1:].ravel()]
        # Top reflux and condenser split identities are already exact in these
        # coordinates. Retain the condenser bubble equation, every interior
        # energy/VLE equation, and the bottom draw specification.
        return np.r_[a[1:,0],a[0,self.c+1],a[1:,self.c+1:].ravel()]


def balanced_newton(raw, estimate, feeds, vapor_scale, liquid_scale, reflux_ratio, lower, upper, tolerance, max_iterations, reboiled_absorber=False,residual_weights=None,coordinate_scales=None,audit=None,trace_relative_finite_differences=False):
    coordinates=BalancedCoordinates(feeds,vapor_scale,liquid_scale,reflux_ratio,reboiled_absorber)
    u=coordinates.reduce(estimate)
    evaluations=0
    def evaluate(v):
        nonlocal evaluations
        full=coordinates.expand(v)
        if np.any(full<lower) or np.any(full>upper):raise ValueError('Newton trial outside positive native coordinates')
        evaluations+=1
        r=raw(full)
        reduced=coordinates.residual(r)
        if residual_weights is not None:reduced=reduced*residual_weights
        return reduced,float(r@r),full
    residual,sse,full=evaluate(u)
    history=[]
    for iteration in range(min(max_iterations,60)):
        history.append({'iteration':iteration,'native_sum_squares':sse,'reduced_sum_squares':float(residual@residual)})
        if audit is not None:
            audit.update(history=history,last_unaccepted_coordinates=full.tolist(),maximum_scaled_residual=float(max(abs(residual))),
                         maximum_scaled_H=float(max(abs(residual[:coordinates.n]))),scaled_bottom_specification=float(residual[coordinates.n-1]))
        if sse<=tolerance and (residual_weights is None or max(abs(residual))<=1e-7):return full,history,evaluations
        jac=np.empty((len(u),len(u)))
        for j in range(len(u)):
            step=max(abs(u[j])*1e-5,1e-30 if trace_relative_finite_differences else 1e-13)
            found=False
            for _ in range(16):
                for sign in ([1.,-1.] if trace_relative_finite_differences else [1.]):
                    trial=u.copy();trial[j]+=sign*step
                    try:r,_,_=evaluate(trial);found=True;signed_step=sign*step;break
                    except ValueError:continue
                if found:break
                step*=.1
            if not found:raise ValueError('No feasible finite difference for balanced native coordinates')
            jac[:,j]=(r-residual)/signed_step
        if coordinate_scales is None:direction=np.linalg.lstsq(jac,-residual,rcond=1e-12)[0]
        else:
            scaled_jac=jac*coordinate_scales[None,:]
            column_norm=np.maximum(np.linalg.norm(scaled_jac,axis=0),1e-30)
            scaling=coordinate_scales/column_norm
            direction=scaling*np.linalg.lstsq(jac*scaling[None,:],-residual,rcond=1e-12)[0]
        cost=float(residual@residual);accepted=False
        for power in range(24):
            trial=u+direction*(.5**power)
            if audit is not None:
                expanded=coordinates.expand(trial)
                violated=np.flatnonzero((expanded<lower)|(expanded>upper))
                audit['last_line_search']=dict(power=power,violated_native_indices=violated.tolist(),
                    minimum_native_coordinate=float(min(expanded)),maximum_native_coordinate=float(max(expanded)),
                    direction_norm=float(np.linalg.norm(direction)),
                    violated_values=expanded[violated].tolist())
            try:r,s,full_trial=evaluate(trial)
            except (ValueError,ArithmeticError):continue
            if float(r@r)<cost:
                u,residual,sse,full=trial,r,s,full_trial;accepted=True;break
        if not accepted:raise ValueError('Balanced Newton line search failed; last native SSE='+str(sse))
    raise ValueError('Balanced Newton iteration budget exhausted; last native SSE='+str(sse))
