"""User-facing intake feedback; no inferred engineering specifications."""

LABELS = {
    'components: two canonical identities': 'Names and identities of two components',
    'feed.pressure_kPa': 'Operating pressure (kPa)',
    'feed.flow and feed.flow_unit': 'Feed flow rate and unit (kmol/h or mol/s)',
    'feed.composition: two mole fractions (mass-fraction conversion not implemented)': 'Feed mole fractions for both components (sum to 1)',
    'feed.quality_q': 'Feed thermal condition q (1 at the bubble point)',
    'target.distillate_mole_fraction': 'Target distillate mole fraction of the first component',
    'target.bottoms_mole_fraction OR target.key_component_recovery': 'Target bottoms mole fraction or first-component recovery',
    'column.reflux_ratio': 'Operating reflux ratio for the specified calculation',
}


def describe_missing(fields):
    return [LABELS.get(field,field) for field in fields]
