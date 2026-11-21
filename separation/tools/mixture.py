"""Typed DWSIM mixture diagnostics; deliberately separate from design admission."""
import json
import hashlib
import math
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .dwsim import DwsimBackend

CARD_ROOT = Path(__file__).resolve().parents[2]/'engineering/data/hybrid'


def mixture_card(card_id):
    allowed = {'acid_li2014_dimer_candidate','acid_dimer_regressed_candidate',
               'abe_oh2021_lle_candidate','abe_oh2021_vle_candidate','acetone_dodecanol_unifac_candidate',
               'acetone_dodecanol_dortmund_candidate','acetone_dodecanol_nist_candidate',
               'acid_pcsaft_native_candidate','mch_toluene_phenol_unifac_v1','mch_toluene_phenol_hydraulic_sensitivity_v2',
               'mch_toluene_phenol_source_pure_v2','mch_toluene_sulfolane_lle_brouwer2021',
               'mch_toluene_sulfolane_vle_brouwer2021','mch_toluene_sulfolane_lle_ternary_brouwer2021',
               'sulfolane_recovery_ternary_vle_seed_v1',
               'acetone_water_3methylhexane_unifac_candidate'}
    if card_id not in allowed:
        raise ValueError('PROPERTY_UNQUALIFIED: unknown mixture model card')
    path = CARD_ROOT/(card_id+'.json')
    data = json.loads(path.read_text(encoding='utf8'))
    ids=data['component_order'];names=data['native_names'];n=len(ids)
    if not 2<=n<=8 or len(set(ids))!=n or len(names)!=n or len(set(names))!=n:
        raise ValueError('INVALID_PROPERTY_CARD: distinct component identities required')
    if data.get('model','NRTL')=='NRTL':
        for key in ('A','B_K','alpha'):
            rows=data[key]
            if len(rows)!=n or any(len(row)!=n or any(not math.isfinite(v) for v in row) for row in rows):
                raise ValueError('INVALID_PROPERTY_CARD: finite square coefficient matrices required')
        if any(data['alpha'][i][j]!=data['alpha'][j][i] or not 0<data['alpha'][i][j]<=1 for i in range(n) for j in range(i+1,n)):
            raise ValueError('INVALID_PROPERTY_CARD: explicit symmetric nonrandomness for every pair required')
    return data, hashlib.sha256(path.read_bytes()).hexdigest()


class MixtureProbePoint(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    point_id: str = Field(min_length=1,max_length=80)
    mole_fractions: list[float] = Field(min_length=2,max_length=8)
    pressure_Pa: float = Field(gt=0,le=2e6)
    temperature_K: float = Field(default=350.,ge=273.15,le=600)
    specification: Literal['TP','bubble','pure_properties','phase_properties'] = 'bubble'
    phase: Literal['liquid','vapor'] = 'liquid'

    @model_validator(mode='after')
    def fractions(self):
        if any(x<0 or x>1 for x in self.mole_fractions) or abs(sum(self.mole_fractions)-1)>1e-9:
            raise ValueError('Fractions must sum to one without silent normalization')
        return self


class MixtureProbeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    property_card_id: str
    points: list[MixtureProbePoint] = Field(min_length=1,max_length=200)
    purpose: Literal['property_qualification'] = 'property_qualification'
    phase_policy: Literal['default','liquid_liquid','direct_lle']='default'
    lle_initialization: Literal['native_default','independent_gibbs']='native_default'

    @model_validator(mode='after')
    def coverage(self):
        card,_ = mixture_card(self.property_card_id)
        for point in self.points:
            if point.specification=='phase_properties':
                if self.property_card_id not in {'mch_toluene_phenol_unifac_v1','mch_toluene_phenol_hydraulic_sensitivity_v2','mch_toluene_sulfolane_vle_brouwer2021','mch_toluene_sulfolane_lle_brouwer2021'}:
                    raise ValueError('Phase transport diagnostic not registered for this model')
                lo,hi=card['temperature_guard_K'];pmin,pmax=card['pressure_guard_Pa']
                if not lo+.01<=point.temperature_K<=hi-.01 or not pmin<=point.pressure_Pa<=pmax:
                    raise ValueError('Phase-property finite-difference stencil outside unchanged model guard')
        if self.lle_initialization!='native_default' and (self.phase_policy!='direct_lle' or card.get('model')!='NRTL'):
            raise ValueError('Gibbs phase estimates are restricted to the registered native NRTL liquid-liquid diagnostic')
        if self.phase_policy!='default' and (self.property_card_id not in {'mch_toluene_sulfolane_lle_brouwer2021','mch_toluene_sulfolane_lle_ternary_brouwer2021'}
            or any(p.specification!='TP' or not 293.15<=p.temperature_K<=303.15 or p.pressure_Pa<(8000 if self.phase_policy=='direct_lle' else 95000) or p.pressure_Pa>101325 for p in self.points)):
            raise ValueError('Liquid-liquid diagnostic is restricted to the source sulfolane ambient-temperature card')
        if len({p.point_id for p in self.points}) != len(self.points):
            raise ValueError('Probe IDs must be unique')
        if any(len(p.mole_fractions)!=len(card['component_order']) for p in self.points):
            raise ValueError('Probe component count differs from model card')
        return self


class MixtureDwsimBackend(DwsimBackend):
    def mixture_probe(self, request):
        if not isinstance(request,MixtureProbeRequest):
            raise TypeError('Expected validated MixtureProbeRequest')
        return self._run('mixture_probe',request.model_dump())

    def candidate_column(self, request):
        if not isinstance(request,CandidateColumnRequest):raise TypeError('Expected validated CandidateColumnRequest')
        return self._run('candidate_mixture_column',request.model_dump())


class CandidateColumnRequest(BaseModel):
    """Native column investigation; never bypasses the runtime model gate.

    Only the nonassociating source ABE VLE card is admitted to this diagnostic.
    Acid energy/columns are deliberately blocked until caloric qualification.
    """
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    purpose: Literal['property_qualification']='property_qualification'
    property_card_id: Literal['abe_oh2021_vle_candidate']
    feed_mole_fractions: list[float]
    feed_molar_flow_mol_s: float=Field(gt=0,le=1e5)
    pressure_pa: float=Field(ge=100000,le=102000)
    distillate_flow_mol_s: float=Field(gt=0)
    reflux_ratio: float=Field(gt=0,le=30)
    equilibrium_stages: int=Field(ge=3,le=100,strict=True)
    feed_stage: int=Field(ge=1,strict=True)
    feed_temperature_K: float | None=Field(ge=298.15,le=460)
    feed_conditioning_source: str | None=None
    bottom_pressure_pa: float | None=None
    save_path: str | None=None
    include_profiles: bool=False
    solver_preference: Literal['default','modified_bubble_point','simultaneous_correction']='default'
    numerical_homotopy_strength: float=Field(default=1.,ge=0,le=1)
    initial_profile: list[dict[str,float | list[float]]] | None=None
    initial_estimate_source_evidence_id: str | None=None

    @property
    def components(self):return tuple(mixture_card(self.property_card_id)[0]['native_names'])
    @property
    def property_package(self):return 'NRTL'
    @model_validator(mode='after')
    def validate_physical(self):
        MixtureProbePoint(point_id='feed',mole_fractions=self.feed_mole_fractions,pressure_Pa=self.pressure_pa)
        if len(self.feed_mole_fractions)!=len(self.components):raise ValueError('Model component mismatch')
        if self.distillate_flow_mol_s>=self.feed_molar_flow_mol_s:raise ValueError('Nonpositive bottoms')
        if self.feed_stage>=self.equilibrium_stages:raise ValueError('Feed must enter an interior stage')
        if self.feed_temperature_K is None and not (self.feed_conditioning_source or '').strip():
            raise ValueError('Saturated-liquid conditioning requires an explicit design decision/source; heater duty remains separate')
        if (self.initial_profile is None)!=(self.initial_estimate_source_evidence_id is None):
            raise ValueError('Warm-start estimates require an explicit provenance ID')
        if self.initial_profile is not None:
            if len(self.initial_profile)!=self.equilibrium_stages+1:raise ValueError('Warm start must cover all stages including condenser')
            fields={'temperature_K','liquid_flow_mol_s','vapor_flow_mol_s','liquid_mole_fractions','vapor_mole_fractions'}
            for row in self.initial_profile:
                if set(row)!=fields:raise ValueError('Invalid warm-start fields')
                if not isinstance(row['temperature_K'],(float,int)) or not 298<=row['temperature_K']<=600:raise ValueError('Invalid warm-start temperature')
                for key in ('liquid_flow_mol_s','vapor_flow_mol_s'):
                    if not isinstance(row[key],(float,int)) or row[key]<0:raise ValueError('Invalid warm-start flow')
                for key in ('liquid_mole_fractions','vapor_mole_fractions'):
                    MixtureProbePoint(point_id=key,mole_fractions=row[key],pressure_Pa=self.pressure_pa)
                    if len(row[key])!=len(self.components):raise ValueError('Warm-start composition order mismatch')
        if self.bottom_pressure_pa is not None and not self.pressure_pa<=self.bottom_pressure_pa<=120000:raise ValueError('Pressure outside diagnostic envelope')
        if self.save_path is not None:
            path=Path(self.save_path)
            root=Path(__file__).resolve().parents[2]/'output'
            if not path.is_absolute() or not path.resolve().is_relative_to(root) or path.suffix.lower()!='.dwxmz':
                raise ValueError('Candidate native files must remain in workspace output as .dwxmz')
        return self
