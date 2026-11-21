"""User-facing intake feedback; no inferred engineering specifications."""

LABELS = {
    'components: two canonical identities': '两种组分的名称与身份',
    'feed.pressure_kPa': '操作压力（kPa）',
    'feed.flow and feed.flow_unit': '进料流量及单位（kmol/h 或 mol/s）',
    'feed.composition: two mole fractions (mass-fraction conversion not implemented)': '两组分的进料摩尔分数（合计为 1）',
    'feed.quality_q': '进料热状态 q（泡点进料为 1）',
    'target.distillate_mole_fraction': '塔顶产品中第一组分的目标摩尔分数',
    'target.bottoms_mole_fraction OR target.key_component_recovery': '塔底目标摩尔分数或第一组分回收率',
    'column.reflux_ratio': '指定计算模式的操作回流比',
}


def describe_missing(fields):
    return [LABELS.get(field,field) for field in fields]
