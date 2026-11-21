"""Bounded, physics-tested scheme synthesis and reflux/stage tradeoffs."""
from scipy.optimize import brentq
from .binary import stages


def feasibility(package, basis, vle):
    p = basis.feed.pressure_kPa*1000
    points = vle['points']
    roots = []
    for a,b in zip(points[1:-1],points[2:-1]):
        fa,fb = a['y'][0]-a['x'][0],b['y'][0]-b['x'][0]
        if fa*fb < 0:
            root = float(brentq(lambda x: package.point(x,p)['y'][0]-x,a['x'][0],b['x'][0],xtol=1e-10))
            if not roots or abs(roots[-1]-root)>1e-7:
                roots.append(root)
    from .binary import material_balance
    balance = material_balance(basis)
    xb,xd = balance['xB'],balance['xD']
    differences = [package.point(xb+(xd-xb)*i/200,p)['y'][0]-(xb+(xd-xb)*i/200) for i in range(201)]
    possible = min(differences) > 1e-7 and not any(xb <= r <= xd for r in roots)
    return {'route': 'ordinary_binary_distillation' if possible else None,
            'conditional_feasible':possible,'sampled_y_minus_x_range':[min(differences),max(differences)],
            'azeotropic_compositions_under_model':roots,'feasible_interval_checked':[xb,xd],
            'global_phase_stability_proven':False,'azeotrope_absence_proven':False,
            'scope':'numerical root/target-interval screen under qualified model; no global stability proof',
            'alternatives': [] if possible else [
                {'route':'adsorption_or_membrane_polishing','status':'concept_only_needs_data',
                 'reason':'May bypass a simple-column equilibrium limit; no separation/sizing claim.'},
                {'route':'extractive_distillation','status':'concept_only_needs_solvent_and_ternary_data',
                 'reason':'No entrainer or ternary equilibrium is assumed.'}]}


def tradeoffs(package, basis, balance, minimum):
    """Enumerate choices, retaining numerical failures as counterevidence.

    The score is a transparent dimensionless screening heuristic, not TAC,
    energy, or an economic optimum. All returned quantities come from solvers.
    """
    rows = []
    multipliers = (basis.column.reflux_multiplier,) if basis.column.reflux_multiplier is not None else (1.1,1.25,1.5,1.75,2.0,2.5)
    for multiplier in multipliers:
        candidate = basis.model_copy(deep=True)
        candidate.column.reflux_ratio = multiplier*minimum['minimum_reflux_ratio']
        try:
            result = stages(package,candidate,balance,minimum)
            rows.append({'candidate_id':f'Rmin_x_{multiplier:g}', 'status':'feasible',
                         'R_over_Rmin':multiplier,'reflux_ratio':result['reflux_ratio'],
                         'theoretical_stages_fractional':result['theoretical_stages_fractional'],
                         'theoretical_stages_rounded_up':result['theoretical_stages_rounded_up'],
                         'feed_stage_from_top':result['feed_stage_from_top'],
                         'internal_vapor_kmol_h':(result['reflux_ratio']+1)*balance['D_kmol_h']})
        except ValueError as exc:
            rows.append({'candidate_id':f'Rmin_x_{multiplier:g}','status':'rejected',
                         'R_over_Rmin':multiplier,'reason':str(exc)})
    valid = [r for r in rows if r['status']=='feasible']
    if not valid:
        raise ValueError('STAGE_PINCH: no bounded reflux candidate reached target; numerical counterexamples retained')
    minimum_n = min(r['theoretical_stages_fractional'] for r in valid)
    minimum_v = min(r['internal_vapor_kmol_h'] for r in valid)
    for row in valid:
        row['screening_score'] = .5*row['theoretical_stages_fractional']/minimum_n+.5*row['internal_vapor_kmol_h']/minimum_v
    return {'candidates':rows,'default_candidate_id':min(valid,key=lambda r:r['screening_score'])['candidate_id'],
            'policy':'equal-weight normalized stage count and internal vapor flow; illustrative bounded candidate set; not TAC/energy optimum',
            'weights':{'normalized_stages':.5,'normalized_vapor_flow':.5},'global_optimality_proven':False}
