"""Read-only native fugacity evaluation for independently reviewed stage arrays."""
import math
from sepmind.simulation.multicomponent import IdealStageProbeRequest


def ideal_stage_probe(manager, payload, Array, Double, ObjectType):
    request = IdealStageProbeRequest.model_validate(payload)
    return stage_probe(manager, request, "Raoult's Law", Array, Double, ObjectType)


def stage_probe(manager, request, property_package, Array, Double, ObjectType):
    from DWSIM.Thermodynamics.PropertyPackages import State
    concrete = lambda value: getattr(value, '__implementation__', value)
    flow = concrete(manager.CreateFlowsheet())
    for name in request.components:
        if not manager.AvailableCompounds.ContainsKey(name):
            raise ValueError('Native compound unavailable')
        flow.AddCompound(name)
    package = concrete(flow.CreateAndAddPropertyPackage(property_package))
    stream = concrete(flow.AddObject(ObjectType.MaterialStream, 0, 0, 'Stage residual probe'))
    stream.PropertyPackage = package
    order = [str(name) for name in flow.SelectedCompounds.Keys]
    positions = [request.components.index(name) for name in order]
    rows = []
    for point in request.points:
        liquid = Array[Double]([point.liquid_mole_fractions[index] for index in positions])
        vapor = Array[Double]([point.vapor_mole_fractions[index] for index in positions])
        stream.SetOverallComposition(liquid)
        stream.SetMolarFlow(1.)
        stream.SetTemperature(point.temperature_K)
        stream.SetPressure(point.pressure_Pa)
        package.CurrentMaterialStream = stream
        phi_l = list(package.DW_CalcFugCoeff(liquid, point.temperature_K, point.pressure_Pa, State.Liquid))
        phi_v = list(package.DW_CalcFugCoeff(vapor, point.temperature_K, point.pressure_Pa, State.Vapor))
        values_l = [float(phi_l[order.index(name)]) for name in request.components]
        values_v = [float(phi_v[order.index(name)]) for name in request.components]
        if any(not math.isfinite(value) or value <= 0 for value in values_l+values_v):
            raise ValueError('Nonphysical native fugacity coefficient')
        rows.append({'point_id': point.point_id, 'liquid_fugacity_coefficients': values_l,
                     'vapor_fugacity_coefficients': values_v})
    return {'request': request.model_dump(), 'points': rows,
            'property_package': property_package, 'native_component_order': order,
            'limitations': ['Same native thermodynamic implementation used to evaluate independent residual arithmetic.',
                            'Explicit ideal model hypothesis requires separate experimental applicability evidence.']}
