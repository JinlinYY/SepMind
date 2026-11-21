"""Trusted native mixture-property qualification; never returns a design pass.

DWSIM performs the flashes. Source-backed NRTL coefficients are converted from
dimensionless A+B/T to DWSIM's (a+b*T)/(1.98721*T), in cal/mol.
The vapor hook is chemical-theory dimerization, explicitly NOT NRTL-HOC.
"""
import math
from sepmind.simulation.mixture import MixtureProbeRequest, mixture_card
from sepmind.simulation.association import acid_dimer_state


def tighten_candidate_flash(pp):
    """Numerical repair only; do not change model equations or accept ideal fallback.

    Installed DWSIM defaults PT/PH tolerances to 1e-4, looser than the column's
    1e-5 iteration tolerance and the independent 1e-7 material check.
    This policy applies only to new candidate studies, not frozen binary runs.
    """
    from DWSIM.Interfaces.Enums import FlashSetting
    policy={
        'PTFlash_External_Loop_Tolerance':'1e-10','PTFlash_Internal_Loop_Tolerance':'1e-10',
        'PHFlash_External_Loop_Tolerance':'1e-9','PHFlash_Internal_Loop_Tolerance':'1e-9',
        'PTFlash_Maximum_Number_Of_External_Iterations':'300',
        'PTFlash_Maximum_Number_Of_Internal_Iterations':'300',
        'PHFlash_Maximum_Number_Of_External_Iterations':'300',
        'PHFlash_Maximum_Number_Of_Internal_Iterations':'300',
        'NL_FastMode':'False','IO_FastMode':'False','PVFlash_TryIdealCalcOnFailure':'False',
        'FailSafeCalculationMode':'3'}  # UniversalFlash: 3=None; 1 silently uses ideal VLE.
    for key,value in policy.items():pp.FlashSettings[getattr(FlashSetting,key)]=value
    return policy


def configure_candidate(flow, pp, card, Array, Double):
    from System import String
    from System.Collections.Generic import Dictionary
    from DWSIM.Thermodynamics.PropertyPackages import PropertyPackage, State
    from DWSIM.Thermodynamics.PropertyPackages.Auxiliary import NRTL_IPData
    from System import Func
    tighten_candidate_flash(pp)
    native_order = [str(k) for k in flow.SelectedCompounds.Keys]
    mapping = [card['native_names'].index(n) for n in native_order]
    for name,index in zip(native_order,mapping):
        if str(flow.SelectedCompounds[name].CAS_Number)!=card['component_order'][index]:
            raise ValueError('MODEL_COMPONENT_MISMATCH: native compound CAS differs from the source card')
    overrides=card.get('pure_property_overrides')
    if overrides:
        # Data-only source correlations: no XML/flowsheet objects are loaded.
        allowed={'VaporPressureEquation','IdealgasCpEquation','Normal_Boiling_Point',
                 *('Vapor_Pressure_Constant_'+c for c in 'ABCDE'),
                 'Vapor_Pressure_TMAX','Vapor_Pressure_TMIN',
                 *('Ideal_Gas_Heat_Capacity_Const_'+c for c in 'ABCDE')}
        if set(overrides)!=set(card['component_order']):raise ValueError('Incomplete source pure-property coverage')
        for name,index in zip(native_order,mapping):
            data=overrides[card['component_order'][index]]
            if set(data)!=allowed:raise ValueError('Unregistered pure-property override')
            native=flow.SelectedCompounds[name]
            for key,value in data.items():
                if key in ('VaporPressureEquation','IdealgasCpEquation'):
                    if value not in ('101','16'):raise ValueError('Unsupported source correlation')
                elif not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Nonfinite source coefficient')
                setattr(native,key,value)
    if card.get('vapor_model')=='native_associating_EOS':
        parameters={};binary=[]
        for cas in card['component_order']:
            if not pp.CompoundParameters.ContainsKey(cas):raise ValueError('PROPERTY_UNQUALIFIED: missing native PC-SAFT pure parameters for '+cas)
            value=pp.CompoundParameters[cas]
            parameters[cas]={field.Name:str(field.GetValue(value)) for field in value.GetType().GetFields()}
        for i,ci in enumerate(card['component_order']):
            for cj in card['component_order'][i+1:]:
                value=None
                if pp.InteractionParameters.ContainsKey(ci) and pp.InteractionParameters[ci].ContainsKey(cj):value=pp.InteractionParameters[ci][cj]
                elif pp.InteractionParameters.ContainsKey(cj) and pp.InteractionParameters[cj].ContainsKey(ci):value=pp.InteractionParameters[cj][ci]
                binary.append({'pair':[ci,cj],'parameters':{field.Name:str(field.GetValue(value)) for field in value.GetType().GetFields()} if value is not None else None,
                    'origin':'native_library_entry' if value is not None else 'explicit_missing_native_zero_hypothesis_diagnostic_only'})
        return {'native_order':native_order,'mapping':mapping,'calls':{},'native_parameters':parameters,'binary_parameters':binary}
    if 'UNIFAC' in card.get('model',''):
        options=card.get('native_options')
        if options:
            if set(options)!={'vapor_fugacity','enthalpy','poynting'} or options['vapor_fugacity']!='Ideal' or options['enthalpy'] not in ('Ideal','Excess') or options['poynting'] is not True:
                raise ValueError('Unsupported source property options')
            pp.VaporPhaseFugacityCalculationMode=PropertyPackage.VaporPhaseFugacityCalcMode.Ideal
            pp.EnthalpyEntropyCpCvCalculationMode=getattr(PropertyPackage.EnthalpyEntropyCpCvCalcMode,options['enthalpy'])
            pp.LiquidFugacity_UsePoyntingCorrectionFactor=True
        groups={}
        for name in native_order:
            native=getattr(flow.SelectedCompounds[name],card.get('group_collection','UNIFACGroups'))
            groups[name]={str(k):int(native[k]) for k in native.Keys}
        if any(not row for row in groups.values()):raise ValueError('PROPERTY_UNQUALIFIED: missing native UNIFAC groups')
        return {'native_order':native_order,'mapping':mapping,'calls':{},'groups':groups}
    # Clear bundled/default values, then require every unordered pair explicitly.
    table = pp.m_uni.InteractionParameters
    table.Clear()
    for i,name in enumerate(native_order):
        table.Add(name,Dictionary[String,NRTL_IPData]())
        for j in range(i+1,len(native_order)):
            ci,cj = mapping[i],mapping[j]
            entry=NRTL_IPData()
            entry.A12=1.98721*card['B_K'][ci][cj]
            entry.A21=1.98721*card['B_K'][cj][ci]
            entry.B12=1.98721*card['A'][ci][cj]
            entry.B21=1.98721*card['A'][cj][ci]
            entry.alpha12=card['alpha'][ci][cj]
            table[name].Add(native_order[j],entry)
    acid=native_order.index('Acetic acid') if card['vapor_model']=='ideal_physical_gas_acid_dimerization' else None
    pp.ActivityCoefficientModels_IgnoreMissingInteractionParameters=False
    # Both physical-vapor and caloric departures are explicitly ideal here.
    pp.VaporPhaseFugacityCalculationMode=PropertyPackage.VaporPhaseFugacityCalcMode.Ideal
    pp.EnthalpyEntropyCpCvCalculationMode=PropertyPackage.EnthalpyEntropyCpCvCalcMode.Ideal
    pp.LiquidFugacity_UsePoyntingCorrectionFactor=False
    calls={'liquid':0,'vapor':0,'outside_association_T_range':0}
    if acid is None:
        # Native NRTL + ideal physical vapor already represents this model.
        # Do not route native column tasks through unnecessary Python delegates.
        return {'native_order':native_order,'mapping':mapping,'calls':calls}

    def fugacity(x,T,P,state,package):
        key='liquid' if state==State.Liquid else 'vapor'
        calls[key]+=1
        if acid is not None and not 318.15<=T<=393.15:calls['outside_association_T_range']+=1
        if state==State.Liquid:
            # DW_CalcFugCoeff is the native routine, distinct from the K override.
            result=package.DW_CalcFugCoeff(x,T,P,state)
            if acid is not None:
                psat=package.AUX_PVAPi(acid,T)
                result[acid]*=acid_dimer_state(T,psat,1.)['acid_fugacity_coefficient']
            return result
        if state!=State.Vapor:
            raise ValueError('Unsupported phase in acid diagnostic')
        if acid is None:return Array[Double]([1.]*len(x))
        d=acid_dimer_state(T,P,float(x[acid]))
        values=[d['other_fugacity_coefficient']]*len(x)
        values[acid]=d['acid_fugacity_coefficient']
        return Array[Double](values)

    delegate=Func[Array[Double],Double,Double,State,PropertyPackage,Array[Double]](fugacity)
    pp.KvalFugacityCoefficientOverride=delegate
    pp.OverrideKvalFugCoeff=True
    # This diagnostic does not override caloric properties: TP/PVF only, no
    # accepted energy balance, column, equipment duty or recycle design.
    return {'native_order':native_order,'mapping':mapping,'calls':calls,'delegate':delegate}


def probe_mixture(manager,payload,Array,Double,ObjectType,StreamSpec):
    request=MixtureProbeRequest.model_validate(payload)
    card,digest=mixture_card(request.property_card_id)
    concrete=lambda o:getattr(o,'__implementation__',o)
    flow=concrete(manager.CreateFlowsheet())
    for name in card['native_names']:
        if not manager.AvailableCompounds.ContainsKey(name):raise ValueError('Unknown native compound: '+name)
        flow.AddCompound(name)
    pp=concrete(flow.CreateAndAddPropertyPackage(card.get('model','NRTL')))
    config=configure_candidate(flow,pp,card,Array,Double)
    flash_policy=tighten_candidate_flash(pp)
    if request.phase_policy=='liquid_liquid':
        # In installed 9.0.5 FlashAlgorithm is a legacy property ignored by
        # FlashBase/GetFlash. The active selector is FlashCalculationApproach.
        # Gibbs minimization retains vapor candidates; this does not force LLE.
        from DWSIM.Thermodynamics.PropertyPackages import PropertyPackage
        pp.FlashCalculationApproach=PropertyPackage.FlashCalculationApproachType.GibbsMinimization
    s=concrete(flow.AddObject(ObjectType.MaterialStream,0,0,'Mixture qualification probe'))
    s.PropertyPackage=pp
    rows=[]
    for point in request.points:
        row={'point_id':point.point_id,'request':point.model_dump(),'converged':False}
        try:
            s.ClearAllProps()
            s.SetMolarFlow(1.)
            s.SetOverallComposition(Array[Double]([point.mole_fractions[i] for i in config['mapping']]))
            s.SetTemperature(point.temperature_K);s.SetPressure(point.pressure_Pa)
            if point.specification=='phase_properties':
                if card['model_id'] not in {'mch_toluene_phenol_unifac_v1','mch_toluene_phenol_hydraulic_sensitivity_v2','mch_toluene_sulfolane_vle_brouwer2021','mch_toluene_sulfolane_lle_brouwer2021'}:
                    raise ValueError('Phase transport diagnostic not registered for this model')
                from DWSIM.Thermodynamics.PropertyPackages import Phase,State
                xx=Array[Double]([point.mole_fractions[i] for i in config['mapping']])
                liq=point.phase=='liquid';pe=Phase.Liquid1 if liq else Phase.Vapor;pi=3 if liq else 2
                state=State.Liquid if liq else State.Vapor
                s.SetPhaseComposition(xx,pe);s.Phases[pi].Properties.molarfraction=1.
                pp.CurrentMaterialStream=s;pp.DW_CalcPhaseProps(pe)
                pr=s.Phases[pi].Properties
                h=lambda t:float(pp.DW_CalcEnthalpy(xx,t,point.pressure_Pa,state))
                step=.01
                cp=(h(point.temperature_K+step)-h(point.temperature_K-step))/(2*step)
                rho=float(pr.density);mu=float(pr.viscosity)
                values=[rho,mu,cp,h(point.temperature_K)]
                if not all(math.isfinite(v) for v in values) or min(rho,mu,cp)<=0:
                    raise ValueError('Nonpositive/nonfinite native fixed-composition phase property')
                row.update(executed=True,converged=None,equilibrium_applicable=False,
                    phase_properties=dict(phase=point.phase,density_kg_m3=rho,viscosity_Pa_s=mu,
                        molecular_weight_kg_kmol=float(pr.molecularWeight),specific_enthalpy_kJ_kg=values[-1],
                        heat_capacity_fixed_composition_kJ_kg_K=cp,
                        native_phase_property_Cp_kJ_kg_K=float(pr.heatCapacityCp)),
                    caloric_scope='Fixed-composition native enthalpy derivative; numerical check only, not experimental caloric qualification')
                if liq:row['phase_properties']['surface_tension_N_m']=float(pp.AUX_SURFTM(3,point.temperature_K))
                rows.append(row);continue
            if point.specification=='pure_properties':
                # Native correlation evaluation, no equilibrium result invented.
                pp.CurrentMaterialStream=s
                pressures=[0.]*len(config['mapping'])
                for j,i in enumerate(config['mapping']):pressures[i]=float(pp.AUX_PVAPi(j,point.temperature_K))
                if not all(math.isfinite(v) and v>0 for v in pressures):raise ValueError('Invalid native pure vapor pressure')
                from DWSIM.Thermodynamics.PropertyPackages import State
                xx=Array[Double]([point.mole_fractions[i] for i in config['mapping']])
                phin=pp.DW_CalcFugCoeff(xx,point.temperature_K,point.pressure_Pa,State.Liquid)
                liquid_phi=[0.]*len(config['mapping'])
                for j,i in enumerate(config['mapping']):liquid_phi[i]=float(phin[j])
                row.update(executed=True,converged=None,equilibrium_applicable=False,
                    reference_temperature_K=point.temperature_K,
                    native_liquid_fugacity_coefficients_at_reference_state=liquid_phi,
                    native_vapor_pressures_Pa_at_reference_T=pressures)
                if card['model_id'] in ('mch_toluene_sulfolane_vle_brouwer2021','sulfolane_recovery_ternary_vle_seed_v1'):
                    from DWSIM.Thermodynamics.PropertyPackages import Phase
                    s.SetPhaseComposition(xx,Phase.Liquid1);s.Phases[3].Properties.molarfraction=1.
                    pp.DW_CalcPhaseProps(Phase.Liquid1)
                    h=float(s.Phases[3].Properties.enthalpy);rho=float(s.Phases[3].Properties.density)
                    if not math.isfinite(h) or not math.isfinite(rho) or rho<=0:raise ValueError('Invalid native liquid-reference state')
                    row.update(native_liquid_specific_enthalpy_kJ_kg=h,native_liquid_density_kg_m3=rho,
                               native_liquid_molecular_weight_kg_kmol=float(s.Phases[3].Properties.molecularWeight),
                               caloric_scope='Native liquid-reference evaluation only; phase stability checked separately')
                rows.append(row)
                continue
            if point.specification=='bubble':
                s.SpecType=StreamSpec.Pressure_and_VaporFraction
                s.Phases[2].Properties.molarfraction=0.
            else:s.SpecType=StreamSpec.Temperature_and_Pressure
            if request.phase_policy=='direct_lle':
                from DWSIM.Thermodynamics.PropertyPackages.Auxiliary.FlashAlgorithms import SimpleLLE
                from DWSIM.Thermodynamics.PropertyPackages import Phase
                pp.CurrentMaterialStream=s
                algorithm=SimpleLLE();algorithm.FlashSettings=pp.FlashSettings
                if request.lle_initialization=='independent_gibbs':
                    from sepmind.engineering.thermo.lle import NRTLModel,flash_lle
                    seed=flash_lle(NRTLModel(card),point.mole_fractions,point.temperature_K,point.pressure_Pa,require_qualified=False)
                    if seed['phase_count']!=2:raise ValueError('Independent seed has no stable nontrivial liquid split')
                    a,b=seed['phases']
                    algorithm.UseInitialEstimatesForPhase1=True;algorithm.UseInitialEstimatesForPhase2=True
                    algorithm.InitialEstimatesForPhase1=Array[Double]([a['composition'][i] for i in config['mapping']])
                    algorithm.InitialEstimatesForPhase2=Array[Double]([b['composition'][i] for i in config['mapping']])
                    algorithm.InitialEstimateForPhase1Amount=float(a['fraction'])
                    row['numerical_initialization']='Independent source-NRTL Gibbs phase estimates; native fugacity equations and lever rule still checked'
                native_z=Array[Double]([point.mole_fractions[i] for i in config['mapping']])
                result=algorithm.Flash_PT(native_z,point.pressure_Pa,point.temperature_K,pp,False,None)
                if abs(float(result[1]))>1e-12:raise ValueError('Unexpected vapor from liquid-only routine')
                for phase_index,phase_enum,beta_index,composition_index in [(3,Phase.Liquid1,0,2),(4,Phase.Liquid2,5,6)]:
                    beta=float(result[beta_index])
                    s.Phases[phase_index].Properties.molarfraction=beta
                    if beta>1e-12:
                        s.SetPhaseComposition(Array[Double]([float(v) for v in result[composition_index]]),phase_enum)
                        pp.DW_CalcPhaseProps(phase_enum)
                row['liquid_only_scope']='Native SimpleLLE.Flash_PT; vapor feasibility and independent phase stability require separate review'
            else:s.Calculate()
            T=float(s.GetTemperature())
            def fractions(phase):
                values=[0.]*len(card['component_order'])
                for j,name in enumerate(config['native_order']):
                    value=s.Phases[phase].Compounds[name].MoleFraction
                    values[config['mapping'][j]]=float(value or 0.)
                return values
            phases=[]
            for phase in (2,3,4,5,6,7):
                properties=s.Phases[phase].Properties
                beta=float(properties.molarfraction or 0.)
                if beta>1e-12:
                    phases.append({'native_phase_index':phase,'molar_fraction':beta,
                        'composition':fractions(phase),
                        'density_kg_m3':float(properties.density) if properties.density is not None else None,
                        'specific_enthalpy_kJ_kg_unqualified':float(properties.enthalpy) if properties.enthalpy is not None else None})
            closure=max(abs(sum(row['molar_fraction']*row['composition'][i] for row in phases)-point.mole_fractions[i]) for i in range(len(point.mole_fractions)))
            native_x=Array[Double]([point.mole_fractions[i] for i in config['mapping']])
            from DWSIM.Thermodynamics.PropertyPackages import State
            pp.CurrentMaterialStream=s
            native_phi=pp.DW_CalcFugCoeff(native_x,point.temperature_K,point.pressure_Pa,State.Liquid)
            pressures=[0.]*len(config['mapping']);gammas=[0.]*len(config['mapping'])
            for j,i in enumerate(config['mapping']):
                pressures[i]=float(pp.AUX_PVAPi(j,point.temperature_K))
                gammas[i]=float(native_phi[j])*point.pressure_Pa/pressures[i]
            fugacities=[]
            equilibrium_phases=phases.copy()
            if point.specification=='bubble' and not any(r['native_phase_index']==2 for r in phases):
                equilibrium_phases.append({'native_phase_index':2,'composition':fractions(2)})
            for phase in equilibrium_phases:
                if sum(phase['composition'])<.999:continue
                state=State.Vapor if phase['native_phase_index']==2 else State.Liquid
                x=Array[Double]([phase['composition'][i] for i in config['mapping']])
                phi=pp.KvalFugacityCoefficientOverride.Invoke(x,T,point.pressure_Pa,state,pp) if pp.OverrideKvalFugCoeff else pp.DW_CalcFugCoeff(x,T,point.pressure_Pa,state)
                values=[0.]*len(config['mapping'])
                for j,i in enumerate(config['mapping']):values[i]=float(x[j]*phi[j])
                fugacities.append(values)
            active=[i for i,x in enumerate(point.mole_fractions) if x>1e-12]
            eq_residual=max((abs(math.log(f[i]/fugacities[0][i])) for f in fugacities[1:] for i in active if min(f[i],fugacities[0][i])>0),default=0.)
            numerical_pass=closure<=1e-7 and eq_residual<=1e-3 and all(abs(sum(row['composition'])-1)<1e-7 for row in phases)
            if not numerical_pass:raise ValueError(f'Native flash failed independent numerical check: component={closure}, log_fugacity={eq_residual}')
            row.update(converged=True,temperature_K=T,
                vapor_mole_fractions=fractions(2),liquid_mole_fractions=fractions(3),
                within_association_T_range=(318.15<=T<=393.15) if card['vapor_model']=='ideal_physical_gas_acid_dimerization' else None,
                reference_temperature_K=point.temperature_K,
                phases=phases,component_closure_relative=closure,
                maximum_log_fugacity_residual=eq_residual,numerical_validation_passed=numerical_pass,
                native_UNIFAC_groups=config.get('groups'),
                native_vapor_pressures_Pa_at_reference_T=pressures,
                native_activity_coefficients_at_reference_T=gammas if card['vapor_model']!='native_associating_EOS' else None)
            if point.specification=='TP' and request.phase_policy=='default':
                row['native_overall_properties']=dict(
                    molecular_weight_kg_kmol=float(s.GetMassFlow())*1000/float(s.GetMolarFlow()),
                    specific_enthalpy_kJ_kg=float(s.GetMassEnthalpy()),
                    vapor_mole_fraction=sum(phase['molar_fraction'] for phase in phases if phase['native_phase_index']==2),
                    density_kg_m3=phases[0]['density_kg_m3'] if len(phases)==1 else None)
            if request.phase_policy=='direct_lle':
                margins=[-math.log(sum(v)) for v in fugacities]
                row.update(ideal_vapor_tpd_margins=margins,ideal_vapor_screen_passed=min(margins)>=-1e-7)
            if not all(math.isfinite(v) for v in [T]+row['vapor_mole_fractions']+row['liquid_mole_fractions']):
                raise ValueError('Nonfinite native mixture flash')
        except Exception as exc:
            row.update(converged=False,error=str(exc))
        rows.append(row)
    return {'property_card_id':request.property_card_id,'parameter_sha256':digest,
        'component_order':card['component_order'],'points':rows,'override_calls':config['calls'],
        'native_flash_policy':flash_policy,
        'requested_phase_policy':request.phase_policy,
        'native_flash_algorithm_type':'DWSIM.SimpleLLE.Flash_PT (direct liquid-only call)' if request.phase_policy=='direct_lle' else str(pp.FlashBase.GetType().FullName),
        'native_parameters':config.get('native_parameters'),'native_binary_parameters':config.get('binary_parameters'),
        'native_UNIFAC_groups':config.get('groups'),
        'native_component_constants':{name:{'CAS':str(flow.SelectedCompounds[name].CAS_Number),
            'molecular_weight_g_mol':float(flow.SelectedCompounds[name].Molar_Weight)} for name in config['native_order']},
        'qualification_only':True,'design_admitted':False,
        'limitations':card['limitations']+['Caloric properties not qualified; this interface cannot run columns or process duties.']}
