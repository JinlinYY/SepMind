import React, { useEffect, useState } from 'react'
import './topology.css'

const API = '/api/engineering/topology'
const STORAGE_KEY = 'sepmind_topology_run'
const STATUS = { ready: 'Ready', running: 'Generating and evaluating candidates', passed: 'Verified', failed: 'Search completed with no verified candidate', blocked: 'Blocked' }

async function jsonResponse(response) {
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail || value))
  return value
}

export default function TopologyWorkspace({ initialRunId }) {
  const [basis, setBasis] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [exampleCase, setExampleCase] = useState('ternary')
  const [runId, setRunId] = useState(() => initialRunId || localStorage.getItem(STORAGE_KEY) || '')
  const [run, setRun] = useState(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [stopRequested, setStopRequested] = useState(false)

  const loadExample = async (caseId = exampleCase) => {
    try {
      const example = await jsonResponse(await fetch(`${API}/example?case=${caseId}`))
      setBasis(JSON.stringify(example, null, 2))
      setError('')
    } catch (exception) { setError(exception.message) }
  }

  useEffect(() => { if (!runId) loadExample() }, [])
  useEffect(() => {
    if (!runId) return
    let cancelled = false
    let timer
    const controller = new AbortController()
    const poll = async () => {
      try {
        const next = await jsonResponse(await fetch(`${API}/runs/${runId}`, { signal: controller.signal }))
        if (cancelled) return
        setRun(next)
        setBasis(JSON.stringify(next.basis, null, 2))
        setExampleCase(['D02', 'D03', 'D04'].find(caseId => next.basis.design_id.startsWith(caseId+'-')) || 'ternary')
        localStorage.setItem(STORAGE_KEY, next.run_id)
        if (next.status === 'ready' || next.status === 'running') timer = setTimeout(poll, 1200)
      } catch (exception) {
        if (!cancelled && exception.name !== 'AbortError') setError(exception.message)
      }
    }
    poll()
    return () => { cancelled = true; controller.abort(); clearTimeout(timer) }
  }, [runId])

  const active = run && ['ready', 'running'].includes(run.status)
  const start = async () => {
    setSubmitting(true)
    setError('')
    try {
      const parsed = JSON.parse(basis)
      const next = await jsonResponse(await fetch(`${API}/runs`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ basis: parsed, provider }),
      }))
      setRun(null)
      setStopRequested(false)
      localStorage.setItem(STORAGE_KEY, next.run_id)
      setRunId(next.run_id)
    } catch (exception) { setError(exception.message) }
    finally { setSubmitting(false) }
  }

  const stop = async () => {
    try {
      await jsonResponse(await fetch(`${API}/runs/${runId}/stop`, { method: 'POST' }))
      setStopRequested(true)
    } catch (exception) { setError(exception.message) }
  }

  const selected = run?.candidates?.find(candidate => candidate.candidate_id === run.accepted_candidate_id)
  const verifiedTopologies = new Set((run?.candidates || []).filter(candidate => candidate.status === 'passed').map(candidate => candidate.topology_signature)).size
  return <main className="topology-workspace">
    <header>
      <h1>SepMind · Autonomous flowsheet design</h1>
      <p>Enter the feed and product requirements. SepMind proposes units, connections, and design assumptions, then runs DWSIM and independently reviews the numerical results.</p>
      <p className="topology-scope">Supports acyclic distillation flowsheets for three- to five-component ideal mixtures and binary cases under their declared property assumptions. Each task records the feed, product requirements, property assumptions, and search budget.</p>
    </header>
    <div className="topology-grid">
      <section className="topology-basis" aria-labelledby="topology-input-heading">
        <h2 id="topology-input-heading">Design basis</h2>
        <label htmlFor="topology-case">Autonomous design case</label>
        <select id="topology-case" value={exampleCase} disabled={active || submitting} onChange={event => {
          setExampleCase(event.target.value); loadExample(event.target.value)
        }}>
          <option value="ternary">Benzene/toluene/ethylbenzene example</option>
          <option value="D02">D02 · Benzene/toluene, 36 wt% benzene</option>
          <option value="D03">D03 · Ethanol/water, 48 wt% ethanol</option>
          <option value="D04">D04 · Methanol/water, 40 wt% methanol</option>
        </select>
        <button onClick={() => loadExample()} disabled={active || submitting}>Load selected task</button>
        <label htmlFor="topology-basis">Task JSON</label>
        <textarea id="topology-basis" value={basis} onChange={event => setBasis(event.target.value)} disabled={active || submitting} spellCheck={false} />
        <label htmlFor="topology-provider">LLM provider</label>
        <select id="topology-provider" value={provider} onChange={event => setProvider(event.target.value)} disabled={active || submitting}>
          <option value="deepseek">DeepSeek</option><option value="qwen">Qwen</option>
        </select>
        <div className="topology-actions">
          <button className="topology-primary" onClick={start} disabled={!basis || active || submitting}>{submitting ? 'Submitting…' : 'Start flowsheet synthesis'}</button>
          {active && <button onClick={stop} disabled={stopRequested}>{stopRequested ? 'Stop requested' : 'Stop run'}</button>}
        </div>
        {stopRequested && active && <p role="status">The current simulator call will finish before the run stops.</p>}
        {error && <p className="topology-error" role="alert">{error}</p>}
      </section>
      <section className="topology-results" aria-labelledby="topology-results-heading">
        <h2 id="topology-results-heading">Synthesis and verification</h2>
        {!run && <p>Submit a task to see candidate connections, calculations, and verification results.</p>}
        {run && <>
          <p className={`topology-status ${run.status}`} role="status">{STATUS[run.status] || run.status}</p>
          <p className="topology-run-id">Run {run.run_id}</p>
          <dl className="topology-counts">
            <div><dt>LLM requests</dt><dd>{run.llm_calls}</dd></div>
            <div><dt>Simulator calls</dt><dd>{run.native_calls}</dd></div>
            <div><dt>Workflow tool calls</dt><dd>{run.tool_calls}</dd></div>
          </dl>
          <p>Verified topologies {verifiedTopologies}. Search target {run.basis?.budget?.desired_verified_topologies ?? '—'}.</p>
          {run.report_markdown && run.graph && <img className="topology-pfd" src={`${API}/runs/${runId}/export/svg`} alt="Generated flowsheet. See the run status for verification." />}
          {selected?.review?.targets && <div className="topology-table-wrap"><table>
            <caption>Product specification checks</caption>
            <thead><tr><th>Product</th><th>Component</th><th>Mole fraction</th><th>Target</th><th>Recovery</th><th>Target</th></tr></thead>
            <tbody>{selected.review.targets.map(target => <tr key={target.product_id}>
              <td>{target.product_id}</td><td>{target.component}</td><td>{target.mole_fraction.toFixed(8)}</td><td>{target.required_mole_fraction > 0 ? `≥${target.required_mole_fraction}` : 'Unspecified'}</td>
              <td>{target.recovery.toFixed(8)}</td><td>{target.required_recovery > 0 ? `≥${target.required_recovery}` : 'Unspecified'}</td>
            </tr>)}</tbody>
          </table></div>}
          {!!run.candidates?.length && <div className="topology-table-wrap"><table className="topology-candidates">
            <caption>Candidates and revisions</caption>
            <thead><tr><th>Candidate</th><th>Columns</th><th>Change type</th><th>Result</th></tr></thead>
            <tbody>{run.candidates.map(candidate => <tr key={candidate.candidate_id}>
              <td>{candidate.candidate_id}</td><td>{candidate.graph?.columns?.length ?? '—'}</td>
              <td>{candidate.change_kind === 'new_topology' ? 'New topology' : candidate.change_kind === 'parameter_revision' ? 'Parameter revision' : 'Proposal requires revision'}</td>
              <td>{candidate.status === 'passed' ? 'Passed' : candidate.status === 'running' ? 'Running' : candidate.error ?
                <details><summary>Execution or decision failure</summary><pre>{candidate.error}</pre></details> : 'Product specifications unmet'}</td>
            </tr>)}</tbody>
          </table></div>}
          {!!run.decisions?.length && <details><summary>Expert decisions and evidence</summary>
            {run.decisions.map((decision, index) => <article key={index}><h3>{decision.role}</h3>
              <p>{decision.rationale || decision.observation}</p><p>{decision.recommendation}</p>
              <p className="topology-run-id">{decision.evidence_ids?.join(', ')}</p></article>)}
          </details>}
          {run.questions?.map((question, index) => <p className="topology-error" key={index}>{question}</p>)}
          {run.report_markdown && <nav className="topology-downloads" aria-label="Run exports">
            <a href={`/?topology_run=${encodeURIComponent(runId)}`}>Link to run</a>
            {['json', 'md', ...(run.graph ? ['svg', 'mmd'] : [])].map(format => <a key={format} href={`${API}/runs/${runId}/export/${format}`} download>{format.toUpperCase()}</a>)}
          </nav>}
        </>}
      </section>
    </div>
  </main>
}
