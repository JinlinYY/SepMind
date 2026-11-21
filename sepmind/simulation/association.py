"""Acetic-acid chemical-theory diagnostic, not a Hayden--O'Connell model.

Ideal physical gas, monomer + dimer chemical equilibrium. Apparent component
amounts count acid formula units, so the dimer contains TWO acid units.
Source: Buettner/Maurer 1983, DOI 10.1002/bbpc.19830871010;
pressure convention confirmed by the authors' PRODIAS poster (see model card).
No cross-association, physical virial or solvation terms are represented.
"""
import math

R_J_MOL_K = 8.31446261815324


def acid_dimer_state(temperature_K, pressure_Pa, apparent_acid_fraction):
    T, P, y = temperature_K, pressure_Pa, apparent_acid_fraction
    if not all(math.isfinite(v) for v in (T, P, y)) or T <= 0 or P <= 0 or not 0 <= y <= 1:
        raise ValueError('Invalid dimer equilibrium state')
    kp = math.exp(-19.1001 + 7928.7 / T) * P / 100000.0
    # Kp*(2-y)*s**2 + s - y = 0. Rationalized root avoids cancellation.
    monomer = 2*y/(1+math.sqrt(1+4*kp*(2-y)*y))
    dimer = kp*monomer*monomer
    extent = dimer/(1+dimer)  # mol dimers per apparent mol of mixture
    acid_phi = (2/(1+math.sqrt(1+4*kp*(2-y)*y))) if y else 1.
    return {'true_monomer_fraction': monomer, 'true_dimer_fraction': dimer,
            'extent_per_apparent_mol': extent,
            'acid_fugacity_coefficient': acid_phi,
            'other_fugacity_coefficient': 1+dimer,
            'residual_enthalpy_J_per_apparent_mol': -R_J_MOL_K*7928.7*extent,
            'within_experimental_temperature_range': 318.15 <= T <= 393.15}
