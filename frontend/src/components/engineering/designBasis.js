// Intake feedback only. The Python contracts and gates remain authoritative.
export function missingDesignInputs(basis) {
  if (!basis || typeof basis !== 'object' || Array.isArray(basis)) return ['The design task must be a JSON object']
  const missing = []
  const positive = value => typeof value === 'number' && Number.isFinite(value) && value > 0
  const fraction = value => positive(value) && value < 1
  if (basis.process_family && basis.process_family !== 'binary_distillation') {
    if (!Array.isArray(basis.components) || basis.components.length < 2) missing.push('Component identities')
    const feed = basis.streams?.find(s => s.stream_id === basis.feed_stream_id)
    if (!feed || !positive(feed.flow) || !['kg/h', 'kmol/h'].includes(feed.flow_unit)) missing.push('Pretreated extraction feed flow rate and unit')
    if (!feed?.composition || !Object.keys(feed.composition).length || Math.abs(Object.values(feed.composition).reduce((a, b) => a + b, 0) - 1) > 1e-8) missing.push('Pretreated feed composition and mass or molar basis')
    if (!positive(basis.extraction_temperature_K) || !positive(basis.extraction_pressure_Pa)) missing.push('Extraction temperature (K) and pressure (Pa)')
    if (!basis.solvent_component_id || !basis.carrier_component_id || !basis.solute_component_id) missing.push('Solvent, carrier, and solute identities')
    if (!basis.targets?.length) missing.push('Product, recovery, or concentration targets')
    return missing
  }
  if (!Array.isArray(basis.components) || basis.components.length !== 2 || basis.components.some(c => !c?.canonical_id || !c?.name)) missing.push('Names and identities of two components')
  const feed = basis.feed || {}, target = basis.target || {}
  if (!positive(feed.flow) || !['kmol/h', 'mol/s'].includes(feed.flow_unit)) missing.push('Feed flow rate and unit (kmol/h or mol/s)')
  if (!positive(feed.pressure_kPa)) missing.push('Operating pressure (kPa)')
  if (!Array.isArray(feed.composition) || feed.composition.length !== 2 || feed.composition_basis !== 'mole_fraction' ||
      feed.composition.some(x => typeof x !== 'number' || !Number.isFinite(x) || x < 0 || x > 1) ||
      Math.abs(feed.composition.reduce((a, b) => a + b, 0) - 1) > 1e-8) missing.push('Feed mole fractions for both components (sum to 1)')
  if (typeof feed.quality_q !== 'number' || !Number.isFinite(feed.quality_q)) missing.push('Feed thermal condition q (1 at the bubble point)')
  if (!fraction(target.distillate_mole_fraction)) missing.push('Target distillate mole fraction of the first component')
  if (!fraction(target.bottoms_mole_fraction) && !fraction(target.key_component_recovery)) missing.push('Target bottoms mole fraction or first-component recovery')
  if (basis.design_mode === 'specified' && !positive(basis.column?.reflux_ratio)) missing.push('Operating reflux ratio for the specified calculation')
  return missing
}

export function parseDesignInput(text) {
  try {
    const basis = JSON.parse(text)
    return { basis, missing: missingDesignInputs(basis) }
  } catch {
    return { basis: null, missing: ['Invalid design basis JSON. Reload the case or correct the entry.'] }
  }
}
