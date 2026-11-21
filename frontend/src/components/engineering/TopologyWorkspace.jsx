import React, { useEffect, useState } from 'react'
import './topology.css'

const API = '/api/engineering/topology'
const STORAGE_KEY = 'sepmind_topology_run'
const STATUS = { ready: '等待执行', running: '正在综合与计算', passed: '数值验收通过', failed: '搜索结束，候选未通过验收', blocked: '运行已阻断' }

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
      <h1>SepMind · 自主流程设计</h1>
      <p>提供原料与产品要求，由Agent提出单元数量、连接和设计假设，再执行DWSIM与独立数值审查。</p>
      <p className="topology-scope">支持三至五组分理想物系，以及D02–D04原二元案例声明物性下的无环精馏流程。任务保留原料、产品要求、模型假设和搜索预算。</p>
    </header>
    <div className="topology-grid">
      <section className="topology-basis" aria-labelledby="topology-input-heading">
        <h2 id="topology-input-heading">设计依据</h2>
        <label htmlFor="topology-case">自主设计案例</label>
        <select id="topology-case" value={exampleCase} disabled={active || submitting} onChange={event => {
          setExampleCase(event.target.value); loadExample(event.target.value)
        }}>
          <option value="ternary">苯／甲苯／乙苯三组分示例</option>
          <option value="D02">D02 · 苯／甲苯，36 wt%苯</option>
          <option value="D03">D03 · 乙醇／水，48 wt%乙醇</option>
          <option value="D04">D04 · 甲醇／水，40 wt%甲醇</option>
        </select>
        <button onClick={() => loadExample()} disabled={active || submitting}>载入所选任务</button>
        <label htmlFor="topology-basis">任务JSON</label>
        <textarea id="topology-basis" value={basis} onChange={event => setBasis(event.target.value)} disabled={active || submitting} spellCheck={false} />
        <label htmlFor="topology-provider">LLM提供商</label>
        <select id="topology-provider" value={provider} onChange={event => setProvider(event.target.value)} disabled={active || submitting}>
          <option value="deepseek">DeepSeek</option><option value="qwen">Qwen</option>
        </select>
        <div className="topology-actions">
          <button className="topology-primary" onClick={start} disabled={!basis || active || submitting}>{submitting ? '正在提交' : '开始自主拓扑综合'}</button>
          {active && <button onClick={stop} disabled={stopRequested}>{stopRequested ? '已请求停止' : '停止运行'}</button>}
        </div>
        {stopRequested && active && <p role="status">正在等待当前有界原生调用结束，随后停止后续步骤。</p>}
        {error && <p className="topology-error" role="alert">{error}</p>}
      </section>
      <section className="topology-results" aria-labelledby="topology-results-heading">
        <h2 id="topology-results-heading">生成与验证</h2>
        {!run && <p>提交任务后，这里显示候选连接、实际计算和验收结果。</p>}
        {run && <>
          <p className={`topology-status ${run.status}`} role="status">{STATUS[run.status] || run.status}</p>
          <p className="topology-run-id">运行 {run.run_id}</p>
          <dl className="topology-counts">
            <div><dt>LLM请求</dt><dd>{run.llm_calls}</dd></div>
            <div><dt>原生调用</dt><dd>{run.native_calls}</dd></div>
            <div><dt>阶段工具</dt><dd>{run.tool_calls}</dd></div>
          </dl>
          <p>已验证拓扑 {verifiedTopologies} 个，搜索目标 {run.basis?.budget?.desired_verified_topologies ?? '—'} 个。</p>
          {run.report_markdown && run.graph && <img className="topology-pfd" src={`${API}/runs/${runId}/export/svg`} alt="本次Agent生成的流程图，数值验收状态见运行状态" />}
          {selected?.review?.targets && <div className="topology-table-wrap"><table>
            <caption>原始产品要求验收</caption>
            <thead><tr><th>产品</th><th>组分</th><th>摩尔纯度</th><th>目标</th><th>回收率</th><th>目标</th></tr></thead>
            <tbody>{selected.review.targets.map(target => <tr key={target.product_id}>
              <td>{target.product_id}</td><td>{target.component}</td><td>{target.mole_fraction.toFixed(8)}</td><td>{target.required_mole_fraction > 0 ? `≥${target.required_mole_fraction}` : '未单独规定'}</td>
              <td>{target.recovery.toFixed(8)}</td><td>{target.required_recovery > 0 ? `≥${target.required_recovery}` : '未单独规定'}</td>
            </tr>)}</tbody>
          </table></div>}
          {!!run.candidates?.length && <div className="topology-table-wrap"><table className="topology-candidates">
            <caption>候选与修订记录</caption>
            <thead><tr><th>候选</th><th>塔数量</th><th>变更类型</th><th>结果</th></tr></thead>
            <tbody>{run.candidates.map(candidate => <tr key={candidate.candidate_id}>
              <td>{candidate.candidate_id}</td><td>{candidate.graph?.columns?.length ?? '—'}</td>
              <td>{candidate.change_kind === 'new_topology' ? '新拓扑' : candidate.change_kind === 'parameter_revision' ? '参数修订' : '提案待修正'}</td>
              <td>{candidate.status === 'passed' ? '通过' : candidate.status === 'running' ? '正在执行' : candidate.error ?
                <details><summary>执行或决策失败</summary><pre>{candidate.error}</pre></details> : '产品指标未通过'}</td>
            </tr>)}</tbody>
          </table></div>}
          {!!run.decisions?.length && <details><summary>专家公开决策与证据</summary>
            {run.decisions.map((decision, index) => <article key={index}><h3>{decision.role}</h3>
              <p>{decision.rationale || decision.observation}</p><p>{decision.recommendation}</p>
              <p className="topology-run-id">{decision.evidence_ids?.join(', ')}</p></article>)}
          </details>}
          {run.questions?.map((question, index) => <p className="topology-error" key={index}>{question}</p>)}
          {run.report_markdown && <nav className="topology-downloads" aria-label="本次运行导出">
            <a href={`/?topology_run=${encodeURIComponent(runId)}`}>运行链接</a>
            {['json', 'md', ...(run.graph ? ['svg', 'mmd'] : [])].map(format => <a key={format} href={`${API}/runs/${runId}/export/${format}`} download>{format.toUpperCase()}</a>)}
          </nav>}
        </>}
      </section>
    </div>
  </main>
}
