"""Interpret an actual finite binary VLE scan without claiming ternary proof."""
import math


def review_binary_boundary(probe,first_index,second_index,target_mass_fraction,molecular_weights):
    if not 0<target_mass_fraction<1 or first_index==second_index:raise ValueError('Invalid binary target')
    points=[]
    for row in probe['points']:
        if row.get('converged') is not True:raise ValueError('All boundary probe points must pass native numerical review')
        xs=row['request']['mole_fractions'];ys=row['vapor_mole_fractions']
        if any(xs[i]!=0 for i in range(len(xs)) if i not in (first_index,second_index)):
            raise ValueError('An explicitly binary scan is required')
        if abs(xs[first_index]+xs[second_index]-1)>1e-9:raise ValueError('Nonclosing binary feed')
        points.append((xs[first_index],ys[first_index]-xs[first_index]))
    points.sort()
    if len(points)<3 or len({p[0] for p in points})!=len(points):raise ValueError('Distinct finite VLE scan required')
    brackets=[(a[0],b[0]) for a,b in zip(points,points[1:]) if a[1]*b[1]<0]
    ma,mb=molecular_weights[first_index],molecular_weights[second_index]
    target_x=(target_mass_fraction/ma)/(target_mass_fraction/ma+(1-target_mass_fraction)/mb)
    if not math.isfinite(target_x):raise ValueError('Invalid molecular weights')
    return {'source_evidence_id':probe['evidence_id'],'property_card_id':probe['property_card_id'],
        'binary_azeotrope_brackets_mole_fraction':brackets,'target_mass_fraction':target_mass_fraction,
        'target_mole_fraction':target_x,'binary_target_above_detected_bracket':any(target_x>hi for lo,hi in brackets),
        'next_gate':'property_and_multicomponent_route_review' if brackets else 'additional_phase_screening',
        'ternary_infeasibility_proved':False,'design_admitted':False,
        'scope':'Finite scan sign-change evidence under a candidate model; no experimental or full ternary feasibility claim.'}
