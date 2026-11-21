import React, { useEffect, useRef, useState } from 'react'
import { missingDesignInputs, parseDesignInput } from './designBasis'
import './engineering.css'
import ValveDesign from './ValveDesign'

export function EngineeringStart({ onStart, loading, error }) {
  const [basis, setBasis] = useState('{}')
  const [provider, setProvider] = useState('deepseek')
  const [designLevel, setDesignLevel] = useState('preliminary_equipment')
  const [equipmentPolicy, setEquipmentPolicy] = useState(null)
  const [localError, setLocalError] = useState('')
  const [exampleCase, setExampleCase] = useState('water_ethanol')
  const [exampleLoading, setExampleLoading] = useState(true)
  const requestVersion = useRef(0)
  const loadExample = async caseName => {
    const version = ++requestVersion.current
    setExampleLoading(true); setLocalError('')
    try {
      const res = await fetch(`/api/engineering/example?case=${caseName}`)
      if (!res.ok) throw new Error('案例加载失败，请点击重新载入')
      const loaded = await res.json()
      if (version === requestVersion.current) setBasis(JSON.stringify(loaded, null, 2))
    } catch (e) {
      if (version === requestVersion.current) setLocalError(e.message)
    } finally {
      if (version === requestVersion.current) setExampleLoading(false)
    }
  }
  useEffect(() => {
    loadExample(exampleCase)
    return () => { requestVersion.current += 1 }
  }, [exampleCase])
  const parsed = parseDesignInput(basis)
  const showEquipmentPolicy = async () => {
    try {
      const response = await fetch('/api/engineering/equipment-policy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(parsed.basis) })
      if (!response.ok) throw new Error('请先补全有效的设计依据')
      setEquipmentPolicy(await response.json())
    } catch (e) { setLocalError(e.message) }
  }
  return <main className="engineering-start">
    <h1>SepMind · 既定拓扑设计</h1>
    <p>在既定单塔或已声明联合流程中开展专家引导的参数设计与验证。输入原料、组成、压力、进料状态和分离目标后，Agent可选择物性方法、检验可行性，并比较回流比与理论级数方案。深化模式接入本机DWSIM，验证产品目标、修正级数，并计算能量和初步设备估算。</p>
    <label>案例<select aria-label="案例" value={exampleCase} onChange={e => {
      requestVersion.current += 1; setBasis('{}'); setExampleLoading(true); setExampleCase(e.target.value)
    }}>
      <option value="water_ethanol">水／乙醇参数自主设计（既定单塔拓扑）</option>
      <option value="heptane_nonane">正庚烷／正壬烷指定条件计算</option>
      <option value="case-1a">人类案例 1a：苯／甲苯，42 wt% 进料</option>
      <option value="case-1b">人类案例 1b：苯／甲苯，36 wt% 进料</option>
      <option value="case-2">人类案例 2：乙醇／水，48 wt% 进料</option>
      <option value="case-3">人类案例 3：甲醇／水，40 wt% 进料</option>
      <option value="case-5">案例 5：醋酸萃取—精馏（当前计算萃取段）</option>
      <option value="case-6">案例 6：含酚废水萃取—精馏（入口待补）</option>
    </select></label>
    <button disabled={exampleLoading} onClick={() => loadExample(exampleCase)}>重新载入所选案例</button>
    {exampleLoading ? <p role="status">正在载入所选案例，请稍候…</p> : parsed.missing.length ?
      <section aria-label="设计依据检查"><p>设计依据尚不完整，请补充以下内容后进入：</p><ul>{parsed.missing.map(m => <li key={m}>{m}</li>)}</ul></section> :
      <p role="status">{parsed.basis.process_family ? '多组分任务已载入。当前萃取段可计算，完整溶剂回收和能量设计尚待验证。' : `设计依据已载入：进料 ${parsed.basis.feed.flow} ${parsed.basis.feed.flow_unit}；压力 ${parsed.basis.feed.pressure_kPa} kPa；进料摩尔分数 ${parsed.basis.feed.composition.join(' / ')}。请检查后确认进入。`}</p>}
    <label>设计依据 JSON（可编辑）<textarea aria-label="设计依据 JSON" disabled={exampleLoading} value={basis} onChange={e => { setBasis(e.target.value); setLocalError('') }} /></label>
    <label>规划方式<select aria-label="规划方式" value={provider} onChange={e => setProvider(e.target.value)}>
      <option value="deterministic">确定性专家工作流（无需 Key）</option>
      <option value="deepseek">DeepSeek（服务端环境变量）</option>
      <option value="qwen">千问 Qwen（服务端密钥配置）</option>
    </select></label>
    {!parsed.basis?.process_family && <label>计算深度<select aria-label="计算深度" value={designLevel} onChange={e => setDesignLevel(e.target.value)}>
      <option value="preliminary_process">流程筛查：相平衡、衡算与理论级</option>
      <option value="preliminary_equipment">深化计算：DWSIM 反馈修正、能量与初步设备</option>
    </select></label>}
      {!parsed.basis?.process_family && designLevel === 'preliminary_equipment' && <p>需要本机 DWSIM，运行可能持续数分钟。F1 内件、管路及传热系数采用可查看和修改的教学假设；程序计算泵扬程和 NPSHa。完整水力学、压降反馈和厂家选型仍须进一步校核。</p>}
    {!parsed.basis?.process_family && designLevel === 'preliminary_equipment' && <><button disabled={exampleLoading || parsed.missing.length > 0} onClick={showEquipmentPolicy}>查看本案例教学假设</button>
      {equipmentPolicy && <details open><summary>F1 内件与公用工程假设</summary><p>{equipmentPolicy.origin}</p><pre>{JSON.stringify(equipmentPolicy.equipment, null, 2)}</pre></details>}</>}
    <p>{parsed.basis?.process_family ? '当前联合流程分支只放行已验证工具。案例5可计算等温萃取段；案例6需补齐入口，完整再生循环与能量尚未验证。' : '任务的流量、目标、理想性与恒摩尔流假设均由你查看后提交，不是实验验证结果。'}</p>
    <button disabled={loading || exampleLoading || parsed.missing.length > 0} onClick={() => {
      try {
        setLocalError('')
        onStart({ workspace: 'engineering', provider, baseline: 'sepmind', persona_id: 'engineering',
          ...(provider === 'deterministic' ? { model_id: 'deterministic' } : {}),
          engineering_basis: parsed.basis.process_family ? parsed.basis : { ...parsed.basis, design_level: designLevel }, user_id: 'engineering' })
      } catch (e) { setLocalError(e.message) }
    }}>确认任务并进入设计</button>
    {(error || localError) && <p role="alert">{error || localError}</p>}
  </main>
}

function PhasePlot({ points }) {
  if (!points?.length) return null
  const temps = points.map(p => p.temperature_K)
  const low = Math.min(...temps) - 1, high = Math.max(...temps) + 1
  const x = v => 35 + 300 * v
  const y = t => 195 - 155 * (t - low) / (high - low)
  const line = key => points.map(p => `${x(p[key][0])},${y(p.temperature_K)}`).join(' ')
  return <figure><figcaption>真实工具输出 T–x–y 图（K；组分 0 摩尔分数）</figcaption>
    <svg viewBox="0 0 370 235" role="img" aria-label="工具计算的二元 Txy 相图">
      <path d="M35 25V195H340" fill="none" stroke="currentColor" />
      <polyline points={line('x')} fill="none" stroke="#176b87" strokeWidth="2" />
      <polyline points={line('y')} fill="none" stroke="#bb4d00" strokeWidth="2" />
      <text x="35" y="215">0</text><text x="330" y="215">1</text>
      <text x="2" y="40">{high.toFixed(0)}</text><text x="2" y="195">{low.toFixed(0)}</text>
      <text x="90" y="232">蓝：液相 x；橙：汽相 y</text>
    </svg></figure>
}

function ExpertDecisionPath({ records }) {
  const conclusions = { admitted_for_test: '允许检验', supported_conditionally: '条件性支持', refuted: '被计算反证', needs_input: '待补证据', blocked: '阻断' }
  const actions = {
    continue_only_with_declared_assumptions: '在已声明近似和范围内继续',
    invoke_counterevidence_policy: '转入反证诊断',
    request_operating_domain_evidence: '补充当前工况的适用范围证据',
    request_qualified_parameters_or_other_qualified_model: '补充合格参数或审查其他有证据的模型',
    request_explicit_assumptions_or_model_review: '明确假设并重新审查模型',
    reject_parameter_hypothesis_and_review_model: '拒绝当前参数假设并重新审查模型',
    reject_ordinary_column_and_review_alternative_routes: '拒绝当前普通单塔方案，审查替代路线',
    exclude_rejected_computed_candidates: '剔除计算失败的候选，只允许选择可行方案',
    reconcile_conflicting_inputs_before_recomputation: '核对冲突输入后重算',
    review_reflux_or_stage_constraints: '复查回流比或级数约束', stop_and_review_evidence: '停止并审查证据',
  }
  if (!records?.length) return null
  return <section aria-label="专家决策路径">
    <h3>专家决策路径</h3>
    <p>输入判据 → 方法假设 → 计算检验 → 结论与后续动作</p>
    {records.map((r, index) => <details key={r.record_id} open={index === 0}>
      <summary>{r.gate} · {r.title} · {conclusions[r.conclusion]}{r.reused ? '（复用已有证据）' : ''}</summary>
      <p><strong>判断依据：</strong>{r.input_facts.component_order?.join(' / ')}；压力 {r.input_facts.pressure_kPa} kPa；{r.input_facts.mixture_class}</p>
      <p><strong>待检验假设：</strong>{r.hypothesis}</p>
      {!!r.model_options.length && <table aria-label="模型候选审查"><thead><tr><th>模型</th><th>判定</th><th>依据</th></tr></thead><tbody>
        {r.model_options.map(m => <tr key={m.model}><td>{m.model}</td><td>{m.eligible ? '可检验' : '排除'}</td><td>{m.reasons.join('；')}</td></tr>)}
      </tbody></table>}
      <p><strong>结论：</strong>{conclusions[r.conclusion]}；{actions[r.next_action] || r.next_action}</p>
      <p>Skill：{r.skill_id} v{r.skill_version}；证据来源运行：{r.source_run_id}</p>
      {r.action_status === 'recommendation_only' && <p>这里记录的是后续建议，尚未执行新的设计。</p>}
      <details><summary>查看实际检验结果与限制</summary><pre>{JSON.stringify({ observations: r.observations, limitations: r.limitations, evidence: r.evidence_after }, null, 2)}</pre></details>
    </details>)}
  </section>
}

export function EngineeringPanel({ session, onOpenTopology }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [pressure, setPressure] = useState('')
  const base = `/api/engineering/sessions/${session.session_id}`
  const refresh = async () => {
    const res = await fetch(`${base}/state`)
    if (res.ok) setData(await res.json())
  }
  useEffect(() => {
    let active = true
    const poll = async () => { const res = await fetch(`${base}/state`); if (res.ok && active) setData(await res.json()) }
    poll().catch(() => {})
    const timer = setInterval(() => poll().catch(() => {}), 1500)
    return () => { active = false; clearInterval(timer) }
  }, [base])
  const execute = async (updates, message) => {
    if (!updates && missingInputs.length) { setError('设计依据不完整，请先补充任务或明确载入案例。'); return }
    setBusy(true); setError('')
    try {
      const res = await fetch(`${base}/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message || (updates ? '修改明确指定的压力' : '执行当前设计依据'), task_updates: updates || null }) })
      if (!res.ok) throw new Error((await res.json()).detail || '运行失败')
      setData(await res.json())
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const run = data?.run
  const currentBasis = data?.design_basis || run?.basis || session.config?.engineering_basis || {}
  const missingInputs = data?.missing_inputs || missingDesignInputs(currentBasis)
  const running = busy || run?.status === 'running'
  const loadCaseAndRun = async caseName => {
    setBusy(true); setError('')
    try {
      const res = await fetch(`/api/engineering/example?case=${caseName}`)
      if (!res.ok) throw new Error('案例加载失败，请重试')
      const basis = await res.json()
      if (missingDesignInputs(basis).length) throw new Error('案例任务不完整，未启动计算')
      await execute(basis, `明确载入所选案例 ${caseName} 的设计依据并执行自主设计`)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const balance = run?.artifacts?.calculate_material_balance
  const vle = run?.artifacts?.calculate_binary_vle
  const scheme = run?.artifacts?.select_process_design
  const candidates = run?.artifacts?.explore_reflux_candidates
  const stages = run?.artifacts?.calculate_mccabe_thiele_stages
  const rigorous = run?.artifacts?.verify_and_refine_column
  const energy = run?.artifacts?.calculate_energy_balance
  const equipment = run?.artifacts?.estimate_column_equipment
  const auxiliary = run?.artifacts?.estimate_auxiliary_equipment
  return <aside className="engineering-panel">
    <h2>专家工作流与计算证据</h2>
    {onOpenTopology && <button onClick={onOpenTopology}>进入自主流程设计</button>}
    {!!missingInputs.length && <section aria-label="补充设计依据">
      <h3>当前会话缺少完整设计依据，尚未开始工艺计算</h3>
      <ul>{missingInputs.map(m => <li key={m}>{m}</li>)}</ul>
      <p>{currentBasis.process_family ? '请补齐有来源的萃取入口数据；原始废水组成不能替代脱酸脱氨后的入口。' : '可在左侧输入完整任务，或明确选择以下案例后载入并执行：'}</p>
      {!currentBasis.process_family && <><button disabled={running} onClick={() => loadCaseAndRun('water_ethanol')}>载入水／乙醇案例并执行</button>
      <button disabled={running} onClick={() => loadCaseAndRun('heptane_nonane')}>载入正庚烷／正壬烷案例并执行</button></>}
    </section>}
    <button disabled={running || missingInputs.length > 0} onClick={() => execute()}>执行已提交设计依据</button>
    {running && <p role="status">正在执行，请等待结果，无需重复点击。</p>}
    <label>仅修改压力（kPa）<input aria-label="压力 kPa" type="number" min="0.001" value={pressure} onChange={e => setPressure(e.target.value)} /></label>
    <button disabled={running || missingInputs.length > 0 || !pressure || Number(pressure) <= 0} onClick={() => execute(currentBasis.process_family ? { extraction_pressure_Pa: Number(pressure) * 1000 } : { feed: { pressure_kPa: Number(pressure) } })}>生成修订版本</button>
    {error && <p role="alert">{String(error)}</p>}
    {!run ? <p>尚未运行。没有计算结果可展示。</p> : <>
      <p>版本 {run.revision} · {run.status} · 工具 {run.tool_calls} 次 / LLM {run.llm_calls} 次</p>
      <p>失效关卡：{run.invalidated_gates?.join(', ') || (currentBasis.process_family ? '联合流程修订按完整重算处理' : '首次运行')}；复用证据 {run.reused_artifact_ids?.length || 0} 项</p>
      {currentBasis.process_family ? <section aria-label="联合流程专家决策路径"><h3>专家决策与工具检验</h3>{run.expert_records?.map((r, i) => <p key={i}>{r.gate} · {r.owner} · {r.skill_id} · {r.status}</p>)}</section> : <ExpertDecisionPath records={run.expert_records} />}
      {run.artifacts?.explore_extraction_candidates?.status === 'success' && <section aria-label="真实萃取候选"><h3>已计算的萃取段方案</h3><table><thead><tr><th>候选</th><th>接触级数</th><th>S/F质量比</th><th>萃取回收率</th><th>状态</th></tr></thead><tbody>{run.artifacts.explore_extraction_candidates.data.candidates.map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.stages}</td><td>{c.solvent_feed_mass_ratio}</td><td>{c.raw ? `${(100 * c.raw.solute_extraction_recovery).toFixed(4)}%` : '未接受结果'}</td><td>{c.status}</td></tr>)}</tbody></table><p>仅为等温萃取段。回收率不是全流程产品回收率；完整精馏回收、能量与溶剂循环尚未验证。</p></section>}
      <table aria-label="阶段状态"><thead><tr><th>关卡</th><th>实际状态</th><th>说明</th></tr></thead><tbody>
        {Object.values(run.gates).map(g => <tr key={g.gate}><td>{g.gate}</td><td>{g.status}</td><td>{g.gate === 'G0' && g.status === 'needs_input' && missingInputs.length ? missingInputs.join('；') : g.reason}</td></tr>)}
      </tbody></table>
      {balance?.status === 'success' && balance.validation.passed && <><h3>已校核物流（kmol/h）</h3><table><tbody>
        {balance.data.streams.map(s => <tr key={s.id}><th>{s.id}</th><td>{s.flow_kmol_h.toFixed(6)}</td><td>x₀={s.composition[0].toFixed(6)}</td></tr>)}
      </tbody></table></>}
      {scheme?.status === 'success' && scheme.validation.passed && <section>
        <h3>Agent 的 CMO 初始方案</h3>
        <p>模型：{run.artifacts.select_thermodynamic_model?.data.selected_model}；回流比：{scheme.data.selected_reflux_ratio.toFixed(4)}</p>
        <p>{scheme.data.selection_basis}</p>
        {stages?.status === 'success' && <p>理论级数：{stages.data.theoretical_stages_rounded_up}；进料级：{stages.data.feed_stage_from_top}（从塔顶计，包括部分再沸器、不包括全凝器）</p>}
        {!!candidates?.data.candidates?.length && <table aria-label="回流比方案比较"><thead><tr><th>候选</th><th>回流比</th><th>理论级</th><th>状态</th></tr></thead><tbody>
          {candidates.data.candidates.map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.reflux_ratio?.toFixed(3) || '—'}</td><td>{c.theoretical_stages_rounded_up || '—'}</td><td>{c.status}</td></tr>)}
        </tbody></table>}
        <p>级数和内部汽相流量的方案权衡，尚未证明经济最优；恒摩尔流等方法近似详见导出报告。</p>
      </section>}
      {rigorous && <section aria-label="严格塔反馈修正">
        <h3>DWSIM 严格塔验证与修正</h3>
        <p>原产品指标保持不变；每个候选的产品组成由模拟计算。用户给定的回流约束保持不变。</p>
        <table><thead><tr><th>候选</th><th>级数 / 进料级</th><th>回流比</th><th>实际判定</th></tr></thead><tbody>
          {(rigorous.data.attempts || []).map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.equilibrium_stages} / {c.feed_stage}</td><td>{c.reflux_ratio.toFixed(4)}</td><td>{c.status}</td></tr>)}
        </tbody></table>
        {rigorous.data.selected_candidate && <p>最终方案：{rigorous.data.selected_candidate.equilibrium_stages} 个平衡级，进料级 {rigorous.data.selected_candidate.feed_stage}；原产品目标严格通过。</p>}
      </section>}
      {energy?.status === 'success' && energy.validation.passed && <section aria-label="能量与设备估算">
        <h3>能量与初步设备</h3>
        <p>冷凝负荷 {energy.data.condenser_duty_kW.toFixed(2)} kW；再沸负荷 {energy.data.reboiler_duty_kW.toFixed(2)} kW；能量相对残差 {energy.data.relative_residual.toExponential(2)}。</p>
        {equipment?.validation.passed && <p>塔径估计 {equipment.data.diameter_m.toFixed(2)} m；整体效率估计 {(equipment.data.overall_efficiency_estimate * 100).toFixed(1)}%；实际塔板估计 {equipment.data.actual_trays_estimate}；有效高度 {equipment.data.active_height_m.toFixed(2)} m。</p>}
          {auxiliary?.validation.passed && <p>冷凝器面积估计 {auxiliary.data.condenser.area_m2.toFixed(2)} m²；再沸器面积估计 {auxiliary.data.reboiler.area_m2.toFixed(2)} m²。采用的 U、管路和几何假设可在导出报告中查看。</p>}
          {auxiliary?.validation.passed && auxiliary.data.feed_pump?.feed_heater && <p>
            冷态进料泵：{auxiliary.data.feed_pump.flow_m3_h.toFixed(2)} m³/h，所需扬程 {auxiliary.data.feed_pump.required_head_m.toFixed(2)} m，轴功率 {auxiliary.data.feed_pump.shaft_power_kW.toFixed(3)} kW；NPSHa {auxiliary.data.feed_pump.NPSH_available_m.toFixed(2)} m。
            进料预热负荷 {auxiliary.data.feed_pump.feed_heater.duty_kW.toFixed(2)} kW。NPSHr 和厂家型号以实际提供的数据为准。
          </p>}
        <p>完整漏液/夹带、压降反馈及厂家性能尚待验证；整体效率不等于 Murphree 效率。</p>
      </section>}
      {vle?.status === 'success' && vle.validation.passed && <PhasePlot points={vle.data.points} />}
      {equipment?.validation.passed && <ValveDesign data={equipment.data} />}
      <h3>导出本次实际运行</h3>
      {['json', 'csv', 'md'].map(format => <a className="engineering-export" key={format} href={`${base}/export/${format}`}>{format.toUpperCase()}</a>)}
      <details><summary>决策记录与引用</summary><pre>{JSON.stringify(run.decisions, null, 2)}</pre></details>
      <p>G8 是已执行部分的数值审查；不表示能量、设备、水力学或完整工艺设计已验证。</p>
    </>}
  </aside>
}
