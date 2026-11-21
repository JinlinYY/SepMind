"""Exact absent-species elimination for native column coordinates.

The physical request and full source parameter table are preserved. No positive
trace material is introduced. Native results are restored to the original order.
"""
import copy
import numpy as np


class NativeColumnView:
    def model_copy(self,update):
        result=copy.copy(self)
        result.__dict__=dict(self.__dict__,**update)
        return result


def project_absent_species(request):
    total=np.sum([feed.flow_mol_s*np.asarray(feed.mole_fractions) for feed in request.feeds],axis=0)
    active=np.flatnonzero(total>0).tolist()
    if len(active)<2 or len(active)==len(request.components):return request,None
    view=NativeColumnView()
    view.__dict__.update(request.model_dump())
    view.components=tuple(request.components[i] for i in active)
    view.property_package=request.property_package
    view.feed_molar_flow_mol_s=request.feed_molar_flow_mol_s
    view.feed_mole_fractions=[request.feed_mole_fractions[i] for i in active]
    view.feed_temperature_K=request.feed_temperature_K
    view.feed_stage=request.feed_stage
    view.feeds=[feed.model_copy(update={'mole_fractions':[feed.mole_fractions[i] for i in active]}) for feed in request.feeds]
    if request.initial_profile:
        view.initial_profile=copy.deepcopy(request.initial_profile)
        for row in view.initial_profile:
            for key in ['liquid_mole_fractions','vapor_mole_fractions']:
                values=np.asarray(row[key])[active]
                if sum(values)<=0:raise ValueError('ABSENT_SPECIES: numerical phase has no active components')
                row[key]=(values/sum(values)).tolist()
    return view,dict(active_indices=active,original_components=list(request.components),
        absent_indices=np.flatnonzero(total==0).tolist(),original_feed_inventory_mol_s=total.tolist(),
        physical_feeds_unchanged=True,parameter_policy='Exact source submatrix selected by native compound identity; no new parameter or trace material.')


def restore_absent_species(record,projection):
    if projection is None:return record
    result=copy.deepcopy(record)
    size=len(projection['original_components']);active=projection['active_indices']
    restored=set()
    def expand(row,keys):
        if id(row) in restored:return
        restored.add(id(row))
        for key in keys:
            if key not in row:continue
            values=np.zeros(size)
            values[active]=row[key]
            row[key]=values.tolist()
    outputs=result['outputs']
    for key in ['feed','distillate','bottoms','overhead_vapor']:
        if key in outputs:expand(outputs[key],['mole_fractions'])
    for feed in outputs.get('feeds',[]):expand(feed,['mole_fractions'])
    for row in outputs.get('stage_profiles',[]):expand(row,['liquid_mole_fractions','vapor_mole_fractions'])
    result['absent_species_projection']=projection
    return result
