"""Propose bounded expert-rule edits using an autonomous graph and actual ports.

These are hypotheses for model selection and full recalculation. No reference
flowsheet, literature stage count or accepted source simulation is loaded.
"""
import copy


def propose_inventory_repair(basis,candidate,phase_evidence,recovery_fraction=.95,light_draw_margin=1.05):
    if basis.design_id!='H01':return None
    graph=copy.deepcopy(candidate['graph']);observed=candidate.get('partial_execution',{}).get('streams',{})
    fresh=[name for name,fraction in zip(basis.components,basis.fresh_mole_fractions) if fraction>0]
    if len(fresh)!=2 or not phase_evidence:return None
    first=basis.components.index(fresh[0])
    points=[row for row in phase_evidence['points'] if row.get('converged') and row.get('numerical_validation_passed')]
    if not points or not all(row['vapor_mole_fractions'][first]>row['liquid_mole_fractions'][first] for row in points):return None
    light=fresh[0];edits=[];removed=[]
    for unit in graph['units']:
        if unit['kind']!='column' or len(unit['inputs'])!=1:continue
        assignments=[name for name,port in graph['products'].items() if port in [unit['unit_id']+'.distillate',unit['unit_id']+'.bottoms'] and name in {'MCH','TOL'}]
        if len(assignments)!=1:continue
        name=assignments[0];identity='Methylcyclohexane' if name=='MCH' else 'Toluene'
        inlet=observed.get(unit['inputs'][0]);index=basis.components.index(identity)
        requirement=basis.requirements.get(name+'_minimum_mass_fraction')
        if not inlet or requirement is None or inlet.get('mass_fractions',[0.]*len(basis.components))[index]<requirement:continue
        outlets={unit['unit_id']+'.distillate',unit['unit_id']+'.bottoms'}
        if any(set(other['inputs'])&outlets for other in graph['units']):continue
        if any(port in outlets for port in graph.get('constraint_streams',{}).values()):continue
        if any(tear['source_stream'] in outlets for tear in graph.get('tears',[])):continue
        graph['products']={key:port for key,port in graph['products'].items() if port not in outlets}
        graph['products'][name]=unit['inputs'][0];removed.append(unit['unit_id'])
        edits.append(dict(rule='already_qualifying_inlet_phase',unit_id=unit['unit_id'],product=name,
            measured_mass_fraction=inlet['mass_fractions'][index],original_minimum=requirement,
            action='Bypass optional product column; recheck complete process and final product.'))
    graph['units']=[unit for unit in graph['units'] if unit['unit_id'] not in removed]
    columns=[unit for unit in graph['units'] if unit['kind']=='column']
    for recovery in columns:
        inlet=observed.get(recovery['inputs'][0]) if len(recovery['inputs'])==1 else None
        solvent=basis.components.index('Sulfolane')
        if not inlet or inlet['mole_fractions'][solvent]<.5:continue
        if not all(all(row.get('native_vapor_pressures_Pa_at_reference_T',[0.]*len(basis.components))[basis.components.index(name)]>
            10*row.get('native_vapor_pressures_Pa_at_reference_T',[float('inf')]*len(basis.components))[solvent] for name in fresh) for row in points):continue
        following=[unit for unit in columns if unit['inputs']==[recovery['unit_id']+'.distillate']]
        if len(following)!=1:continue
        downstream=following[0]
        if graph['products'].get('TOL')!=downstream['unit_id']+'.bottoms':continue
        if 'Sulfolane' not in basis.allowed_auxiliary_feeds:continue
        for unit,components,multiplier in [(recovery,fresh,recovery_fraction),(downstream,[light],light_draw_margin)]:
            unit.update(distillate_fraction=None,distillate_flow_mol_s=None,
                distillate_inventory_components=components,distillate_inventory_multiplier=multiplier,
                numerical_solver='native',numerical_jacobian_policy='balanced_reduced',initialization_policy='cold')
        edits.append(dict(rule='recover_light_inventory_before_heavy_product',recovery_unit=recovery['unit_id'],
            product_unit=downstream['unit_id'],light_component=light,recovery_inventory_fraction=recovery_fraction,
            light_draw_inventory_multiplier=light_draw_margin,
            action='Explicit inventory-based design candidates; native phase, balance and product acceptance remains mandatory.'))
    return dict(graph=graph,rules=edits,source_candidate_id=candidate['candidate_id']) if edits else None
