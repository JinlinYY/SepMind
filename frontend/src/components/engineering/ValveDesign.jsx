import React from 'react'

function ValveLayout({ name, layout }) {
  const g = layout.geometry, scale = 220 / g.diameter_m, r = g.diameter_m * scale / 2
  const weirX = (g.diameter_m / 2 - g.downcomer_width_m) * scale
  return <figure>
    <figcaption>{name}：{layout.valve_count} 个 F1 浮阀；中心距 {(layout.pitch_m * 1000).toFixed(1)} mm</figcaption>
    <svg viewBox="0 0 280 280" role="img" aria-label={`${name}实际计算的F1浮阀布置`}>
      <g transform="translate(140 135)">
        <circle r={r} fill="#f4f8fa" stroke="#176b87" />
        {[-1, 1].map(sign => <line key={sign} x1={sign * weirX} x2={sign * weirX} y1={-g.weir_length_m * scale / 2} y2={g.weir_length_m * scale / 2} stroke="#b36719" strokeWidth="2" />)}
        {layout.centers_m.map(([x, y], i) => <circle key={i} cx={x * scale} cy={-y * scale} r={layout.hole_diameter_m * scale / 2} fill="none" stroke="#176b87" strokeWidth="0.6" />)}
      </g>
      <text x="70" y="268">塔径 {g.diameter_m.toFixed(2)} m · 孔径 39 mm</text>
    </svg>
  </figure>
}

function PerformanceChart({ name, chart }) {
  const clipId = React.useId().replaceAll(':', '')
  const p = chart.points
  const xmax = chart.liquid_max_m3_s * 1.05
  const ymax = Math.max(chart.operating_point.vapor_flow_m3_s, ...p.map(t => Math.min(t.fair_capacity_vapor_max_m3_s, t.downcomer_backup_vapor_max_m3_s, t.entrainment_vapor_max_m3_s ?? Infinity))) * 1.25
  const x = v => 55 + 285 * v / xmax, y = v => 220 - 170 * v / ymax
  const keys = ['fair_capacity_vapor_max_m3_s', 'downcomer_backup_vapor_max_m3_s', 'entrainment_vapor_max_m3_s']
  const colors = ['#176b87', '#b36719', '#8c4192']
  const line = key => p.filter(t => t[key] != null).map(t => `${x(t.liquid_flow_m3_s)},${y(t[key])}`).join(' ')
  return <figure>
    <figcaption>{name}负荷性能（代表平衡级 {chart.representative_equilibrium_stage}；固定物性）</figcaption>
    <svg viewBox="0 0 380 280" role="img" aria-label={`${name}实际计算的负荷性能图`}>
      <defs><clipPath id={clipId}><rect x="55" y="35" width="290" height="185" /></clipPath></defs>
      <path d="M55 35V220H345" fill="none" stroke="currentColor" />
      {keys.map((key, i) => <polyline key={key} points={line(key)} fill="none" stroke={colors[i]} strokeWidth="1.5" clipPath={`url(#${clipId})`} />)}
      <line x1="55" x2="340" y1={y(p[0].minimum_vapor_m3_s)} y2={y(p[0].minimum_vapor_m3_s)} stroke="#bf3347" strokeDasharray="4 3" />
      {[chart.liquid_min_m3_s, chart.liquid_max_m3_s].map((v, i) => <line key={i} x1={x(v)} x2={x(v)} y1="35" y2="220" stroke="#737b83" strokeDasharray="3 3" />)}
      <circle cx={x(chart.operating_point.liquid_flow_m3_s)} cy={y(chart.operating_point.vapor_flow_m3_s)} r="4" fill="#bf3347" />
      <text x="58" y="239">0</text><text x="275" y="239">{xmax.toPrecision(3)}</text>
      <text x="2" y="43">{ymax.toPrecision(3)}</text>
      <text x="110" y="260">液相流量 m³/s</text><text x="5" y="20">汽相流量 m³/s</text>
    </svg>
    <p>蓝：Fair 容量；棕：降液管液泛；紫：原案例 CF 夹带指标；红点：实际负荷。</p>
  </figure>
}

export default function ValveDesign({ data }) {
  if (!data?.valve_layouts) return null
  const names = { rectifying: '精馏段', stripping: '提馏段' }
  return <section aria-label="F1浮阀设计">
    <h3>F1 浮阀布置与负荷性能</h3>
    <p>孔数来自图中实际排列，已检查壁面和降液管避让。以下是教学关联式下的初步设计。</p>
    {Object.entries(data.valve_layouts).map(([name, layout]) => <ValveLayout key={name} name={names[name] || name} layout={layout} />)}
    {data.load_window && <p>估计负荷范围 {(data.load_window.minimum_relative_load * 100).toFixed(1)}%～{(data.load_window.maximum_relative_load * 100).toFixed(1)}%；操作弹性 {data.load_window.operating_elasticity_estimate.toFixed(2)}。物性按本工况固定。</p>}
    {Object.entries(data.load_performance_charts || {}).map(([name, chart]) => <PerformanceChart key={name} name={names[name] || name} chart={chart} />)}
    <details><summary>所用假设与尚待确认的内容</summary><pre>{JSON.stringify({ source: data.sources, geometry: data.geometry, unresolved: data.unresolved_checks }, null, 2)}</pre></details>
  </section>
}
