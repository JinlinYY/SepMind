"""Typed inventory/load repairs of an existing autonomous extractive graph.

No reference flowsheet, reference geometry or accepted product is read here.
Candidate settings are hypotheses; only native execution can accept them.
"""
import copy
from .hybrid_autonomous import HybridGraph, validate_hybrid_graph


def propose_repair(basis, base, phase_screen, *, solvent_fraction=.75,
                   stages=40, reflux=4., recovery_stages=24, recovery_reflux=2.,
                   light_draw_multiplier=1.002, hydrocarbon_draw_multiplier=.9995,
                   intercolumn_temperature_K=None):
    if basis.design_id!='H02' or basis.fresh_state_specification!='TP':
        raise ValueError('H02_ORIGINAL_TP_REQUIRED')
    points=phase_screen['points']
    point=next((p for p in points if abs(float(p['point_id'])-solvent_fraction)<1e-12),None)
    if point is None or not point.get('numerical_validation_passed'):
        raise ValueError('COMPUTED_SOLVENT_LOADING_REQUIRED')
    x,y=point['liquid_mole_fractions'],point['vapor_mole_fractions']
    alpha=y[2]*x[1]/(y[1]*x[2])
    if alpha<=1:raise ValueError('NO_COMPUTED_MCH_ENRICHMENT')
    g=copy.deepcopy(base['graph']); by_id={u['unit_id']:u for u in g['units']}
    light=by_id[g['products']['MCH'].split('.')[0]]
    heavy=by_id[g['products']['TOL'].split('.')[0]]
    solvent=next((by_id[r.split('.')[0]] for r in light['inputs'] if r!='fresh'
                  and by_id[r.split('.')[0]]['kind']=='makeup_mixer'),None)
    if light['kind']!='column' or heavy['kind']!='column' or solvent is None:
        raise ValueError('REPAIR_REQUIRES_EXISTING_TWO_COLUMN_SOLVENT_GRAPH')
    card=basis.property_cards[-1]; p=basis.fresh_pressure_Pa
    circulation=basis.fresh_flow_mol_s*solvent_fraction/(1-solvent_fraction)
    light.update(inputs=['fresh',solvent['unit_id']+'.out'],stages=stages,
        feed_stages=[round(.65*stages),max(2,round(.125*stages))],reflux_ratio=reflux,
        distillate_fraction=None,distillate_flow_mol_s=None,
        distillate_inventory_components=['Methylcyclohexane'],
        distillate_inventory_multiplier=light_draw_multiplier,pressure_Pa=p,bottom_pressure_Pa=None,
        numerical_solver='sparse_trust_region',initialization_policy='auto',initialization_evidence_id=None)
    heavy.update(inputs=[light['unit_id']+'.bottoms'],stages=recovery_stages,
        feed_stages=[round(.5*recovery_stages)],reflux_ratio=recovery_reflux,
        distillate_fraction=None,distillate_flow_mol_s=None,
        distillate_inventory_components=['Toluene','Methylcyclohexane'],
        distillate_inventory_multiplier=hydrocarbon_draw_multiplier,pressure_Pa=p,bottom_pressure_Pa=None,
        numerical_solver='sparse_trust_region',initialization_policy='auto',initialization_evidence_id=None)
    solvent.update(inputs=['tear.T1'],temperature_K=373.,pressure_Pa=p,
        target_component_flow_mol_s=circulation)
    g.update(units=[light,heavy,solvent],products={'MCH':light['unit_id']+'.distillate',
        'TOL':heavy['unit_id']+'.distillate'},constraint_streams={'solvent_rich':light['unit_id']+'.bottoms',
        'solvent_recycle':heavy['unit_id']+'.bottoms'},tears=[dict(tear_id='T1',
        source_stream=heavy['unit_id']+'.bottoms',component_flows_mol_s=[circulation,0.,0.],
        temperature_K=373.,pressure_Pa=p)])
    if intercolumn_temperature_K is not None:
        identifier=next('U'+str(i) for i in range(1,100) if 'U'+str(i) not in {light['unit_id'],heavy['unit_id'],solvent['unit_id']})
        g['units'].append(dict(unit_id=identifier,kind='conditioner',inputs=[light['unit_id']+'.bottoms'],
            property_card_id=card,temperature_K=intercolumn_temperature_K,pressure_Pa=p))
        heavy['inputs']=[identifier+'.out']
    graph=HybridGraph.model_validate(g);validate_hybrid_graph(graph,basis)
    return dict(graph=graph.model_dump(),source_candidate_id=base['candidate_id'],
        rules=[dict(rule='computed_loading_not_reference_solvent_rate',fraction=solvent_fraction,
                    computed_alpha=alpha,circulation_mol_s=circulation),
               dict(rule='draw_from_actual_inventory_not_half_total_solvent_flow',
                    light_multiplier=light_draw_multiplier,hydrocarbon_multiplier=hydrocarbon_draw_multiplier),
               dict(rule='remove_unjustified_purge_and_duplicate_fixed_makeup',
                    reason='Return all regenerated solvent; actual makeup restores solvent inventory.')],
        scope='Development continuation of an actual autonomous graph; fresh TP and all original targets frozen; no reference parameter injection.')
