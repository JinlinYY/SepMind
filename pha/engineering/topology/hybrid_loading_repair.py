"""Source-checked computational loading evidence for a bounded H01 revision."""
import hashlib
import json
from pathlib import Path
import numpy as np
from separation.tools.mixture import mixture_card
from .hybrid_repair_rules import propose_inventory_repair


def load_loading_screen(folder,basis):
    folder=Path(folder).resolve()
    rows=json.loads((folder/'summary.json').read_text(encoding='utf8'))
    row=min((row for row in rows if row['passed']),key=lambda row:row['solvent_component_flow_mol_s'])
    ratio=row['solvent_to_original_fresh_molar_ratio']
    paths=[folder/f'ratio{ratio}_extraction.json',folder/f'ratio{ratio}_wash.json']
    extraction,native=[json.loads(path.read_text(encoding='utf8')) for path in paths]
    card,checksum=mixture_card(basis.property_cards[0])
    if native['property_card_id']!=basis.property_cards[0] or native['parameter_sha256']!=checksum:
        raise ValueError('LOADING_SCREEN: source parameter mismatch')
    if not extraction['validation']['passed']:raise ValueError('LOADING_SCREEN: unaccepted extraction')
    fresh=basis.fresh_flow_mol_s*np.asarray(basis.fresh_mole_fractions)
    if not np.allclose(extraction['feed_kmol_h'],3.6*fresh[:3],rtol=0,atol=1e-10):
        raise ValueError('LOADING_SCREEN: immutable original feed mismatch')
    point=native['points'][0]
    if not point['numerical_validation_passed'] or not point['ideal_vapor_screen_passed']:
        raise ValueError('LOADING_SCREEN: native phase or vapor check failed')
    phases=sorted(point['phases'],key=lambda phase:phase['density_kg_m3'])
    z=np.asarray(phases[0]['composition']);mw=np.asarray(card['molecular_weights_g_mol'])
    purity=float(z[0]*mw[0]/(z@mw))
    raff=np.r_[np.array(extraction['raffinate_kmol_h'])/3.6,0.]
    wash=np.asarray(point['request']['mole_fractions'])
    water=wash[3]*sum(raff)/(1-wash[3])
    if purity<basis.requirements['MCH_minimum_mass_fraction']:
        raise ValueError('LOADING_SCREEN: actual phase purity misses original target')
    return dict(solvent_flow_mol_s=float(extraction['solvent_kmol_h'][2]/3.6),
        stages=extraction['stages'],extraction_temperature_K=308.15,wash_temperature_K=point['request']['temperature_K'],
        pressure_Pa=point['request']['pressure_Pa'],wash_water_flow_mol_s=float(water),
        MCH_phase_mass_fraction=purity,native_evidence_id=native['evidence_id'],source_parameter_sha256=checksum,
        sources=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths],
        scope='Validated provisional pure-solvent extraction/wash screen. Contaminated recycle and whole-process acceptance require recalculation.')


def propose_loading_repair(basis,candidate,phase_evidence,certificate,recovery_fraction,light_draw_margin):
    proposal=propose_inventory_repair(basis,candidate,phase_evidence,recovery_fraction,light_draw_margin)
    if proposal is None:return None
    graph=proposal['graph'];units={unit['unit_id']:unit for unit in graph['units']}
    mch_port=graph['products']['MCH'];polish=units[mch_port.split('.')[0]]
    if polish['kind']!='column' or len(polish['inputs'])!=1:return None
    decanter=units[polish['inputs'][0].split('.')[0]]
    if decanter['kind']!='decanter' or not polish['inputs'][0].endswith('.light'):return None
    mixer=units[decanter['inputs'][0].split('.')[0]]
    if mixer['kind']!='mixer':return None
    source_units=[units[reference.split('.')[0]] for reference in mixer['inputs']]
    extraction=next((unit for unit in source_units if unit['kind']=='extraction'),None)
    water=next((unit for unit in source_units if unit['kind']=='auxiliary_feed' and unit['makeup_component']=='Water'),None)
    if extraction is None or water is None:return None
    if extraction['stages']!=certificate['stages'] or extraction['temperature_K']!=certificate['extraction_temperature_K'] or abs(water['target_component_flow_mol_s']-certificate['wash_water_flow_mol_s'])>1e-7 or decanter['temperature_K']!=certificate['wash_temperature_K'] or decanter['pressure_Pa']!=certificate['pressure_Pa']:
        return None
    outlets={polish['unit_id']+'.distillate',polish['unit_id']+'.bottoms'}
    if any(set(unit['inputs'])&outlets for unit in graph['units']):return None
    graph['products']={name:port for name,port in graph['products'].items() if port not in outlets}
    graph['products']['MCH']=polish['inputs'][0]
    graph['units']=[unit for unit in graph['units'] if unit['unit_id']!=polish['unit_id']]
    for unit in graph['units']:
        if unit['kind']=='makeup_mixer' and unit['makeup_component']=='Sulfolane':
            unit['target_component_flow_mol_s']=certificate['solvent_flow_mol_s']
    for tear in graph['tears']:
        if units[tear['source_stream'].split('.')[0]]['kind']=='makeup_mixer':
            tear['component_flows_mol_s'][basis.components.index('Sulfolane')]=certificate['solvent_flow_mol_s']
    proposal['rules'].append(dict(rule='verified_extraction_wash_loading',certificate=certificate,
        action='Select computationally screened circulation and bypass optional product polishing. Final products and recycle must be recalculated under original requirements.'))
    return proposal
