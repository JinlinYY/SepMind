"""Necessary product-draw bounds from actual inlet component inventories."""
import numpy as np


def product_draw_bounds(basis, graph, unit, incoming, molecular_weights):
    incoming=np.asarray(incoming,dtype=float)
    total=float(sum(incoming))
    checks=[]
    for product,reference in graph.products.items():
        if reference not in {unit.unit_id+'.distillate',unit.unit_id+'.bottoms'}:
            continue
        fraction=(unit.distillate_flow_mol_s/total if getattr(unit,'distillate_flow_mol_s',None) is not None
            else unit.distillate_fraction)
        if reference.endswith('.bottoms'):fraction=1-fraction
        if basis.design_id=='H02' and product=='TOL':
            impurity=basis.components.index('Phenol')
            limit=basis.requirements['TOL_product_phenol_maximum_mole_fraction']
            maximum=(total-incoming[impurity])/(1-limit)
        elif basis.design_id=='H01' and product in {'MCH','TOL'}:
            identity='Methylcyclohexane' if product=='MCH' else 'Toluene'
            index=basis.components.index(identity)
            purity=basis.requirements[product+'_minimum_mass_fraction']
            weights=np.asarray(molecular_weights,dtype=float)
            impurity_minimum_weight=float(min(np.delete(weights,index)))
            maximum=incoming[index]*(1+weights[index]*(1-purity)/(purity*impurity_minimum_weight))
        else:
            continue
        draw=total*fraction
        checks.append(dict(product=product,unit_id=unit.unit_id,product_port=reference,
            proposed_distillate_fraction=unit.distillate_fraction,
            necessary_distillate_fraction_bound=('upper' if reference.endswith('.distillate') else 'lower'),
            necessary_distillate_fraction_limit=float(maximum/total if reference.endswith('.distillate') else 1-maximum/total),
            actual_feed_components_mol_s=incoming.tolist(),
            proposed_product_flow_mol_s=draw,necessary_maximum_product_flow_mol_s=float(maximum),
            passed=bool(draw<=maximum+1e-10*max(total,1.))))
    return checks
