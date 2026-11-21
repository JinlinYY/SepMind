"""Numerical residual correction around native PH calculations."""
import math


def refine_ph_specification(stream, target_enthalpy, tolerance=1e-8, maximum_iterations=48):
    trial=float(target_enthalpy)
    history=[]
    negative=None
    positive=None
    for iteration in range(maximum_iterations):
        stream.SetMassEnthalpy(trial)
        stream.Calculate()
        actual=float(stream.GetMassEnthalpy())
        if not math.isfinite(actual):
            raise ValueError('PH_REFINEMENT: nonfinite native enthalpy')
        error=target_enthalpy-actual
        history.append(dict(iteration=iteration,target_enthalpy_kJ_kg=target_enthalpy,
            numerical_specification_kJ_kg=trial,actual_enthalpy_kJ_kg=actual,
            relative_error=abs(error)/max(abs(target_enthalpy),1.)))
        if history[-1]['relative_error']<=tolerance:
            # The next native flowsheet solve must evaluate this numerical
            # specification again. Its resulting physical H is independently
            # compared against the unchanged target.
            stream.SetMassEnthalpy(trial)
            stream.Calculated=False
            return history
        if error<0:negative=(trial,error)
        elif error>0:positive=(trial,error)
        if negative is not None and positive is not None:
            trial=(negative[0]+positive[0])/2
        else:
            trial+=error
    import json
    raise ValueError('PH_REFINEMENT: native enthalpy did not reach the original target; '+json.dumps(history))
