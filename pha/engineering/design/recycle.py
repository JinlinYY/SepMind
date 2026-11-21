"""Bounded component-flow recycling for registered deterministic unit maps.

The callback is trusted developer code, never executable text from an LLM or
uploaded document. No recycle calculation is claimed without a verified unit map.
"""
import numpy as np


def converge_component_recycle(unit_map,initial,relative_tolerance=1e-8,max_iterations=100,damping=.5,*,acceleration='none',upper_bounds=None):
    if not callable(unit_map):raise TypeError('A registered deterministic callable is required; executable strings are forbidden')
    if not 0<relative_tolerance<1 or not 1<=max_iterations<=500 or not 0<damping<=1:raise ValueError('Invalid bounded recycle policy')
    guess=np.asarray(initial,dtype=float)
    if guess.ndim!=1 or len(guess)<2 or not np.isfinite(guess).all() or min(guess)<0:raise ValueError('Invalid initial component flows')
    if acceleration not in ('none','bounded_wegstein'):raise ValueError('Unknown recycle acceleration policy')
    upper=np.full_like(guess,np.inf) if upper_bounds is None else np.asarray(upper_bounds,dtype=float)
    if upper.shape!=guess.shape or np.isnan(upper).any() or min(upper)<=0 or np.any(guess>upper):raise ValueError('Invalid numerical recycle bounds')
    trace=[];previous_guess=None;previous_return=None
    for i in range(max_iterations):
        raw=unit_map(guess.copy())
        if raw.get('validated') is not True:raise ValueError('RECYCLE_UNIT_MAP_UNVALIDATED: reject results before recycle iteration')
        returned=np.asarray(raw['recycle_component_flows'],dtype=float)
        if returned.shape!=guess.shape or not np.isfinite(returned).all() or min(returned)<0:raise ValueError('INVALID_RECYCLE_COMPONENT_FLOW')
        scale=max(float(sum(returned)),float(sum(guess)),1e-12)
        residuals=(returned-guess)/scale
        maximum=float(max(abs(residuals)))
        trace.append({'iteration':i+1,'maximum_component_relative_residual':maximum,'component_relative_residuals':residuals.tolist()})
        if maximum<=relative_tolerance:
            # Re-evaluate from the accepted return; catch stale or stateful maps.
            final=unit_map(returned.copy());check=np.asarray(final['recycle_component_flows'])
            if final.get('validated') is not True or max(abs(check-returned))/max(sum(returned),1e-12)>relative_tolerance:
                raise ValueError('RECYCLE_RECHECK_FAILED')
            return {'converged':True,'component_flows':returned.tolist(),'iterations':i+1,'trace':trace,'unit_map_result':final,
                    'scope':'component recycle fixed point only; external mass/energy and product targets require independent flowsheet review'}
        factor=np.full_like(guess,damping)
        if acceleration=='bounded_wegstein' and previous_guess is not None:
            dx=guess-previous_guess;valid=abs(dx)>max(scale*1e-12,1e-14)
            slope=np.zeros_like(guess);slope[valid]=(returned[valid]-previous_return[valid])/dx[valid]
            valid&=(slope>-.5)&(slope<.8)
            factor[valid]=np.clip(1/(1-slope[valid]),.5,3.)
        trial=guess+factor*(returned-guess)
        trial=np.where(trial<0,returned,trial);trial=np.minimum(trial,upper)
        trace[-1]['numerical_acceleration_factors']=factor.tolist()
        previous_guess=guess.copy();previous_return=returned.copy();guess=trial
    raise ValueError(f'RECYCLE_NONCONVERGENCE: bounded at {max_iterations} iterations; no accepted recycle')


def fresh_solvent_makeup_from_external_losses(streams,solvent_index):
    if not streams or any(s.get('validated') is not True for s in streams):raise ValueError('MAKEUP_REQUIRES_VALIDATED_EXTERNAL_OUTLETS')
    losses=[]
    for s in streams:
        values=np.asarray(s['component_mass_flow_kg_h'],dtype=float)
        if not np.isfinite(values).all() or min(values)<0:raise ValueError('INVALID_SOLVENT_LOSS')
        losses.append(float(values[solvent_index]))
    return {'fresh_solvent_makeup_kg_h':sum(losses),'external_loss_components_kg_h':losses,
            'scope':'steady nonreactive balance on validated external product/waste/purge streams; no arbitrary solvent recovery efficiency'}
