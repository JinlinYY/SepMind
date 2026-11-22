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
      if (!res.ok) throw new Error('Could not load the case. Select Reload selected case.')
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
      if (!response.ok) throw new Error('Complete the design basis before continuing.')
      setEquipmentPolicy(await response.json())
    } catch (e) { setLocalError(e.message) }
  }
  return <main className="engineering-start">
    <h1>SepMind · Prescribed flowsheet design</h1>
    <p>Specify feed, pressure, feed state, and product targets for a prescribed flowsheet. SepMind checks the property method and feasibility and compares reflux and stage counts. The detailed workflow uses DWSIM to verify targets, revise the column design, and estimate heat duties and equipment size.</p>
    <label>Case<select aria-label="Case" value={exampleCase} onChange={e => {
      requestVersion.current += 1; setBasis('{}'); setExampleLoading(true); setExampleCase(e.target.value)
    }}>
      <option value="water_ethanol">Ethanol/water (prescribed single column)</option>
      <option value="heptane_nonane">n-Heptane/n-nonane (specified conditions)</option>
      <option value="case-1a">D01 · Benzene/toluene, 42 wt% benzene</option>
      <option value="case-1b">D02 · Benzene/toluene, 36 wt% benzene</option>
      <option value="case-2">D03 · Ethanol/water, 48 wt% ethanol</option>
      <option value="case-3">D04 · Methanol/water, 40 wt% methanol</option>
      <option value="case-5">Case 5 · Acetic acid extraction and distillation (extraction section)</option>
      <option value="case-6">Case 6 · Phenolic wastewater extraction and distillation (feed data needed)</option>
    </select></label>
    <button disabled={exampleLoading} onClick={() => loadExample(exampleCase)}>Reload selected case</button>
    {exampleLoading ? <p role="status">Loading selected case…</p> : parsed.missing.length ?
      <section aria-label="Design basis checks"><p>Complete the following design inputs to continue.</p><ul>{parsed.missing.map(m => <li key={m}>{m}</li>)}</ul></section> :
      <p role="status">{parsed.basis.process_family ? 'Multicomponent task loaded. Calculations cover the extraction section. Solvent recovery and energy design require further verification.' : `Design basis loaded. Feed ${parsed.basis.feed.flow} ${parsed.basis.feed.flow_unit}, pressure ${parsed.basis.feed.pressure_kPa} kPa, feed mole fractions ${parsed.basis.feed.composition.join(' / ')}. Review the basis before continuing.`}</p>}
    <label>Design basis JSON (editable)<textarea aria-label="Design basis JSON" disabled={exampleLoading} value={basis} onChange={e => { setBasis(e.target.value); setLocalError('') }} /></label>
    <label>Planning mode<select aria-label="Planning mode" value={provider} onChange={e => setProvider(e.target.value)}>
      <option value="deterministic">Deterministic expert workflow</option>
      <option value="deepseek">DeepSeek (server environment)</option>
      <option value="qwen">Qwen (server credentials)</option>
    </select></label>
    {!parsed.basis?.process_family && <label>Calculation scope<select aria-label="Calculation scope" value={designLevel} onChange={e => setDesignLevel(e.target.value)}>
      <option value="preliminary_process">Screening: phase equilibrium, balances, and equilibrium stages</option>
      <option value="preliminary_equipment">Detailed: DWSIM verification and revision, energy balances, and preliminary equipment</option>
    </select></label>}
      {!parsed.basis?.process_family && designLevel === 'preliminary_equipment' && <p>This workflow requires DWSIM and may take several minutes. Review the editable assumptions for F1 valves, piping, and heat-transfer coefficients. The program estimates pump head and NPSHa. Full hydraulics, pressure-drop feedback, and vendor selection require further checks.</p>}
    {!parsed.basis?.process_family && designLevel === 'preliminary_equipment' && <><button disabled={exampleLoading || parsed.missing.length > 0} onClick={showEquipmentPolicy}>Review case assumptions</button>
      {equipmentPolicy && <details open><summary>F1 internals and utility assumptions</summary><p>{equipmentPolicy.origin}</p><pre>{JSON.stringify(equipmentPolicy.equipment, null, 2)}</pre></details>}</>}
    <p>{parsed.basis?.process_family ? 'Case 5 supports isothermal extraction. Case 6 requires additional feed data. Full solvent regeneration, recycle, and energy design remain open.' : 'Review the specified flow, targets, ideality, and constant molar overflow assumptions before submitting.'}</p>
    <button disabled={loading || exampleLoading || parsed.missing.length > 0} onClick={() => {
      try {
        setLocalError('')
        onStart({ workspace: 'engineering', provider, baseline: 'sepmind',
          ...(provider === 'deterministic' ? { model_id: 'deterministic' } : {}),
          engineering_basis: parsed.basis.process_family ? parsed.basis : { ...parsed.basis, design_level: designLevel }, user_id: 'engineering' })
      } catch (e) { setLocalError(e.message) }
    }}>Confirm design basis</button>
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
  return <figure><figcaption>Calculated T–x–y diagram (K and mole fraction of component 0)</figcaption>
    <svg viewBox="0 0 370 235" role="img" aria-label="Calculated binary Txy diagram">
      <path d="M35 25V195H340" fill="none" stroke="currentColor" />
      <polyline points={line('x')} fill="none" stroke="#176b87" strokeWidth="2" />
      <polyline points={line('y')} fill="none" stroke="#bb4d00" strokeWidth="2" />
      <text x="35" y="215">0</text><text x="330" y="215">1</text>
      <text x="2" y="40">{high.toFixed(0)}</text><text x="2" y="195">{low.toFixed(0)}</text>
      <text x="90" y="232">Blue: liquid x. Orange: vapor y.</text>
    </svg></figure>
}

function ExpertDecisionPath({ records }) {
  const conclusions = { admitted_for_test: 'Admitted for testing', supported_conditionally: 'Conditionally supported', refuted: 'Refuted by calculations', needs_input: 'Evidence needed', blocked: 'Blocked' }
  const actions = {
    continue_only_with_declared_assumptions: 'Proceed within declared assumptions and scope',
    invoke_counterevidence_policy: 'Diagnose the failed check',
    request_operating_domain_evidence: 'Obtain evidence for the operating range',
    request_qualified_parameters_or_other_qualified_model: 'Obtain qualified parameters or review another supported model',
    request_explicit_assumptions_or_model_review: 'State assumptions and review the model',
    reject_parameter_hypothesis_and_review_model: 'Reject the parameter assumption and review the model',
    reject_ordinary_column_and_review_alternative_routes: 'Reject the conventional single column and review alternatives',
    exclude_rejected_computed_candidates: 'Exclude failed candidates from selection',
    reconcile_conflicting_inputs_before_recomputation: 'Reconcile conflicting inputs before recalculating',
    review_reflux_or_stage_constraints: 'Review reflux or stage constraints', stop_and_review_evidence: 'Stop and review evidence',
  }
  if (!records?.length) return null
  return <section aria-label="Expert decision path">
    <h3>Expert decision path</h3>
    <p>Input criteria → hypothesis → numerical check → conclusion and next action</p>
    {records.map((r, index) => <details key={r.record_id} open={index === 0}>
      <summary>{r.gate} · {r.title} · {conclusions[r.conclusion]}{r.reused ? ' (evidence reused)' : ''}</summary>
      <p><strong>Decision basis</strong>{r.input_facts.component_order?.join(' / ')}, pressure {r.input_facts.pressure_kPa} kPa, {r.input_facts.mixture_class}</p>
      <p><strong>Hypothesis</strong>{r.hypothesis}</p>
      {!!r.model_options.length && <table aria-label="Property model candidates"><thead><tr><th>Model</th><th>Assessment</th><th>Evidence</th></tr></thead><tbody>
        {r.model_options.map(m => <tr key={m.model}><td>{m.model}</td><td>{m.eligible ? 'Eligible' : 'Excluded'}</td><td>{m.reasons.join('. ')}</td></tr>)}
      </tbody></table>}
      <p><strong>Conclusion</strong>{conclusions[r.conclusion]}. {actions[r.next_action] || r.next_action}</p>
      <p>Skill {r.skill_id} v{r.skill_version}. Evidence run {r.source_run_id}</p>
      {r.action_status === 'recommendation_only' && <p>This is a proposed next action. The updated design remains pending.</p>}
      <details><summary>Numerical checks and limitations</summary><pre>{JSON.stringify({ observations: r.observations, limitations: r.limitations, evidence: r.evidence_after }, null, 2)}</pre></details>
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
    if (!updates && missingInputs.length) { setError('Complete the design basis or load a case.'); return }
    setBusy(true); setError('')
    try {
      const res = await fetch(`${base}/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message || (updates ? 'Change the specified pressure' : 'Run the current design basis'), task_updates: updates || null }) })
      if (!res.ok) throw new Error((await res.json()).detail || 'Run failed')
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
      if (!res.ok) throw new Error('Could not load the case. Try again.')
      const basis = await res.json()
      if (missingDesignInputs(basis).length) throw new Error('The case requires more inputs before calculation.')
      await execute(basis, `Load case ${caseName} and execute the design`)
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
    <h2>Expert workflow and numerical evidence</h2>
    {onOpenTopology && <button onClick={onOpenTopology}>Open autonomous flowsheet design</button>}
    {!!missingInputs.length && <section aria-label="Complete the design basis">
      <h3>Complete the design basis to start the calculation</h3>
      <ul>{missingInputs.map(m => <li key={m}>{m}</li>)}</ul>
      <p>{currentBasis.process_family ? 'Supply sourced extraction feed data after acid and ammonia removal.' : 'Enter a complete task in the chat or run one of the cases below.'}</p>
      {!currentBasis.process_family && <><button disabled={running} onClick={() => loadCaseAndRun('water_ethanol')}>Run the ethanol/water case</button>
      <button disabled={running} onClick={() => loadCaseAndRun('heptane_nonane')}>Run the n-heptane/n-nonane case</button></>}
    </section>}
    <button disabled={running || missingInputs.length > 0} onClick={() => execute()}>Run submitted design</button>
    {running && <p role="status">Running the calculation…</p>}
    <label>Update pressure (kPa)<input aria-label="Pressure (kPa)" type="number" min="0.001" value={pressure} onChange={e => setPressure(e.target.value)} /></label>
    <button disabled={running || missingInputs.length > 0 || !pressure || Number(pressure) <= 0} onClick={() => execute(currentBasis.process_family ? { extraction_pressure_Pa: Number(pressure) * 1000 } : { feed: { pressure_kPa: Number(pressure) } })}>Run revision</button>
    {error && <p role="alert">{String(error)}</p>}
    {!run ? <p>Run the design to see calculated results.</p> : <>
      <p>Revision {run.revision} · {run.status} · Tools {run.tool_calls} calls / LLM {run.llm_calls} calls</p>
      <p>Invalidated stages {run.invalidated_gates?.join(', ') || (currentBasis.process_family ? 'Full recalculation for integrated flowsheets' : 'Initial run')}. Reused evidence {run.reused_artifact_ids?.length || 0} records</p>
      {currentBasis.process_family ? <section aria-label="Integrated process decision path"><h3>Expert decisions and checks</h3>{run.expert_records?.map((r, i) => <p key={i}>{r.gate} · {r.owner} · {r.skill_id} · {r.status}</p>)}</section> : <ExpertDecisionPath records={run.expert_records} />}
      {run.artifacts?.explore_extraction_candidates?.status === 'success' && <section aria-label="Calculated extraction candidates"><h3>Extraction section candidates</h3><table><thead><tr><th>Candidate</th><th>Contact stages</th><th>S/F mass ratio</th><th>Extraction recovery</th><th>Status</th></tr></thead><tbody>{run.artifacts.explore_extraction_candidates.data.candidates.map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.stages}</td><td>{c.solvent_feed_mass_ratio}</td><td>{c.raw ? `${(100 * c.raw.solute_extraction_recovery).toFixed(4)}%` : 'No accepted result'}</td><td>{c.status}</td></tr>)}</tbody></table><p>These values apply to the isothermal extraction section. Full-process recovery, energy balance, and solvent recycle require further verification.</p></section>}
      <table aria-label="Workflow stage status"><thead><tr><th>Stage</th><th>Status</th><th>Details</th></tr></thead><tbody>
        {Object.values(run.gates).map(g => <tr key={g.gate}><td>{g.gate}</td><td>{g.status}</td><td>{g.gate === 'G0' && g.status === 'needs_input' && missingInputs.length ? missingInputs.join('. ') : g.reason}</td></tr>)}
      </tbody></table>
      {balance?.status === 'success' && balance.validation.passed && <><h3>Verified stream flows (kmol/h)</h3><table><tbody>
        {balance.data.streams.map(s => <tr key={s.id}><th>{s.id}</th><td>{s.flow_kmol_h.toFixed(6)}</td><td>x₀={s.composition[0].toFixed(6)}</td></tr>)}
      </tbody></table></>}
      {scheme?.status === 'success' && scheme.validation.passed && <section>
        <h3>Initial constant molar overflow design</h3>
        <p>Model {run.artifacts.select_thermodynamic_model?.data.selected_model}. Reflux ratio {scheme.data.selected_reflux_ratio.toFixed(4)}</p>
        <p>{scheme.data.selection_basis}</p>
        {stages?.status === 'success' && <p>Equilibrium stages {stages.data.theoretical_stages_rounded_up}. Feed stage {stages.data.feed_stage_from_top} (counted from the top, including the partial reboiler and excluding the total condenser)</p>}
        {!!candidates?.data.candidates?.length && <table aria-label="Reflux ratio comparison"><thead><tr><th>Candidate</th><th>Reflux ratio</th><th>Equilibrium stages</th><th>Status</th></tr></thead><tbody>
          {candidates.data.candidates.map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.reflux_ratio?.toFixed(3) || '—'}</td><td>{c.theoretical_stages_rounded_up || '—'}</td><td>{c.status}</td></tr>)}
        </tbody></table>}
        <p>Stage count and internal vapor flow inform the comparison. See the report for the assumptions and optimization scope.</p>
      </section>}
      {rigorous && <section aria-label="Rigorous column verification and revision">
        <h3>DWSIM column verification and revision</h3>
        <p>Each candidate is simulated with the original product requirements and reflux constraints.</p>
        <table><thead><tr><th>Candidate</th><th>Stages / feed stage</th><th>Reflux ratio</th><th>Verification result</th></tr></thead><tbody>
          {(rigorous.data.attempts || []).map(c => <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.equilibrium_stages} / {c.feed_stage}</td><td>{c.reflux_ratio.toFixed(4)}</td><td>{c.status}</td></tr>)}
        </tbody></table>
        {rigorous.data.selected_candidate && <p>Final candidate {rigorous.data.selected_candidate.equilibrium_stages} equilibrium stages, feed stage {rigorous.data.selected_candidate.feed_stage}. The original product specifications passed.</p>}
      </section>}
      {energy?.status === 'success' && energy.validation.passed && <section aria-label="Energy and equipment estimates">
        <h3>Energy and preliminary equipment</h3>
        <p>Condenser duty {energy.data.condenser_duty_kW.toFixed(2)} kW. Reboiler duty {energy.data.reboiler_duty_kW.toFixed(2)} kW. Relative energy residual {energy.data.relative_residual.toExponential(2)}.</p>
        {equipment?.validation.passed && <p>Estimated diameter {equipment.data.diameter_m.toFixed(2)} m. Estimated overall efficiency {(equipment.data.overall_efficiency_estimate * 100).toFixed(1)}%. Estimated tray count {equipment.data.actual_trays_estimate}. Active height {equipment.data.active_height_m.toFixed(2)} m.</p>}
          {auxiliary?.validation.passed && <p>Estimated condenser area {auxiliary.data.condenser.area_m2.toFixed(2)} m². Estimated reboiler area {auxiliary.data.reboiler.area_m2.toFixed(2)} m². See the export for heat-transfer, piping, and geometry assumptions.</p>}
          {auxiliary?.validation.passed && auxiliary.data.feed_pump?.feed_heater && <p>
            Cold feed pump {auxiliary.data.feed_pump.flow_m3_h.toFixed(2)} m³/h, required head {auxiliary.data.feed_pump.required_head_m.toFixed(2)} m, shaft power {auxiliary.data.feed_pump.shaft_power_kW.toFixed(3)} kW, NPSHa {auxiliary.data.feed_pump.NPSH_available_m.toFixed(2)} m.
            Feed preheat duty {auxiliary.data.feed_pump.feed_heater.duty_kW.toFixed(2)} kW. Pump selection requires the vendor model and NPSHr data.
          </p>}
        <p>Weeping, entrainment, pressure-drop feedback, and vendor performance require further checks. The estimate uses overall tray efficiency.</p>
      </section>}
      {vle?.status === 'success' && vle.validation.passed && <PhasePlot points={vle.data.points} />}
      {equipment?.validation.passed && <ValveDesign data={equipment.data} />}
      <h3>Export run results</h3>
      {['json', 'csv', 'md'].map(format => <a className="engineering-export" key={format} href={`${base}/export/${format}`}>{format.toUpperCase()}</a>)}
      <details><summary>Decisions and references</summary><pre>{JSON.stringify(run.decisions, null, 2)}</pre></details>
      <p>G8 verifies the calculations in scope. See each stage for the review status of energy, equipment, and hydraulics.</p>
    </>}
  </aside>
}
