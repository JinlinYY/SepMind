"""Declarative graph edits from the model; no generated code is executed."""
import copy
from pydantic import Field
from ..schemas import Contract


class UnitUpdate(Contract):
    unit_id:str
    changes:dict=Field(min_length=1)


class HybridRevision(Contract):
    base_candidate_id:str
    unit_updates:list[UnitUpdate]=Field(default_factory=list)
    added_units:list[dict]=Field(default_factory=list)
    deleted_unit_ids:list[str]=Field(default_factory=list)
    products:dict[str,str] | None=None
    tears:list[dict] | None=None
    constraint_streams:dict[str,str] | None=None
    evidence_ids:list[str]=Field(min_length=1)
    rationale:str=Field(min_length=1,max_length=3000)


def apply_revision(revision,base,unit_contract,graph_contract):
    if revision.base_candidate_id!=base['candidate_id']:
        raise ValueError('REVISION_BASE: must reference the supplied current candidate')
    graph=copy.deepcopy(base['graph'])
    units={unit['unit_id']:unit for unit in graph['units']}
    changed=set()
    for edit in revision.unit_updates:
        if edit.unit_id in changed or edit.unit_id not in units:
            raise ValueError('REVISION_UNIT: duplicate or unknown edited unit')
        if set(edit.changes)-set(unit_contract.model_fields) or 'unit_id' in edit.changes:
            raise ValueError('REVISION_FIELDS: unknown field or identity change')
        for key,value in edit.changes.items():
            field=unit_contract.model_fields[key]
            if value is None and not field.is_required() and field.default is not None:
                units[edit.unit_id].pop(key,None)
            else:
                units[edit.unit_id][key]=value
        changed.add(edit.unit_id)
    for identifier in revision.deleted_unit_ids:
        if identifier not in units:raise ValueError('REVISION_DELETE: unknown unit')
        units.pop(identifier)
    for unit in revision.added_units:
        parsed=unit_contract.model_validate(unit)
        if parsed.unit_id in units:raise ValueError('REVISION_ADD: duplicate unit')
        units[parsed.unit_id]=parsed.model_dump()
    graph['units']=list(units.values())
    for key in ['products','tears','constraint_streams']:
        value=getattr(revision,key)
        if value is not None:graph[key]=value
    return graph_contract.model_validate(graph)


def pressure_findings(graph,basis):
    units={unit.unit_id:unit for unit in graph.units}
    tears={tear.tear_id:tear for tear in graph.tears}
    findings=[]
    def output_pressure(reference,seen=()):
        if reference=='fresh':return basis.fresh_pressure_Pa
        if reference.startswith('tear.'):return tears[reference.split('.')[1]].pressure_Pa
        source=units[reference.split('.')[0]]
        if source.kind=='splitter' and source.unit_id not in seen:
            return output_pressure(source.inputs[0],(*seen,source.unit_id))
        if source.kind=='column' and reference.endswith('.bottoms'):
            return source.bottom_pressure_Pa or source.pressure_Pa
        return source.pressure_Pa
    for unit in graph.units:
        if unit.kind in {'pump','splitter'}:continue
        for index,reference in enumerate(unit.inputs):
            pressure=output_pressure(reference)
            required=unit.pressure_Pa
            if unit.kind=='column' and unit.bottom_pressure_Pa is not None:
                denominator=unit.stages if unit.column_mode=='total_condenser' else unit.stages-1
                required+=(unit.bottom_pressure_Pa-unit.pressure_Pa)*unit.feed_stages[index]/denominator
            if required>pressure+1:
                findings.append(dict(unit_id=unit.unit_id,inlet=reference,inlet_pressure_Pa=pressure,
                    proposed_pressure_Pa=required,
                    required_action='Choose pressure no higher than inlet or insert a supported liquid pump; preserve original fresh pressure.'))
    return findings
