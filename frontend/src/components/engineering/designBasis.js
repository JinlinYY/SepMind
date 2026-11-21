// Intake feedback only. The Python contracts and gates remain authoritative.
export function missingDesignInputs(basis) {
  if (!basis || typeof basis !== 'object' || Array.isArray(basis)) return ['设计任务必须是一个 JSON 对象']
  const missing = []
  const positive = value => typeof value === 'number' && Number.isFinite(value) && value > 0
  const fraction = value => positive(value) && value < 1
  if (basis.process_family && basis.process_family !== 'binary_distillation') {
    if (!Array.isArray(basis.components) || basis.components.length < 2) missing.push('组分身份')
    const feed = basis.streams?.find(s => s.stream_id === basis.feed_stream_id)
    if (!feed || !positive(feed.flow) || !['kg/h', 'kmol/h'].includes(feed.flow_unit)) missing.push('预处理后萃取进料流量及单位')
    if (!feed?.composition || !Object.keys(feed.composition).length || Math.abs(Object.values(feed.composition).reduce((a, b) => a + b, 0) - 1) > 1e-8) missing.push('预处理后进料组成及质量/摩尔基准')
    if (!positive(basis.extraction_temperature_K) || !positive(basis.extraction_pressure_Pa)) missing.push('萃取温度（K）及压力（Pa）')
    if (!basis.solvent_component_id || !basis.carrier_component_id || !basis.solute_component_id) missing.push('萃取剂、载体与溶质身份')
    if (!basis.targets?.length) missing.push('明确的产品、回收率或浓度目标')
    return missing
  }
  if (!Array.isArray(basis.components) || basis.components.length !== 2 || basis.components.some(c => !c?.canonical_id || !c?.name)) missing.push('两种组分的名称与身份')
  const feed = basis.feed || {}, target = basis.target || {}
  if (!positive(feed.flow) || !['kmol/h', 'mol/s'].includes(feed.flow_unit)) missing.push('进料流量及单位（kmol/h 或 mol/s）')
  if (!positive(feed.pressure_kPa)) missing.push('操作压力（kPa）')
  if (!Array.isArray(feed.composition) || feed.composition.length !== 2 || feed.composition_basis !== 'mole_fraction' ||
      feed.composition.some(x => typeof x !== 'number' || !Number.isFinite(x) || x < 0 || x > 1) ||
      Math.abs(feed.composition.reduce((a, b) => a + b, 0) - 1) > 1e-8) missing.push('两组分的进料摩尔分数（合计为 1）')
  if (typeof feed.quality_q !== 'number' || !Number.isFinite(feed.quality_q)) missing.push('进料热状态 q（泡点进料为 1）')
  if (!fraction(target.distillate_mole_fraction)) missing.push('塔顶产品中第一组分的目标摩尔分数')
  if (!fraction(target.bottoms_mole_fraction) && !fraction(target.key_component_recovery)) missing.push('塔底目标摩尔分数或第一组分回收率')
  if (basis.design_mode === 'specified' && !positive(basis.column?.reflux_ratio)) missing.push('指定计算模式的操作回流比')
  return missing
}

export function parseDesignInput(text) {
  try {
    const basis = JSON.parse(text)
    return { basis, missing: missingDesignInputs(basis) }
  } catch {
    return { basis: null, missing: ['设计依据 JSON 格式不正确，请重新载入案例或检查编辑内容'] }
  }
}
