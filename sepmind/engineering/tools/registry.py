"""Typed, gate-checked tools with explicit result/provenance envelopes."""

from ..schemas import Contract, DesignBasis, EvidenceRecord, ParameterSet, Reason, ToolResult
from ..workflow.graph import require_gate
from ..thermo import package_for, selected_model
from ..design.synthesis import feasibility, tradeoffs
from ..design.binary import material_balance, minimum_reflux, stages
from ..validation import balance_checks, vle_checks, stage_checks


class BasisInput(Contract):
    basis: DesignBasis


class EmptyInput(Contract):
    pass


def missing_specifications(basis, thermal_only=False):
    missing = []
    if len(basis.components) != 2:
        missing.append("components: two canonical identities")
    if basis.feed.pressure_kPa is None:
        missing.append("feed.pressure_kPa")
    if thermal_only:
        return missing
    if basis.feed.flow is None or basis.feed.flow_unit is None:
        missing.append("feed.flow and feed.flow_unit")
    if len(basis.feed.composition) != 2 or basis.feed.composition_basis != "mole_fraction":
        missing.append("feed.composition: two mole fractions (mass-fraction conversion not implemented)")
    if basis.feed.quality_q is None:
        missing.append("feed.quality_q")
    if basis.target.distillate_mole_fraction is None:
        missing.append("target.distillate_mole_fraction")
    if basis.target.bottoms_mole_fraction is None and basis.target.key_component_recovery is None:
        missing.append("target.bottoms_mole_fraction OR target.key_component_recovery")
    if basis.column.reflux_ratio is None and basis.design_mode != 'autonomous':
        missing.append("column.reflux_ratio")
    return missing


class EngineeringToolRegistry:
    # Canonical v2 numbering follows CODEX_PHA_MIGRATION_PROMPT.md.
    TOOLS = {
        "parse_design_basis": ("G0", BasisInput),
        "check_design_specifications": ("G0", BasisInput),
        "select_thermodynamic_model": ("G2", BasisInput),
        "resolve_property_parameters": ("G2", BasisInput),
        "calculate_binary_vle": ("G1", BasisInput),
        "assess_separation_feasibility": ("G1", EmptyInput),
        "calculate_material_balance": ("G3", BasisInput),
        "estimate_minimum_reflux": ("G4", BasisInput),
        "explore_reflux_candidates": ("G4", BasisInput),
        "select_process_design": ("G4", EmptyInput),
        "calculate_mccabe_thiele_stages": ("G4", BasisInput),
        "verify_and_refine_column": ("G4", BasisInput),
        "calculate_energy_balance": ("G5", EmptyInput),
        "estimate_column_equipment": ("G6", BasisInput),
        "estimate_auxiliary_equipment": ("G7", BasisInput),
        "check_design_consistency": ("G8", EmptyInput),
        "render_preliminary_design_report": ("G9", EmptyInput),
    }

    def capabilities(self):
        return [{"name": name, "gate": gate, "input_schema": schema.model_json_schema(), "implemented": True}
                for name,(gate,schema) in self.TOOLS.items()]

    def execute(self, name, state, gate, arguments):
        if name not in self.TOOLS:
            raise ValueError("UNREGISTERED_TOOL: " + name)
        approved_gate, schema = self.TOOLS[name]
        if gate != approved_gate:
            raise ValueError("GATE_PRECONDITION: tool belongs to " + approved_gate)
        require_gate(state, gate)
        typed = schema.model_validate(arguments)
        if hasattr(typed, "basis") and typed.basis != state.basis:
            raise ValueError("SOURCE_CONFLICT: tool basis differs from frozen run basis")
        for required in {
            "calculate_binary_vle": ["resolve_property_parameters"],
            "assess_separation_feasibility": ["calculate_binary_vle"],
            "estimate_minimum_reflux": ["calculate_material_balance", "calculate_binary_vle"],
            "calculate_mccabe_thiele_stages": ["calculate_material_balance", "estimate_minimum_reflux"],
            "explore_reflux_candidates": ["calculate_material_balance", "estimate_minimum_reflux"],
            "select_process_design": ["explore_reflux_candidates"],
            "verify_and_refine_column": ["calculate_mccabe_thiele_stages", "calculate_material_balance"],
            "calculate_energy_balance": ["verify_and_refine_column"],
            "estimate_column_equipment": ["verify_and_refine_column","calculate_energy_balance"],
            "estimate_auxiliary_equipment": ["verify_and_refine_column","calculate_energy_balance","estimate_column_equipment"],
        }.get(name, []):
            artifact = state.artifacts.get(required)
            if artifact is None or artifact.status != "success" or artifact.validation.get("passed") is not True:
                raise ValueError("GATE_PRECONDITION: validated artifact missing: " + required)
        result = ToolResult(status="success", tool_name=name, run_id=state.run_id, source_or_run=state.run_id,
                            evidence=[EvidenceRecord(evidence_id=state.basis.design_id,
                                      type="input_specification", source="frozen user design basis")])
        state.tool_calls += 1
        try:
            getattr(self, name)(state, result)
        except Exception as exc:
            text = str(exc)
            code = text.split(":",1)[0] if ":" in text else "SOLVER_OR_VALIDATION_FAILED"
            result.status = ("needs_input" if code in ("INPUT_UNDERDETERMINED", "DATA_PARAMETER_MISSING", "REQUIRES_REVIEW",'MODEL_OUT_OF_RANGE')
                             else "unsupported" if code in ("UNSUPPORTED",'FEAS_AZEOTROPE') else "failed")
            result.error_type = code
            result.errors = [Reason(code=code, explanation=text)]
            result.validation = {"passed": False}
        return result

    @staticmethod
    def parse_design_basis(state, out):
        out.data = {"design_basis": state.basis.model_dump(), "missing": missing_specifications(state.basis,
                    state.intent == "THERMODYNAMIC_CALCULATION")}
        out.validation = {"passed": True, "meaning": "typed extraction only, not complete design approval"}

    @staticmethod
    def check_design_specifications(state, out):
        missing = missing_specifications(state.basis, state.intent == "THERMODYNAMIC_CALCULATION")
        if missing:
            from ..workflow.intake import describe_missing
            out.status = "needs_input"
            out.data = {"missing": missing,'missing_labels':describe_missing(missing)}
            out.error_type = "INPUT_UNDERDETERMINED"
            out.validation = {"passed": False}
            return
        if state.intent != "THERMODYNAMIC_CALCULATION":
            if state.basis.feed.quality_q != 1:
                raise ValueError("UNSUPPORTED: only explicit saturated-liquid feed q=1 is implemented")
            # Also detects over-specified recovery and wrong component ordering.
            material_balance(state.basis)
        out.data = {"missing": [], "independent_specifications_sufficient": True}
        out.validation = {"passed": True}

    @staticmethod
    def select_thermodynamic_model(state, out):
        from ..knowledge import assess_models
        assessment = assess_models(state.basis)
        out.data['expert_model_assessment'] = assessment
        model = selected_model(state.basis)
        if model == 'NRTL':
            package = package_for(state.basis)
            out.data.update({'selected_model':'NRTL','selection_basis':'Eligible polar alcohol/water pair, sourced NRTL interaction parameters and the recorded measurement-screening limits',
                        'alternatives_rejected':[{'model':'Raoult','reason':'Liquid nonideality requires an activity-coefficient treatment'},
                                                 {'model':'PR','reason':'No qualified polar-mixture parameterization for this task'}],
                        'proposed_method_assumptions':['ideal_vapor_low_pressure','neglect_Poynting_correction'],
                        'conditional_only':True})
            out.evidence += package.parameters.sources
            out.assumptions = out.data['proposed_method_assumptions']
            out.validation = {'passed':True,'industrial_design_validated':False}
            return
        if model != 'Raoult':
            raise ValueError('DATA_PARAMETER_MISSING: model not qualified')
        research_pair = {c.cas or c.canonical_id for c in state.basis.components} == {'71-43-2','108-88-3'}
        out.data.update({"selected_model": "Raoult", "selection_basis": "near-ideal aromatic pair, measured P-x-T screening and bounded research extrapolation" if research_pair else "explicit user model and ideality assumption"})
        out.assumptions = ["ideal_liquid_and_vapor"]
        out.validation = {"passed": research_pair or "ideal_liquid_and_vapor" in state.basis.assumptions}
        if research_pair:
            package = package_for(state.basis)
            out.evidence += package.parameters.sources
            out.warnings.append(package.caveat)
        if not out.validation["passed"]:
            raise ValueError("REQUIRES_REVIEW: accept ideal_liquid_and_vapor explicitly")

    @staticmethod
    def resolve_property_parameters(state, out):
        package = package_for(state.basis)
        out.data = package.parameters.model_dump()
        out.evidence += package.parameters.sources
        out.units = {"temperature": "K", "vapor_pressure": "Pa"}
        out.validation = {"passed": True, "binary_nonideality_validated": False,
                          "scope": "qualified pure correlations; ideal-mixture applicability explicitly assumed"}
        if hasattr(package,'reference_check'):
            checked = package.reference_check()
            out.data['experimental_reference_check'] = checked
            out.validation = {'passed':checked['passed'],'binary_nonideality_screened':True,
                              'scope':checked['scope'],'fit_temperature_limits_published':False}
            out.warnings.append('Source fit temperature interval is not published in the compilation; project atmospheric guard and measured-data screening are enforced. Not industrial certification.')
            if not checked['passed']:
                raise ValueError('PROPERTY_REFERENCE_MISMATCH: NRTL fails independent experimental screening')

    @staticmethod
    def calculate_binary_vle(state, out):
        package = package_for(state.basis)
        out.data = package.grid(state.basis.feed.pressure_kPa*1000)
        out.validation = vle_checks(out.data,package=package)
        if state.basis.feed.temperature_K is not None and state.basis.feed.composition and state.basis.feed.quality_q == 1:
            expected = package.point(state.basis.feed.composition[0],state.basis.feed.pressure_kPa*1000)["temperature_K"]
            if abs(expected-state.basis.feed.temperature_K) > 0.1:
                raise ValueError("SOURCE_CONFLICT: supplied feed temperature disagrees with saturated-liquid q=1")
        out.convergence = {"all_points_solved": True, "maximum_bubble_residual":
                           max(p["bubble_residual_relative"] for p in out.data["points"])}
        out.units = {"temperature_K": "K", "pressure_Pa": "Pa", "x": "mol/mol", "y": "mol/mol"}
        out.evidence += package.parameters.sources
        out.assumptions = ['ideal_vapor_low_pressure'] if package.MODEL=='NRTL' else ['ideal_liquid_and_vapor']

    @staticmethod
    def assess_separation_feasibility(state, out):
        vle = state.artifacts["calculate_binary_vle"].data
        if state.intent == 'THERMODYNAMIC_CALCULATION':
            out.data = {'route':None,'conditional_feasible':False,'scope':'VLE only; product feasibility requires design specifications'}
            out.validation = {'passed':True,'product_feasibility_assessed':False}
            return
        out.data = feasibility(package_for(state.basis),state.basis,vle)
        possible = out.data['conditional_feasible']
        out.evidence.append(EvidenceRecord(evidence_id=state.artifacts["calculate_binary_vle"].artifact_id,
                                          type="solver_run", source=state.run_id))
        out.validation = {"passed": possible, "scope": "finite-grid phase screen under the accepted model"}
        if not possible:
            raise ValueError("FEAS_AZEOTROPE: boundary signal or wrong nominated light component; route unresolved")

    @staticmethod
    def calculate_material_balance(state, out):
        out.data = material_balance(state.basis)
        out.units = {"F_kmol_h": "kmol/h", "D_kmol_h": "kmol/h", "B_kmol_h": "kmol/h",
                     "key_component_recovery": "mol/mol"}
        out.validation = balance_checks(out.data)

    @staticmethod
    def estimate_minimum_reflux(state, out):
        out.data = minimum_reflux(package_for(state.basis),state.basis,
                                  state.artifacts["calculate_material_balance"].data)
        out.units = {"minimum_reflux_ratio": "mol/mol"}
        out.validation = {"passed": bool(out.data["minimum_reflux_ratio"] >= 0),
                          "global_optimality_proven": False}
        out.convergence = {"bounded_numerical_search_completed": True}

    @staticmethod
    def explore_reflux_candidates(state, out):
        if state.basis.design_mode != 'autonomous' or state.basis.column.reflux_ratio is not None:
            out.data = {'candidates':[],'user_reflux_preserved':state.basis.column.reflux_ratio}
            out.validation = {'passed':True}
            return
        effective = state.basis.model_copy(deep=True)
        effective.assumptions = list(set(effective.assumptions+['constant_molar_overflow']))
        out.data = tradeoffs(package_for(state.basis),effective,
                            state.artifacts['calculate_material_balance'].data,
                            state.artifacts['estimate_minimum_reflux'].data)
        out.assumptions = ['constant_molar_overflow','equilibrium_stages','no_heat_loss_or_pressure_drop_in_stage_screen']
        out.warnings = ['These are agent-proposed method approximations; duties and actual tray efficiency remain unverified.']
        out.validation = {'passed':True,'economic_optimum_claimed':False}

    @staticmethod
    def select_process_design(state, out):
        choices = state.artifacts['explore_reflux_candidates'].data
        if choices.get('user_reflux_preserved') is not None:
            out.data = {'selected_reflux_ratio':choices['user_reflux_preserved'],'selection_basis':'preserve explicit user operating reflux'}
        else:
            candidate = state.design_preferences.get('candidate_id',choices['default_candidate_id'])
            row = next((r for r in choices['candidates'] if r['candidate_id']==candidate and r['status']=='feasible'),None)
            if row is None:
                raise ValueError('INVALID_DESIGN_SELECTION: choose only a feasible computed candidate')
            out.data = {'selected_reflux_ratio':row['reflux_ratio'],'candidate_id':candidate,
                        'selection_basis':state.design_preferences.get('rationale',choices['policy']),
                        'selected_by':'deepseek' if state.provider=='deepseek' else 'deterministic_screening_policy',
                        'route':'ordinary_binary_distillation','condenser':'total','reboiler':'partial',
                        'global_economic_optimality_proven':False}
        out.data.update(route='ordinary_binary_distillation',condenser='total',reboiler='partial')
        balance = state.artifacts['calculate_material_balance'].data
        r,d,f = out.data['selected_reflux_ratio'],balance['D_kmol_h'],balance['F_kmol_h']
        out.data['internal_molar_flows_kmol_h'] = {'rectifying_liquid':r*d,'rectifying_vapor':(r+1)*d,
                                                  'stripping_liquid':r*d+f,'stripping_vapor':(r+1)*d}
        out.data['flowsheet'] = {'level':'preliminary_process_scheme_not_equipment_rating',
                                'units':['binary_column','total_condenser','partial_reboiler'],
                                'streams':balance['streams'],
                                'connections':[['feed','binary_column'],['binary_column','total_condenser'],
                                               ['total_condenser','distillate'],['total_condenser','binary_column'],
                                               ['binary_column','partial_reboiler'],['partial_reboiler','binary_column'],
                                               ['partial_reboiler','bottoms']]}
        out.assumptions = ['constant_molar_overflow','saturated_liquid_feed','total_condenser','partial_reboiler']
        out.validation = {'passed':True}

    @staticmethod
    def calculate_mccabe_thiele_stages(state, out):
        balance = state.artifacts["calculate_material_balance"].data
        effective = state.basis.model_copy(deep=True)
        if effective.design_mode == 'autonomous':
            effective.assumptions = list(set(effective.assumptions+['constant_molar_overflow']))
            effective.column.reflux_ratio = state.artifacts['select_process_design'].data['selected_reflux_ratio']
        out.data = stages(package_for(state.basis),effective,balance,
                          state.artifacts["estimate_minimum_reflux"].data)
        out.validation = stage_checks(out.data,balance)
        out.units = {"reflux_ratio": "mol/mol", "theoretical_stages_fractional": "equilibrium stage",
                     "feed_stage_from_top": "equilibrium stage from top"}
        out.assumptions = ['constant_molar_overflow','saturated_liquid_feed',
                           'ideal_vapor_low_pressure' if selected_model(state.basis)=='NRTL' else 'ideal_liquid_and_vapor']
        out.convergence = {"target_reached": out.validation["bottoms_target_reached"]}

    @staticmethod
    def verify_and_refine_column(state, out):
        from pathlib import Path
        from ..design.rigorous import refine_column
        out.data = refine_column(state.basis,
            state.artifacts['calculate_material_balance'].data,
            state.artifacts['calculate_mccabe_thiele_stages'].data,
            Path(__file__).resolve().parents[3]/'output/engineering/native_columns'/state.run_id)
        out.validation = {'passed':out.data['passed'], 'strict_product_targets':out.data['passed'],
                          'pressure_drop_included':False,'industrial_validation':False}
        out.convergence = {'candidate_count':len(out.data['attempts']), 'bounded':True}
        out.assumptions = ['equilibrium_stages','uniform_pressure','no_heat_loss',
                           'total_condenser','partial_reboiler','saturated_liquid_feed']
        out.warnings = ['Rigorous equilibrium-stage performance under the recorded property method; tray performance and pressure-drop feedback require separate checks.']
        for row in out.data['attempts']:
            if row.get('evidence_id'):
                out.evidence.append(EvidenceRecord(evidence_id=row['evidence_id'],type='solver_run',source=row['evidence_file']))
        if out.data.get('native_equilibrium_screen',{} ) and out.data['native_equilibrium_screen'].get('source_evidence_id'):
            screen=out.data['native_equilibrium_screen']
            out.evidence.append(EvidenceRecord(evidence_id=screen['source_evidence_id'],type='solver_run',source=screen['evidence_file']))
        if not out.data['passed']:
            out.error_type = 'REDESIGN_EXHAUSTED'
            out.errors = [Reason(code=out.error_type,explanation='No strictly compliant native column within the bounded search; original user targets and explicit operating constraints preserved.')]

    @staticmethod
    def calculate_energy_balance(state, out):
        from ..design.rigorous import energy_balance
        native = state.artifacts['verify_and_refine_column'].data['selected_simulation']
        out.data = energy_balance(native)
        out.validation = {'passed':out.data['passed'], 'independent_enthalpy_closure':out.data['passed']}
        out.units = {'condenser_duty_kW':'kW','reboiler_duty_kW':'kW','residual_kW':'kW'}
        out.evidence.append(EvidenceRecord(evidence_id=native['evidence_id'],type='solver_run',source=state.run_id))
        out.assumptions = ['no_heat_loss','uniform_pressure','equilibrium_stages']

    @staticmethod
    def estimate_column_equipment(state, out):
        from ..design.equipment import size_column,equipment_policy_for
        options,origin = equipment_policy_for(state.basis)
        native = state.artifacts['verify_and_refine_column'].data['selected_simulation']
        out.data = size_column(native,options)
        out.data['equipment_policy_origin']=origin
        out.validation = {'passed':out.data['passed'], 'scope':'preliminary sizing and explicitly listed hydraulic checks',
                          'full_hydraulic_validation':False,'pressure_feedback_verified':False}
        out.assumptions = [options.tray_type+'_candidate','equipment_geometry_and_design_margins_are_explicit_estimates',
                           'orifice_coefficient_requires_geometry_validation','uniform_pressure_transport_properties']
        out.warnings = out.data.get('unresolved_checks',[])
        out.units = {'diameter_m':'m','active_height_m':'m','estimated_column_pressure_drop_kPa':'kPa'}

    @staticmethod
    def estimate_auxiliary_equipment(state, out):
        from ..design.equipment import size_auxiliaries,equipment_policy_for,lmtd
        from sepmind.simulation.dwsim import DwsimBackend, UtilityWaterRequest, LiquidConditionRequest
        from ..design.pump import feed_conditioning
        options,origin = equipment_policy_for(state.basis)
        native = state.artifacts['verify_and_refine_column'].data['selected_simulation']
        utility = DwsimBackend().utility_water(UtilityWaterRequest(options.cooling_inlet_K,
                                   options.cooling_outlet_K,options.steam_pressure_Pa))
        out.data = size_auxiliaries(native,options,utility)
        request=native['request']
        cold=DwsimBackend().liquid_condition(LiquidConditionRequest(
            tuple(request['components']),request['property_package'],request['feed_light_fraction'],
            options.pump.storage_temperature_K,options.pump.storage_pressure_Pa))
        column=state.artifacts['estimate_column_equipment'].data
        out.data['feed_pump']=feed_conditioning(native,column,cold,options)
        heater=out.data['feed_pump']['feed_heater']
        ts=utility['outputs']['steam_saturation_K']
        if ts-heater['target_temperature_K']<options.minimum_approach_K:
            raise ValueError('UTILITY_APPROACH: feed-heater steam approach is insufficient')
        heater['LMTD_K']=lmtd(ts-heater['inlet_temperature_K'],ts-heater['target_temperature_K'])
        heater['assumed_U_W_m2_K']=options.reboiler_U_W_m2_K
        heater['area_m2']=heater['duty_kW']*1000*options.area_margin/(heater['assumed_U_W_m2_K']*heater['LMTD_K'])
        out.data['utilities']['feed_heater_steam_kg_s']=heater['duty_kW']/utility['outputs']['steam_latent_heat_kJ_kg']
        out.data['utilities']['total_steam_kg_s']=out.data['utilities']['steam_kg_s']+out.data['utilities']['feed_heater_steam_kg_s']
        out.data['passed']=out.data['passed'] and out.data['feed_pump']['passed']
        out.data['unresolved_checks']=[s for s in out.data['unresolved_checks'] if not s.startswith('pump suction')]
        out.data['unresolved_checks'] += ['cold-feed properties require separate qualification; NPSHr and vendor curves remain pending unless supplied']
        out.data['equipment_policy_origin']=origin
        out.evidence.append(EvidenceRecord(evidence_id=utility['evidence_id'],type='solver_run',source=state.run_id))
        out.evidence.append(EvidenceRecord(evidence_id=cold['evidence_id'],type='solver_run',source=state.run_id))
        out.validation = {'passed':out.data['passed'],'native_utility_properties':True,
                          'scope':'preliminary exchangers, cold-feed Bernoulli/Colebrook pump, NPSHa and conditioning energy under explicit teaching assumptions',
                          'vendor_rating_and_selection_verified':False}
        out.assumptions = ['agent_proposed_equipment_assumptions' if state.basis.equipment is None else options.assumption_origin,
                           'assumed_U_and_pipe_geometry_are_not_rated_or_measured',
                           'isothermal_total_condensation_LMTD_approximation']
        out.warnings = out.data['unresolved_checks']

    @staticmethod
    def check_design_consistency(state, out):
        checks = {}
        if state.artifacts.get('resolve_property_parameters') and state.artifacts['resolve_property_parameters'].status=='success':
            package = package_for(state.basis)
            if hasattr(package,'reference_check'):
                checks['independent_property_reference'] = package.reference_check()
        if state.artifacts.get("calculate_binary_vle") and state.artifacts["calculate_binary_vle"].status == "success":
            checks["VLE"] = vle_checks(state.artifacts["calculate_binary_vle"].data,package=package_for(state.basis))
        if state.artifacts.get("calculate_material_balance") and state.artifacts["calculate_material_balance"].status == "success":
            checks["material_balance"] = balance_checks(state.artifacts["calculate_material_balance"].data)
        if state.artifacts.get("calculate_mccabe_thiele_stages") and state.artifacts["calculate_mccabe_thiele_stages"].status == "success":
            package = package_for(state.basis)
            checks["stages"] = stage_checks(state.artifacts["calculate_mccabe_thiele_stages"].data,
                                            state.artifacts["calculate_material_balance"].data,
                                            equilibrium=lambda x: package.point(x,state.basis.feed.pressure_kPa*1000)["y"][0])
        native = state.artifacts.get('verify_and_refine_column')
        if native and native.status=='success' and native.data.get('selected_simulation'):
            from ..design.rigorous import product_checks, energy_balance
            checks['rigorous_products'] = product_checks(native.data['selected_simulation'],state.basis,
                state.artifacts['calculate_mccabe_thiele_stages'].data['reflux_ratio'])
            checks['enthalpy_balance'] = energy_balance(native.data['selected_simulation'])
            column=state.artifacts.get('estimate_column_equipment')
            auxiliary=state.artifacts.get('estimate_auxiliary_equipment')
            if column and column.status=='success' and column.validation.get('passed'):
                from ..validation.equipment import equipment_checks
                from ..design.equipment import equipment_policy_for
                checks['equipment_invariants']=equipment_checks(native.data['selected_simulation'],column.data,
                    auxiliary.data if auxiliary and auxiliary.status=='success' else None,
                    equipment_policy_for(state.basis)[0])
        issues = [{"gate": key, "severity": "blocker", "reason": gate.reason or gate.status}
                  for key,gate in state.gates.items() if key not in ("G8","G9") and gate.status != "passed"]
        for name in ('estimate_column_equipment','estimate_auxiliary_equipment'):
            artifact = state.artifacts.get(name)
            if artifact and artifact.status=='success':
                issues += [{'gate':self_gate,'severity':'major','reason':reason,'artifact_id':artifact.artifact_id}
                           for reason in artifact.data.get('unresolved_checks',[])
                           for self_gate in [EngineeringToolRegistry.TOOLS[name][0]]]
        out.data = {"checks": checks, "issues": issues, "complete_design_validated": False,
                    "scope": "independent invariants only; unresolved gates retained"}
        out.validation = {"passed": all(c["passed"] for c in checks.values()),
                          "complete_design_validated": False}
        out.evidence += [EvidenceRecord(evidence_id=a.artifact_id,type="solver_run",source=a.source_or_run)
                         for a in state.artifacts.values() if a.status == "success"]

    @staticmethod
    def render_preliminary_design_report(state, out):
        from ..reporting import render_report
        out.data = {"markdown": render_report(state), "format": "markdown", "level": "partial_preliminary"}
        out.validation = {"passed": True, "meaning": "evidence-linked partial report, not engineering sign-off"}
