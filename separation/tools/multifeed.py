"""Typed multifeed native-column investigation; no executable user models."""
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from pha.engineering.schemas import Contract
from .mixture import MixtureProbePoint, mixture_card, MixtureDwsimBackend


class ColumnFeed(Contract):
    feed_id: str=Field(min_length=1)
    flow_mol_s: float=Field(gt=0,le=1e5)
    mole_fractions: list[float]
    temperature_K: float=Field(ge=293.15,le=570,description='Specified T for TP feeds; numerical temperature guess only when specific_enthalpy_kJ_kg supplies a PH state')
    stage_index: int=Field(ge=0,strict=True)
    source_evidence_id: str=Field(min_length=1)
    specific_enthalpy_kJ_kg: float | None=Field(default=None,ge=-1e6,le=1e6)

    @model_validator(mode='after')
    def fractions(self):
        MixtureProbePoint(point_id='feed',mole_fractions=self.mole_fractions,pressure_Pa=101325)
        return self


class MultiFeedColumnRequest(Contract):
    property_card_id: Literal['mch_toluene_phenol_unifac_v1','mch_toluene_phenol_hydraulic_sensitivity_v2','mch_toluene_phenol_source_pure_v2','acetone_water_3methylhexane_unifac_candidate','mch_toluene_sulfolane_vle_brouwer2021','sulfolane_recovery_ternary_vle_seed_v1']
    purpose: Literal['source_reconstruction','design_candidate']
    feeds: list[ColumnFeed]=Field(min_length=1,max_length=4)
    pressure_pa: float=Field(ge=8000,le=110000)
    bottom_pressure_pa: float | None=None
    distillate_flow_mol_s: float=Field(gt=0)
    reflux_ratio: float=Field(ge=0,le=30)
    column_mode: Literal['total_condenser','reboiled_absorber']='total_condenser'
    equilibrium_stages: int=Field(ge=3,le=100,strict=True)
    save_path: str | None=None
    include_profiles: bool=True
    solver_preference: Literal['default','modified_bubble_point','simultaneous_correction']='default'
    solver_iteration_limit: int=Field(default=300,ge=20,le=1000,strict=True)
    solver_attempt_limit: int=Field(default=3,ge=1,le=3,strict=True)
    solver_tolerance: float=Field(default=1e-5,ge=1e-12,le=1e-5)
    numerical_solver: Literal['native','sparse_trust_region']='native'
    numerical_jacobian_policy: Literal['sparse_finite_difference','native_dense','balanced_reduced','log_mesh']='sparse_finite_difference'
    initial_profile: list[dict] | None=None
    initial_estimate_source_evidence_id: str | None=None
    positive_balance_initialization: bool=False
    trace_relative_finite_differences: bool=False
    strict_flash_tolerances: bool=False
    refine_ph_feed: bool=False
    project_exact_absent_species: bool=False
    canonicalize_roundoff_compositions: bool=False

    @property
    def components(self):return tuple(mixture_card(self.property_card_id)[0]['native_names'])
    @property
    def property_package(self):return mixture_card(self.property_card_id)[0]['model']
    @property
    def feed_stage(self):return self.feeds[0].stage_index
    @property
    def feed_molar_flow_mol_s(self):return sum(f.flow_mol_s for f in self.feeds)
    @property
    def feed_mole_fractions(self):
        return [sum(f.flow_mol_s*f.mole_fractions[i] for f in self.feeds)/self.feed_molar_flow_mol_s for i in range(len(self.components))]
    @property
    def feed_temperature_K(self):return None

    @model_validator(mode='after')
    def physical(self):
        card,_=mixture_card(self.property_card_id)
        if self.column_mode=='total_condenser' and (self.reflux_ratio<=0 or any(f.stage_index==0 for f in self.feeds)):
            raise ValueError('Positive reflux and interior feeds required for a total condenser')
        recovery_cards={'mch_toluene_sulfolane_vle_brouwer2021','sulfolane_recovery_ternary_vle_seed_v1'}
        if self.column_mode=='reboiled_absorber' and (self.property_card_id not in recovery_cards or self.reflux_ratio!=0 or (self.numerical_solver!='native' and self.numerical_jacobian_policy not in ('balanced_reduced','log_mesh'))):
            raise ValueError('External-decanter stripper requires source sulfolane VLE, explicit reflux feed and the native solver')
        if self.numerical_jacobian_policy=='log_mesh' and (self.column_mode!='reboiled_absorber' or self.initial_profile is None):
            raise ValueError('Logarithmic native MESH requires a source-tagged stripper initialization')
        tlo,thi=card['temperature_guard_K'];plo,phi=card['pressure_guard_Pa']
        if self.property_card_id not in recovery_cards and self.pressure_pa<95000:
            raise ValueError('Vacuum investigation is registered only for the source sulfolane VLE model')
        if any(not tlo<=f.temperature_K<=thi for f in self.feeds) or not plo<=self.pressure_pa<=phi:
            raise ValueError('Source model calculation guard exceeded')
        if len({f.feed_id for f in self.feeds})!=len(self.feeds):raise ValueError('Distinct feed IDs required')
        if len({f.stage_index for f in self.feeds})!=len(self.feeds):
            raise ValueError('Same-stage feeds require an explicit enthalpy-conserving mixer before this native adapter')
        if any(len(f.mole_fractions)!=len(self.components) for f in self.feeds):raise ValueError('Feed model/order mismatch')
        if any(f.stage_index>=self.equilibrium_stages for f in self.feeds):raise ValueError('Feeds must enter interior stages')
        if self.distillate_flow_mol_s>=self.feed_molar_flow_mol_s:raise ValueError('Nonpositive bottoms')
        maximum_bottom=200000 if self.property_card_id=='mch_toluene_phenol_hydraulic_sensitivity_v2' else 120000
        if self.bottom_pressure_pa is not None and not self.pressure_pa<=self.bottom_pressure_pa<=maximum_bottom:raise ValueError('Invalid pressure profile')
        if self.bottom_pressure_pa is not None and not plo<=self.bottom_pressure_pa<=phi:raise ValueError('Bottom pressure exceeds property-card guard')
        if self.save_path:
            path=Path(self.save_path);root=Path(__file__).resolve().parents[2]/'output'
            if not path.is_absolute() or not path.resolve().is_relative_to(root) or path.suffix.lower()!='.dwxmz':raise ValueError('Workspace native output only')
        if (self.initial_profile is None)!=(self.initial_estimate_source_evidence_id is None):raise ValueError('Warm-start provenance required')
        if self.initial_profile is not None:
            if len(self.initial_profile)!=self.equilibrium_stages+(self.column_mode=='total_condenser'):raise ValueError('Complete stage profile required')
            for row in self.initial_profile:
                if set(row)!={'temperature_K','liquid_flow_mol_s','vapor_flow_mol_s','liquid_mole_fractions','vapor_mole_fractions'}:raise ValueError('Unknown initial-estimate fields')
                import math
                for key in ('temperature_K','liquid_flow_mol_s','vapor_flow_mol_s'):
                    if not isinstance(row[key],(int,float)) or not math.isfinite(row[key]) or row[key]<0:raise ValueError('Invalid numerical initial estimate')
                if not tlo<=row['temperature_K']<=thi:raise ValueError('Initial temperature outside guard')
                for key in ('liquid_mole_fractions','vapor_mole_fractions'):
                    MixtureProbePoint(point_id='estimate',mole_fractions=row[key],pressure_Pa=self.pressure_pa)
                    if len(row[key])!=len(self.components):raise ValueError('Estimate component mismatch')
        return self


class MultiFeedDwsimBackend(MixtureDwsimBackend):
    def column(self,request):
        if not isinstance(request,MultiFeedColumnRequest):raise TypeError('Expected typed multifeed column request')
        return self._run('multifeed_candidate_column',request.model_dump())
