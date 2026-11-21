"""Resample prior autonomous numerical guesses onto a revised stage grid."""
import numpy as np


def initialization_distance(record,request):
    """Preserve inlet topology before comparing aggregate composition.

    A solvent recovery column can have the same aggregate composition as an
    extractive column, while their profiles have different physical roles.
    This only ranks numerical guesses; no accepted result is transferred.
    """
    feeds=record['request']['feeds'];flow=sum(f['flow_mol_s'] for f in feeds)
    old=sum(f['flow_mol_s']*np.asarray(f['mole_fractions']) for f in feeds)/flow
    current=sum(f.flow_mol_s*np.asarray(f.mole_fractions) for f in request.feeds)/request.feed_molar_flow_mol_s
    return (abs(len(feeds)-len(request.feeds)),float(sum(abs(old-current))),
            abs(record['request']['equilibrium_stages']-request.equilibrium_stages))


def resample_profile(record, request):
    rows=record['outputs']['stage_profiles']
    count=request.equilibrium_stages+(request.column_mode=='total_condenser')
    old_grid=np.linspace(0.,1.,len(rows));new_grid=np.linspace(0.,1.,count)
    factor=request.feed_molar_flow_mol_s/sum(feed['flow_mol_s'] for feed in record['request']['feeds'])
    values={key:np.interp(new_grid,old_grid,[row[key] for row in rows]) for key in
        ['temperature_K','liquid_flow_mol_s','vapor_flow_mol_s']}
    fractions={}
    for key in ['liquid_mole_fractions','vapor_mole_fractions']:
        source=np.maximum(np.array([row[key] for row in rows]),1e-30)
        sampled=np.exp(np.column_stack([np.interp(new_grid,old_grid,np.log(source[:,i])) for i in range(source.shape[1])]))
        fractions[key]=sampled/sampled.sum(axis=1)[:,None]
    output=[]
    for index in range(count):
        row={key:float(value[index]) for key,value in values.items()}
        for key in ['liquid_flow_mol_s','vapor_flow_mol_s']:row[key]*=factor
        row.update({key:value[index].tolist() for key,value in fractions.items()})
        output.append(row)
    if request.column_mode=='total_condenser':output[0]['vapor_flow_mol_s']=0.
    return output
