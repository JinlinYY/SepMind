"""Native DWSIM equilibrium-column validation, separate from Agent design tools."""
import math
import sys
import time
from pathlib import Path
from sepmind.simulation.dwsim import RigorousColumnRequest


def simulate_column(manager, payload, Array, Double, ObjectType, StreamSpec, validated_request=None, property_setup=None):
    p = validated_request or RigorousColumnRequest(**payload)
    concrete = lambda obj: getattr(obj, '__implementation__', obj)
    flow = concrete(manager.CreateFlowsheet())
    for name in p.components:
        if not manager.AvailableCompounds.ContainsKey(name):
            raise ValueError('Unknown DWSIM compound: ' + name)
        flow.AddCompound(name)
    if not manager.AvailablePropertyPackages.ContainsKey(p.property_package):
        raise ValueError('Unknown DWSIM property package')
    pp = concrete(flow.CreateAndAddPropertyPackage(p.property_package))
    if getattr(p,'strict_flash_tolerances',False):
        from .dwsim_mixture import tighten_candidate_flash
        tighten_candidate_flash(pp)
    property_context = property_setup(flow,pp,Array,Double) if property_setup is not None else None
    def add(kind, name, x, y):
        obj = concrete(flow.AddObject(kind, x, y, name))
        obj.PropertyPackage = pp
        return obj
    multifeed = hasattr(p, 'feeds')
    external_condenser=getattr(p,'column_mode','total_condenser')=='reboiled_absorber'
    stage_count=p.equilibrium_stages+(not external_condenser)
    feed_specs = list(p.feeds) if multifeed else [None]
    feeds = [add(ObjectType.MaterialStream, spec.feed_id if spec else 'Feed', 0, 100+60*i)
             for i,spec in enumerate(feed_specs)]
    feed = feeds[0]
    distillate = add(ObjectType.MaterialStream, 'Distillate', 300, 0)
    bottoms = add(ObjectType.MaterialStream, 'Bottoms', 300, 300)
    qc = add(ObjectType.EnergyStream, 'Condenser duty', 350, 70)
    qr = add(ObjectType.EnergyStream, 'Reboiler duty', 0, 300)
    col = add(ObjectType.DistillationColumn, 'Fixed design column', 150, 50)
    col.SetNumberOfStages(stage_count)
    if external_condenser:
        from DWSIM.UnitOperations.UnitOperations import Column
        col.ReboiledAbsorber=True
        col.CondenserType=Column.condtype.Partial_Condenser
    pb = p.bottom_pressure_pa or p.pressure_pa
    col.ColumnPressureDrop = pb - p.pressure_pa
    col.CondenserDeltaP = 0.
    for i, stage in enumerate(col.Stages):
        stage.P = p.pressure_pa + (pb-p.pressure_pa)*i/(stage_count-1)
        stage.Efficiency = 1.
    feed_precision=[]
    for stream,spec in zip(feeds,feed_specs):
        stage_index = spec.stage_index if spec else p.feed_stage
        col.ConnectFeed(stream, stage_index)
        # Installed 9.0.5 ConnectFeed stores a stage name; the solver accepts IDs.
        col.SetStreamFeedStage(stream, stage_index)
    if external_condenser:col.ConnectVaporProduct(distillate)
    else:col.ConnectDistillate(distillate)
    col.ConnectBottoms(bottoms)
    if not external_condenser:col.ConnectCondenserDuty(qc)
    col.ConnectReboilerDuty(qr)
    col.SetCondenserSpec('Reflux Ratio', p.reflux_ratio, '', '')
    col.SetReboilerSpec('Product Molar Flow Rate', p.feed_molar_flow_mol_s-p.distillate_flow_mol_s, 'mol/s', '')
    col.MaxIterations = getattr(p,'solver_iteration_limit',300)
    active_tolerance=getattr(p,'solver_tolerance',1e-5)
    col.InternalLoopTolerance = active_tolerance
    col.ExternalLoopTolerance = active_tolerance
    col.SolvingMethodName = 'Wang-Henke (Bubble Point)'
    col.CreateSolverConvergengeReport = True
    numerical_context=None
    if multifeed and p.numerical_solver=='sparse_trust_region':
        from .native_sparse import register_sparse_solver
        numerical_context=register_sparse_solver(flow,col,p,Array,Double)
    order = [str(k) for k in flow.SelectedCompounds.Keys]
    for stream,spec in zip(feeds,feed_specs):
        fractions = spec.mole_fractions if spec else (p.feed_mole_fractions if hasattr(p,'feed_mole_fractions') else (p.feed_light_fraction,1-p.feed_light_fraction))
        composition = dict(zip(p.components, fractions))
        stage_index = spec.stage_index if spec else p.feed_stage
        temperature = spec.temperature_K if spec else getattr(p,'feed_temperature_K',None)
        stream.SetMolarFlow(spec.flow_mol_s if spec else p.feed_molar_flow_mol_s)
        stream.SetPressure(p.pressure_pa + (pb-p.pressure_pa)*stage_index/(stage_count-1))
        stream.SetTemperature(temperature if temperature is not None else 350.)
        stream.SetOverallComposition(Array[Double]([composition[c] for c in order]))
        specified_enthalpy = spec.specific_enthalpy_kJ_kg if spec is not None else getattr(p,'feed_specific_enthalpy_kJ_kg',None)
        if specified_enthalpy is not None:
            # Preserve the actual upstream enthalpy across a physical connector.
            # Reflashing a saturated outlet at rounded T/P can spuriously add a
            # small vapor fraction and destroy whole-flowsheet energy closure.
            stream.SetMassEnthalpy(specified_enthalpy)
            stream.SpecType = StreamSpec.Pressure_and_Enthalpy
            if getattr(p,'refine_ph_feed',False):
                from .ph_precision import refine_ph_specification
                feed_precision.append(dict(feed_id=spec.feed_id if spec else 'Feed',
                    iterations=refine_ph_specification(stream,specified_enthalpy)))
        elif temperature is not None:
            stream.SpecType = StreamSpec.Temperature_and_Pressure
        else:
            stream.SpecType = StreamSpec.Pressure_and_VaporFraction
            stream.Phases[2].Properties.molarfraction = 0.
    attempts=[]
    # Retry only numerical initialization/method; never alter the physical design.
    solvers = ['Wang-Henke (Bubble Point)', 'Modified Wang-Henke (Bubble Point)',
               'Napthali-Sandholm (Simultaneous Correction)']
    if p.solver_preference == 'simultaneous_correction':
        solvers = solvers[-1:] + solvers[:-1]
    elif p.solver_preference == 'modified_bubble_point':
        solvers = [solvers[1],solvers[0],solvers[2]] if multifeed else solvers[1:] + solvers[:1]
    solvers=solvers[:getattr(p,'solver_attempt_limit',3)]
    if numerical_context is not None:solvers=['Napthali-Sandholm (Simultaneous Correction)']
    for solver in solvers:
        col.SolvingMethodName=solver
        if attempts:
            col.ResetInitialEstimates()
        if p.initial_profile:
            estimates=p.initial_profile
            col.SetInitialTemperatureEstimates(Array[Double]([row['temperature_K'] for row in estimates]))
            col.SetInitialLiquidMolarFlowEstimates(Array[Double]([row['liquid_flow_mol_s'] for row in estimates]))
            col.SetInitialVaporMolarFlowEstimates(Array[Double]([row['vapor_flow_mol_s'] for row in estimates]))
            def composition_estimates(key):
                vector_key='liquid_mole_fractions' if key=='liquid_light_fraction' else 'vapor_mole_fractions'
                if vector_key in estimates[0]:
                    return Array[Array[Double]]([Array[Double]([dict(zip(p.components,row[vector_key]))[c]
                                                                for c in order]) for row in estimates])
                return Array[Array[Double]]([Array[Double]([dict(zip(p.components,(row[key],1-row[key])))[c]
                                                            for c in order]) for row in estimates])
            col.InitialEstimates.LiqCompositions.Clear()
            col.InitialEstimates.VapCompositions.Clear()
            col.SetInitialMolarCompositionEstimates(composition_estimates('liquid_light_fraction'),
                                                   composition_estimates('vapor_light_fraction'))
        try:
            if p.include_profiles:
                print('native_column: solve_start '+solver, file=sys.stderr, flush=True)
            started=time.monotonic()
            errors=manager.CalculateFlowsheet2(flow)
            messages=[str(e) for e in errors] if errors is not None and errors.Count else []
            ok=bool(flow.Solved and col.Calculated and not messages)
            attempts.append({'solver':solver,'converged':ok,'messages':messages,'error':str(col.ErrorMessage),
                             'elapsed_s':time.monotonic()-started})
            if p.include_profiles:
                print('native_column: solve_end '+str(ok)+' '+str(time.monotonic()-started),file=sys.stderr,flush=True)
                if not ok:print('native_column: '+str(attempts[-1])[-2500:],file=sys.stderr,flush=True)
        except Exception as exc:
            ok=False
            attempts.append({'solver':solver,'converged':False,'error':str(exc)})
        if multifeed and p.save_path:
            import json
            status_path=Path(p.save_path).with_suffix('.solver.json')
            status_path.parent.mkdir(parents=True,exist_ok=True)
            status_path.write_text(json.dumps({'request':payload,'attempts':attempts,
                'native_initial_temperature_K':[float(t) for t in col.T0],
                'native_initial_liquid_flows_mol_s':[float(v) for v in col.L0],
                'native_initial_vapor_flows_mol_s':[float(v) for v in col.V0],
                'numerical_solver_records':numerical_context['records'] if numerical_context else [],
                'solver_report':str(col.ColumnSolverConvergenceReport),'accepted':ok},indent=2),encoding='utf8')
        if ok:break
    if not ok:
        if p.save_path:
            Path(p.save_path).parent.mkdir(parents=True,exist_ok=True)
            manager.SaveFlowsheet(flow,p.save_path,True)
        raise RuntimeError('Rigorous fixed-design column did not converge; same-design solver attempts: '+str(attempts))
    roundoff_audit=[]
    def represented(vector,label):
        if not getattr(p,'canonicalize_roundoff_compositions',False):return vector
        from .composition_roundoff import canonicalize_roundoff
        vector,audit=canonicalize_roundoff(vector)
        if audit:roundoff_audit.append(dict(location=label,native_component_order=list(p.components),**audit))
        return vector
    def values(stream, require_liquid=True):
        raw = list(stream.GetOverallComposition())
        liquid=stream.Phases[3].Properties
        density,viscosity=float(liquid.density or 0.),float(liquid.viscosity or 0.)
        transport_ok=all(math.isfinite(x) and x>0 for x in (density,viscosity))
        if require_liquid and not transport_ok:
            raise RuntimeError('Product/feed liquid transport properties are unavailable')
        return {'flow_mol_s': float(stream.GetMolarFlow()),
                **({'pressure_Pa':float(stream.GetPressure())} if multifeed else {}),
                'mole_fractions': represented([float(raw[order.index(c)]) for c in p.components],str(getattr(stream,'Name','native_port'))),
                'temperature_K': float(stream.GetTemperature()),
                'specific_enthalpy_kJ_kg': float(stream.GetMassEnthalpy()),
                'mass_flow_kg_s': float(stream.GetMassFlow()),
                'liquid_properties':{'density_kg_m3':density,'viscosity_Pa_s':viscosity} if transport_ok else None}
    feed_values=[values(s,require_liquid=not multifeed) for s in feeds]
    d,b = values(distillate,require_liquid=not external_condenser),values(bottoms)
    if multifeed:
        total_mass=sum(s['mass_flow_kg_s'] for s in feed_values)
        f={'flow_mol_s':sum(s['flow_mol_s'] for s in feed_values),
           'mole_fractions':[sum(s['flow_mol_s']*s['mole_fractions'][i] for s in feed_values)/p.feed_molar_flow_mol_s for i in range(len(p.components))],
           'temperature_K':None,'mass_flow_kg_s':total_mass,
           'specific_enthalpy_kJ_kg':sum(s['specific_enthalpy_kJ_kg']*s['mass_flow_kg_s'] for s in feed_values)/total_mass,
           'liquid_properties':None,'aggregate_only':True}
    else:f=feed_values[0]
    if getattr(p,'single_feed_graph',False):
        f=feed_values[0]
    # DWSIM's column convention: condenser removal positive, reboiler input negative.
    qc_kw,qr_kw = (0. if external_condenser else float(col.CondenserDuty)),-float(col.ReboilerDuty)
    residuals = [(f['flow_mol_s']*f['mole_fractions'][i]-d['flow_mol_s']*d['mole_fractions'][i]-b['flow_mol_s']*b['mole_fractions'][i])/f['flow_mol_s'] for i in range(len(p.components))]
    energy_in = f['specific_enthalpy_kJ_kg']*f['mass_flow_kg_s']+qr_kw
    energy_out = d['specific_enthalpy_kJ_kg']*d['mass_flow_kg_s']+b['specific_enthalpy_kJ_kg']*b['mass_flow_kg_s']+qc_kw
    energy_residual = abs(energy_in-energy_out)/max(abs(qc_kw),abs(qr_kw),1.)
    specification_error=0.
    if multifeed:
        specification_error=abs(d['flow_mol_s']-p.distillate_flow_mol_s)/p.distillate_flow_mol_s
        if not external_condenser:
            actual_reflux=float(col.Lf[0])/d['flow_mol_s']
            specification_error=max(specification_error,abs(actual_reflux-p.reflux_ratio)/p.reflux_ratio)
    all_numbers = [qc_kw, qr_kw, energy_residual]+residuals + [v for s in (*feed_values,d,b) for v in (s['flow_mol_s'],s['temperature_K'],*s['mole_fractions'])]
    physical = all(math.isfinite(v) for v in all_numbers) and all(0<=x<=1 for s in (f,d,b) for x in s['mole_fractions']) and min(d['flow_mol_s'],b['flow_mol_s'])>0
    if not physical or max(map(abs,residuals))>1e-4 or energy_residual>1e-4 or specification_error>1e-4:
        if p.save_path:
            from sepmind.engineering.tools.atomic_recovery import save
            rejected_profiles=[dict(temperature_K=float(col.Tf[i]),liquid_flow_mol_s=float(col.Lf[i]),
                vapor_flow_mol_s=float(col.Vf[i]),
                liquid_mole_fractions=[float(col.xf[i][order.index(c)]) for c in p.components],
                vapor_mole_fractions=[float(col.yf[i][order.index(c)]) for c in p.components]) for i in range(stage_count)]
            diagnostic=dict(status='rejected',scope='Unaccepted native coordinates and ports, for numerical diagnosis only',
                components=list(p.components),feed=f,distillate=d,bottoms=b,stage_profiles=rejected_profiles,
                physical=physical,component_residuals=residuals,energy_residual=energy_residual)
            try:save(Path(p.save_path).with_suffix('.rejected_outputs.json'),diagnostic)
            except (ValueError,TypeError):pass
        raise RuntimeError(f'Column failed independent closure: mass={residuals}, energy={energy_residual}, duties={qc_kw,qr_kw}, '
                           f'specification={specification_error}, actual_D_B={d["flow_mol_s"],b["flow_mol_s"]}, physical={physical}')
    saved = None
    if p.save_path:
        Path(p.save_path).parent.mkdir(parents=True, exist_ok=True)
        manager.SaveFlowsheet(flow, p.save_path, True)
        saved = p.save_path
    profile = []
    if p.include_profiles:
        print('native_column: transport_start',file=sys.stderr,flush=True)
        # Evaluate each already-converged phase at its native stage T/P/x/y.
        # Re-flashing every near-azeotropic phase is unnecessary and can fail or
        # choose a different branch. DW_CalcPhaseProps does no new flash.
        from DWSIM.Thermodynamics.PropertyPackages import Phase,State
        probe = add(ObjectType.MaterialStream, 'Native phase-property probe', 500, 400)
        probe.SetMolarFlow(1.)
        def phase_props(fractions, temperature, pressure, vapor_fraction):
            probe.SetPressure(pressure)
            probe.SetTemperature(temperature)
            comp = dict(zip(p.components,fractions))
            array = Array[Double]([comp[c] for c in order])
            probe.SetOverallComposition(array)
            phase_enum = Phase.Vapor if vapor_fraction else Phase.Liquid1
            phase_index = 2 if vapor_fraction else 3
            probe.SetPhaseComposition(array,phase_enum)
            probe.Phases[phase_index].Properties.molarfraction=1.
            pp.CurrentMaterialStream=probe
            pp.DW_CalcPhaseProps(phase_enum)
            phase = probe.Phases[phase_index].Properties
            answer = {'temperature_K':temperature,
                      'density_kg_m3':float(phase.density),
                      'viscosity_Pa_s':float(phase.viscosity),
                      'molecular_weight_kg_kmol':float(phase.molecularWeight),
                      'specific_enthalpy_kJ_kg':float(phase.enthalpy)}
            if not vapor_fraction:
                answer['surface_tension_N_m'] = float(pp.AUX_SURFTM(3,temperature))
                # This phase-property slot can contain only the departure Cp
                # (zero for Ideal), not the complete liquid heat capacity.
                # Check the actual configured enthalpy derivative at fixed x/P.
                answer['native_phase_property_Cp_kJ_kg_K']=float(phase.heatCapacityCp)
                answer['heat_capacity_kJ_kg_K']=(float(pp.DW_CalcEnthalpy(array,temperature+.01,pressure,State.Liquid))-
                    float(pp.DW_CalcEnthalpy(array,temperature-.01,pressure,State.Liquid)))/.02
                if answer['heat_capacity_kJ_kg_K']<=0:raise RuntimeError('Nonpositive fixed-composition native liquid heat capacity')
                answer['heat_capacity_method']='central derivative of configured native enthalpy, fixed composition/P, deltaT=0.01 K'
            if not all(math.isfinite(v) for v in answer.values() if isinstance(v,(int,float))) or min(answer['density_kg_m3'],answer['viscosity_Pa_s'])<=0:
                raise RuntimeError('Nonphysical native transport properties')
            return answer
        for i in range(stage_count):
            row = {'stage_index_including_condenser': i,
                'temperature_K': float(col.Tf[i]), 'pressure_Pa': float(col.Stages[i].P),
                'liquid_flow_mol_s': float(col.Lf[i]), 'vapor_flow_mol_s': float(col.Vf[i]),
                'liquid_mole_fractions': represented([float(col.xf[i][order.index(c)]) for c in p.components],f'stage_{i}_liquid'),
                'vapor_mole_fractions': represented([float(col.yf[i][order.index(c)]) for c in p.components],f'stage_{i}_vapor')}
            if (0<=i<p.equilibrium_stages-1) if external_condenser else (0<i<p.equilibrium_stages):
                row['liquid_properties'] = phase_props(row['liquid_mole_fractions'],row['temperature_K'],row['pressure_Pa'],0.)
                row['vapor_properties'] = phase_props(row['vapor_mole_fractions'],row['temperature_K'],row['pressure_Pa'],1.)
                row['transport_temperature_source'] = 'native_converged_equilibrium_stage; no additional flash'
            profile.append(row)
        print('native_column: transport_end',file=sys.stderr,flush=True)
    if multifeed:
        temperature_guard=getattr(p,'temperature_guard_K',None)
        if temperature_guard is None:
            from sepmind.simulation.mixture import mixture_card
            card,_=mixture_card(p.property_card_id)
            temperature_guard=card['temperature_guard_K']
        tlo,thi=temperature_guard
        if any(not tlo<=float(t)<=thi for t in col.Tf):
            raise RuntimeError('Native stage temperature exceeds the property-card calculation guard; no design result accepted')
    return {'request':payload, 'outputs':{'feed':f,**({'feeds':feed_values} if multifeed else {}),'distillate':d,'bottoms':b,
            'condenser_duty_kW':qc_kw,'reboiler_duty_kW':qr_kw,
            **({'overhead_vapor':d} if external_condenser else {}),
            'light_recovery':d['flow_mol_s']*d['mole_fractions'][0]/(f['flow_mol_s']*f['mole_fractions'][0]) if f['mole_fractions'][0]>0 else None,
            'stage_temperatures_K':[float(t) for t in col.Tf], 'stage_profiles':profile},
            'checks':{'flowsheet_solved':True,'product_compositions_imposed':False,
                      'mass_acceptance_relative_to_feed':1e-4,'energy_acceptance_relative':1e-4,
                      'component_balance_relative_residual':max(map(abs,residuals)),
                      'energy_balance_relative_residual':energy_residual,'results_physical':physical,
                      **({'specification_maximum_relative_residual':specification_error} if multifeed else {})},
            'mapping':{'DWSIM_stages_including_condenser':stage_count,'column_mode':getattr(p,'column_mode','total_condenser'),
                       'DWSIM_feed_stage_zero_based':p.feed_stage,'stage_efficiency':1.,
                       'specifications':['bottoms_molar_flow','explicit_external_reflux_feed'] if external_condenser else ['condenser_reflux_ratio','bottoms_molar_flow'],
                       'feed_state':'multiple_independent_TP_feeds' if multifeed else ('specified_pressure_enthalpy' if getattr(p,'feed_specific_enthalpy_kJ_kg',None) is not None else 'specified_temperature_pressure' if getattr(p,'feed_temperature_K',None) is not None else 'saturated_liquid'), 'solver':col.SolvingMethodName,
                       **({'feeds':[s.model_dump() for s in p.feeds]} if multifeed else {}),
                       'solver_internal_external_tolerances':[active_tolerance,active_tolerance],
                       'initial_estimates_source_evidence_id':p.initial_estimate_source_evidence_id,
                       'initial_estimates_are_not_product_specifications':True,
                       'duty_convention':'positive condenser heat removed and positive reboiler heat supplied; native reboiler sign reversed'},
            'saved_flowsheet':saved,'solver_attempts':attempts,'solver_report':str(col.ColumnSolverConvergenceReport),
            **({'feed_ph_precision':feed_precision} if feed_precision else {}),
            **({'native_composition_roundoff_audit':roundoff_audit} if roundoff_audit else {}),
            **({'numerical_solver_records':numerical_context['records']} if numerical_context else {}),
            'limitations':['Equilibrium-stage validation; actual tray efficiency and hydraulics are not validated.',
                           'DWSIM property parameters may share ChemSep provenance with the Agent; this is not independent experimental proof.']}
