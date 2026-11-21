"""Private DWSIM worker. Only invoked by DwsimBackend in a fresh process."""

import json
import math
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone
from uuid import uuid4


def concrete(value):
    return getattr(value, "__implementation__", value)


def shortcut(manager, payload, Array, Double, ObjectType, StreamSpec):
    from separation.tools.dwsim import ShortcutDistillationRequest
    p = ShortcutDistillationRequest(**payload)
    for name in p.components:
        if not manager.AvailableCompounds.ContainsKey(name):
            raise ValueError(f"Unknown DWSIM compound: {name}")
    if not manager.AvailablePropertyPackages.ContainsKey(p.property_package):
        raise ValueError(f"Unknown DWSIM property package: {p.property_package}")
    flow = concrete(manager.CreateFlowsheet())
    for name in p.components:
        flow.AddCompound(name)
    pp = concrete(flow.CreateAndAddPropertyPackage(p.property_package))

    def add(kind, name, x, y):
        obj = concrete(flow.AddObject(kind, x, y, name))
        obj.PropertyPackage = pp
        return obj

    feed = add(ObjectType.MaterialStream, "Feed", 0, 0)
    distillate = add(ObjectType.MaterialStream, "Distillate", 200, 0)
    bottoms = add(ObjectType.MaterialStream, "Bottoms", 200, 100)
    condenser = add(ObjectType.EnergyStream, "Condenser duty", 200, 200)
    reboiler = add(ObjectType.EnergyStream, "Reboiler duty", 0, 200)
    column = add(ObjectType.ShortcutColumn, "Shortcut column", 100, 50)
    flow.ConnectObjects(feed.GraphicObject, column.GraphicObject, 0, 0)
    flow.ConnectObjects(column.GraphicObject, distillate.GraphicObject, 0, 0)
    flow.ConnectObjects(column.GraphicObject, bottoms.GraphicObject, 1, 0)
    flow.ConnectObjects(reboiler.GraphicObject, column.GraphicObject, 0, 1)
    flow.ConnectObjects(column.GraphicObject, condenser.GraphicObject, 0, 0)
    order = [str(k) for k in flow.SelectedCompounds.Keys]
    fractions = dict(zip(p.components, (p.feed_light_fraction, 1 - p.feed_light_fraction)))
    feed.SetMolarFlow(p.feed_molar_flow_mol_s)
    feed.SetPressure(p.pressure_pa)
    feed.SetTemperature(350.0)
    feed.SetOverallComposition(Array[Double]([fractions[c] for c in order]))
    feed.SpecType = StreamSpec.Pressure_and_VaporFraction
    feed.Phases[2].Properties.molarfraction = 0.0
    column.m_lightkey, column.m_heavykey = p.components
    column.m_lightkeymolarfrac = p.bottoms_light_fraction
    column.m_heavykeymolarfrac = 1 - p.distillate_light_purity
    column.m_refluxratio = p.reflux_ratio
    column.m_condenserpressure = column.m_boilerpressure = p.pressure_pa
    errors = manager.CalculateFlowsheet2(flow)
    if errors is not None and errors.Count:
        raise RuntimeError("; ".join(str(e) for e in errors))
    if not flow.Solved or not column.Calculated:
        raise RuntimeError("Shortcut flowsheet did not solve.")
    d, b = float(distillate.GetMolarFlow()), float(bottoms.GetMolarFlow())
    xd_raw, xb_raw = list(distillate.GetOverallComposition()), list(bottoms.GetOverallComposition())
    xd = [xd_raw[order.index(c)] for c in p.components]
    xb = [xb_raw[order.index(c)] for c in p.components]
    outputs = {
        "stages_estimate": float(column.m_N), "minimum_stages": float(column.m_Nmin),
        "minimum_reflux_ratio": float(column.m_Rmin), "reflux_ratio": p.reflux_ratio,
        "feed_location_stripping_stages_estimate": float(column.ofs),
        "reboiler_duty_kw": float(column.m_Qb), "condenser_duty_kw": float(column.m_Qc),
        "distillate_flow_mol_s": d, "bottoms_flow_mol_s": b,
        "distillate_composition": xd, "bottoms_composition": xb,
        "distillate_light_purity": xd[0],
        "light_recovery": d * xd[0] / (p.feed_molar_flow_mol_s * p.feed_light_fraction),
    }
    numbers = [v for v in outputs.values() if isinstance(v, (float, int))] + xd + xb
    balance = max(abs(p.feed_molar_flow_mol_s * fractions[c] - d * xd[i] - b * xb[i])
                  / p.feed_molar_flow_mol_s for i, c in enumerate(p.components))
    if (not all(math.isfinite(v) for v in numbers) or min(d, b) <= 0
            or any(not 0 <= v <= 1 for v in xd + xb)
            or max(abs(sum(xd) - 1), abs(sum(xb) - 1)) > 1e-6 or balance > 1e-6
            or outputs["minimum_stages"] <= 0
            or outputs["stages_estimate"] < outputs["minimum_stages"]
            or p.reflux_ratio <= outputs["minimum_reflux_ratio"]):
        raise RuntimeError("Shortcut calculation failed numerical or applicability checks.")
    return {"request": payload, "outputs": outputs,
            "checks": {"flowsheet_solved": True, "component_balance_valid": True,
                       "component_balance_relative_residual": balance, "results_finite": True},
            "limitations": [
                "Native DWSIM Fenske-Underwood-Gilliland shortcut, not a rigorous column solution.",
                "Product purity and recovery are imposed split specifications, not independently validated performance.",
                "Saturated-liquid binary feed, total condenser, equal condenser/reboiler pressures.",
                "No tray efficiency, hydraulics, independent energy-balance validation, or economic assessment.",
                "Property parameters and liquid-phase stability require separate validation."]}


def main(request):
    # A workspace-local dependency install avoids changing the user's base Python.
    project_root = Path(__file__).resolve().parents[2]
    local_runtime = project_root / ".runtime/dwsim"
    if local_runtime.is_dir():
        sys.path.insert(0, str(local_runtime))
    import pythonnet
    pythonnet.load("netfx")
    import clr

    root = Path(request["installation"]).resolve()
    for relative in ("", "unitops", "ppacks", "extenders", "ThermoCS"):
        sys.path.append(str(root / relative))
    os.chdir(root)
    for assembly in ("DWSIM.Automation", "DWSIM.Interfaces", "DWSIM.Thermodynamics", "DWSIM.UnitOperations"):
        clr.AddReference(assembly)
    from System import Array, Console, Double
    from System.IO import StringWriter
    from DWSIM.Automation import Automation3
    from DWSIM.Interfaces.Enums import StreamSpec
    from DWSIM.Interfaces.Enums.GraphicObjects import ObjectType

    original_out, original_err = Console.Out, Console.Error
    log = StringWriter()
    Console.SetOut(log)
    Console.SetError(log)
    manager = None
    try:
        manager = Automation3()
        record = {"status": "ok", "backend": "DWSIM", "version": str(manager.GetVersion()),
                  "evidence_id": str(uuid4()),
                  "created_at": datetime.now(timezone.utc).isoformat()}
        if request["action"] == "doctor":
            record.update(installation=str(root), compound_count=manager.AvailableCompounds.Count,
                          property_packages=sorted(str(k) for k in manager.AvailablePropertyPackages.Keys))
        elif request['action'] == 'liquid_condition':
            sys.path.insert(0,str(project_root))
            from separation.tools.dwsim import LiquidConditionRequest
            p=LiquidConditionRequest(**request['payload'])
            flow=concrete(manager.CreateFlowsheet())
            for name in p.components:flow.AddCompound(name)
            pp=concrete(flow.CreateAndAddPropertyPackage(p.property_package))
            s=concrete(flow.AddObject(ObjectType.MaterialStream,0,0,'Cold feed before pump/heater'))
            s.PropertyPackage=pp
            order=[str(k) for k in flow.SelectedCompounds.Keys]
            comp=dict(zip(p.components,(p.light_mole_fraction,1-p.light_mole_fraction)))
            s.SetOverallComposition(Array[Double]([comp[c] for c in order]))
            s.SetMolarFlow(1.);s.SetTemperature(p.temperature_K);s.SetPressure(p.pressure_Pa)
            s.SpecType=StreamSpec.Temperature_and_Pressure
            s.Calculate()
            vf=float(s.Phases[2].Properties.molarfraction or 0.)
            if vf>1e-6:
                raise ValueError('Cold-feed pump calculation requires a single-phase liquid storage state')
            lp=s.Phases[3].Properties
            values={'temperature_K':float(s.GetTemperature()),'pressure_Pa':float(s.GetPressure()),
                    'density_kg_m3':float(lp.density),'viscosity_Pa_s':float(lp.viscosity),
                    'specific_enthalpy_kJ_kg':float(s.GetMassEnthalpy()),'vapor_fraction':vf}
            s.SpecType=StreamSpec.Temperature_and_VaporFraction
            s.SetOverallComposition(Array[Double]([comp[c] for c in order]))
            s.SetTemperature(p.temperature_K)
            s.AtEquilibrium=False
            s.Phases[2].Properties.molarfraction=0.
            s.Calculate()
            values['bubble_pressure_Pa']=float(s.GetPressure())
            if (not all(math.isfinite(v) for v in values.values()) or min(values['density_kg_m3'],values['viscosity_Pa_s'],values['bubble_pressure_Pa'])<=0
                    or values['bubble_pressure_Pa']>=p.pressure_Pa):
                raise RuntimeError('Native cold-liquid state/bubble-pressure validation failed: '+str(values))
            record.update(request=request['payload'],outputs=values,
                checks={'single_phase_liquid':True,'bubble_pressure_below_storage_pressure':True},
                limitations=['Native default transport/enthalpy/bubble-pressure methods under explicit teaching assumptions.',
                             'Cold-state property adequacy is separate from the narrow experimental qualification of the column VLE.'])
        elif request['action'] == 'utility_water':
            sys.path.insert(0,str(project_root))
            from separation.tools.dwsim import UtilityWaterRequest
            p=UtilityWaterRequest(**request['payload'])
            flow=concrete(manager.CreateFlowsheet())
            flow.AddCompound('Water')
            pp=concrete(flow.CreateAndAddPropertyPackage('Steam Tables (IAPWS-IF97)'))
            s=concrete(flow.AddObject(ObjectType.MaterialStream,0,0,'Utility water'))
            s.PropertyPackage=pp
            s.SetMolarFlow(1.)
            s.SetOverallComposition(Array[Double]([1.]))
            hs=[]
            for t in (p.cooling_inlet_K,p.cooling_outlet_K):
                s.SetTemperature(t);s.SetPressure(101325.)
                s.SpecType=StreamSpec.Temperature_and_Pressure
                s.Calculate()
                hs.append(float(s.GetMassEnthalpy()))
            steam=[]
            for vf in (0.,1.):
                s.SetPressure(p.steam_pressure_Pa)
                s.SpecType=StreamSpec.Pressure_and_VaporFraction
                s.Phases[2].Properties.molarfraction=vf
                s.Calculate()
                steam.append(float(s.GetMassEnthalpy()))
            values={'cooling_enthalpy_rise_kJ_kg':hs[1]-hs[0],
                    'steam_latent_heat_kJ_kg':steam[1]-steam[0],
                    'steam_saturation_K':float(s.GetTemperature())}
            if not all(math.isfinite(v) and v>0 for v in values.values()):
                raise RuntimeError('Invalid native IAPWS utility properties')
            record.update(request=request['payload'],outputs=values,
                property_package='Steam Tables (IAPWS-IF97)',
                checks={'positive_utility_enthalpy_changes':True},
                limitations=['Saturated dry steam to saturated condensate; cooling water at 101325 Pa; no utility line loss.'])
        elif request["action"] == "shortcut_distillation":
            sys.path.insert(0, str(project_root))
            record.update(shortcut(manager, request["payload"], Array, Double, ObjectType, StreamSpec))
        elif request["action"] == "rigorous_column":
            sys.path.insert(0, str(project_root))
            from sepmind.engineering.validation.dwsim_column import simulate_column
            record.update(simulate_column(manager, request['payload'], Array, Double, ObjectType, StreamSpec))
        elif request['action']=='mixture_probe':
            sys.path.insert(0,str(project_root))
            from sepmind.engineering.validation.dwsim_mixture import probe_mixture
            record.update(probe_mixture(manager,request['payload'],Array,Double,ObjectType,StreamSpec))
        elif request['action']=='candidate_mixture_column':
            sys.path.insert(0,str(project_root))
            from separation.tools.mixture import CandidateColumnRequest,mixture_card
            from sepmind.engineering.validation.dwsim_mixture import configure_candidate
            from sepmind.engineering.validation.dwsim_column import simulate_column
            p=CandidateColumnRequest.model_validate(request['payload'])
            card,digest=mixture_card(p.property_card_id)
            def setup(flow,pp,arr,number):
                import copy
                numerical_card=copy.deepcopy(card)
                for key in ('A','B_K'):
                    numerical_card[key]=[[p.numerical_homotopy_strength*x for x in row] for row in card[key]]
                return configure_candidate(flow,pp,numerical_card,arr,number)
            record.update(simulate_column(manager,request['payload'],Array,Double,ObjectType,StreamSpec,validated_request=p,property_setup=setup))
            record.update(property_card_id=p.property_card_id,parameter_sha256=digest,
                qualification_only=True,design_admitted=False,
                numerical_homotopy_strength=p.numerical_homotopy_strength,
                intermediate_not_physical_result=p.numerical_homotopy_strength!=1.)
            record['limitations']+=card['limitations']+['Native MESH closure is not thermodynamic parameter qualification. Saved file requires SepMind trusted model initialization before replay.']
        elif request['action']=='multifeed_candidate_column':
            sys.path.insert(0,str(project_root))
            from separation.tools.multifeed import MultiFeedColumnRequest
            from separation.tools.mixture import mixture_card
            from sepmind.engineering.validation.dwsim_mixture import configure_candidate
            from sepmind.engineering.validation.dwsim_column import simulate_column
            p=MultiFeedColumnRequest.model_validate(request['payload'])
            card,digest=mixture_card(p.property_card_id)
            def setup(flow,pp,arr,number):
                return configure_candidate(flow,pp,card,arr,number)
            if p.project_exact_absent_species:
                from sepmind.engineering.validation.absent_species import project_absent_species,restore_absent_species
                native_request,projection=project_absent_species(p)
                native_record=simulate_column(manager,request['payload'],Array,Double,ObjectType,StreamSpec,validated_request=native_request,property_setup=setup)
                record.update(restore_absent_species(native_record,projection))
            else:
                record.update(simulate_column(manager,request['payload'],Array,Double,ObjectType,StreamSpec,validated_request=p,property_setup=setup))
            record.update(property_card_id=p.property_card_id,parameter_sha256=digest,
                          purpose=p.purpose,qualification_only=True,design_admitted=False)
            record['limitations']+=card['limitations']+['Source settings are reconstructed with native DWSIM units; CAPE-OPEN binaries are never loaded.']
        elif request['action']=='topology_binary_column':
            sys.path.insert(0,str(project_root))
            from sepmind.engineering.topology.binary_contracts import BinaryGraphColumnRequest, BinarySparseColumnRequest
            from sepmind.engineering.validation.dwsim_column import simulate_column
            contract=BinarySparseColumnRequest if request['payload'].get('numerical_solver')=='sparse_trust_region' else BinaryGraphColumnRequest
            p=contract(**request['payload'])
            record.update(simulate_column(manager,request['payload'],Array,Double,ObjectType,StreamSpec,validated_request=p))
            record['limitations'].append('Original-case native binary property model; full experimental qualification remains separate.')
        elif request['action']=='topology_binary_stage_probe':
            sys.path.insert(0,str(project_root))
            from sepmind.engineering.topology.binary_contracts import BinaryStageProbeRequest
            from sepmind.engineering.topology.native import stage_probe
            p=BinaryStageProbeRequest.model_validate(request['payload'])
            record.update(stage_probe(manager,p,p.property_package,Array,Double,ObjectType))
        elif request['action']=='ideal_stage_probe':
            sys.path.insert(0,str(project_root))
            from sepmind.engineering.topology.native import ideal_stage_probe
            record.update(ideal_stage_probe(manager,request['payload'],Array,Double,ObjectType))
        elif request['action']=='multicomponent_column':
            sys.path.insert(0,str(project_root))
            from separation.tools.multicomponent import MultiColumnRequest
            from sepmind.engineering.validation.dwsim_column import simulate_column
            p=MultiColumnRequest(**request['payload'])
            record.update(simulate_column(manager,request['payload'],Array,Double,ObjectType,StreamSpec,validated_request=p))
            record['limitations'].append('Multicomponent ideal-assumption adapter only; this run does not qualify acid HOC/VLLE or phenols regeneration.')
        elif request["action"] == "binary_vle":
            p = request["payload"]
            # Validate even when the worker is invoked directly.
            sys.path.insert(0, str(project_root))
            from separation.tools.dwsim import BinaryVLERequest
            from DWSIM.Thermodynamics.PropertyPackages import Phase
            BinaryVLERequest(**p)
            for name in p["components"]:
                if not manager.AvailableCompounds.ContainsKey(name):
                    raise ValueError(f"Unknown DWSIM compound: {name}")
            if not manager.AvailablePropertyPackages.ContainsKey(p["property_package"]):
                raise ValueError(f"Unknown DWSIM property package: {p['property_package']}")
            flow = concrete(manager.CreateFlowsheet())
            for name in p["components"]:
                flow.AddCompound(name)
            # Never rely on dictionary insertion order for mole-fraction arrays.
            compound_order = [str(k) for k in flow.SelectedCompounds.Keys]
            pp = concrete(flow.CreateAndAddPropertyPackage(p["property_package"]))
            stream = concrete(flow.AddObject(ObjectType.MaterialStream, 0, 0, "VLE feed"))
            stream.PropertyPackage = pp
            stream.SetMolarFlow(1.0)  # normalization; this is not the user's feed flow
            stream.SetPressure(p["pressure_pa"])
            stream.SetTemperature(350.0)  # solver initial guess, not an operating constraint
            stream.SpecType = StreamSpec.Pressure_and_VaporFraction
            points = []
            for x in p["liquid_mole_fractions"]:
                composition = dict(zip(p["components"], (x, 1 - x)))
                stream.SetOverallComposition(Array[Double]([composition[c] for c in compound_order]))
                stream.Phases[2].Properties.molarfraction = 0.0
                errors = manager.CalculateFlowsheet2(flow)
                if errors is not None and errors.Count:
                    raise RuntimeError("; ".join(str(e) for e in errors))
                if not flow.Solved or not stream.Calculated:
                    raise RuntimeError(f"Unsolved bubble-point calculation at x={x}.")
                liquid_raw = list(stream.GetPhaseComposition(3))
                vapor_raw = list(stream.GetPhaseComposition(2))
                liquid = [liquid_raw[compound_order.index(c)] for c in p["components"]]
                vapor = [vapor_raw[compound_order.index(c)] for c in p["components"]]
                temperature = float(stream.GetTemperature())
                closure = max(abs(sum(liquid) - 1), abs(sum(vapor) - 1))
                balance = max(abs(liquid[0] - x), abs(liquid[1] - (1 - x)))
                if (not all(math.isfinite(v) and 0 <= v <= 1 for v in liquid + vapor)
                        or not math.isfinite(temperature) or temperature <= 0
                        or closure > 1e-6 or balance > 1e-6):
                    raise RuntimeError(f"Invalid numerical result at x={x}.")
                point={"x": liquid, "y": vapor, "temperature_k": temperature,
                               "composition_closure_residual": closure,
                               "bubble_liquid_balance_residual": balance}
                if p.get('include_enthalpies',False):
                    lp=stream.Phases[3].Properties
                    point['liquid_enthalpy_kJ_mol']=float(lp.enthalpy)*float(lp.molecularWeight)/1000
                    stream.SetPhaseComposition(Array[Double](vapor_raw),Phase.Vapor)
                    stream.Phases[2].Properties.molarfraction=1.
                    pp.CurrentMaterialStream=stream
                    pp.DW_CalcPhaseProps(Phase.Vapor)
                    vp=stream.Phases[2].Properties
                    point['vapor_enthalpy_kJ_mol']=float(vp.enthalpy)*float(vp.molecularWeight)/1000
                    if not all(math.isfinite(point[k]) for k in ('liquid_enthalpy_kJ_mol','vapor_enthalpy_kJ_mol')):
                        raise RuntimeError('Invalid native molar phase enthalpies')
                    stream.Phases[2].Properties.molarfraction=0.
                points.append(point)
            record.update(request=p, points=points, checks={"all_points_solved": True,
                          "compositions_valid": True, "bubble_liquid_balance_valid": True},
                          limitations=["Finite-grid VLE screening, not a proof of global phase behavior.",
                                        "Property-parameter provenance and range are not validated here.",
                                        "Liquid-phase stability and VLLE have not been independently checked.",
                                        "No column simulation, energy balance, or equipment design performed."])
        else:
            raise ValueError("Unsupported DWSIM action.")
        return record
    finally:
        try:
            if manager is not None:
                manager.ReleaseResources()
        finally:
            Console.SetOut(original_out)
            Console.SetError(original_err)
            # Retain plugin/engine diagnostics, while keeping stdout machine-readable.
            diagnostics = str(log.ToString()).strip()
            if diagnostics:
                print(diagnostics, file=sys.stderr)


if __name__ == "__main__":
    try:
        result = main(json.load(sys.stdin))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    # Native Fortran/C optimizers bypass .NET Console.SetOut. Frame exactly one
    # trusted result; their stdout remains diagnostic text, never process data.
    print('\x1eSEPMIND_DWSIM_RESULT_V1\x1e'+json.dumps(result, allow_nan=False)+
          '\x1eSEPMIND_DWSIM_RESULT_END\x1e',flush=True)
