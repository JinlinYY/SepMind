import React, { useState, useEffect } from 'react'
import ChatInterface from './components/ChatInterface'
import { EngineeringStart, EngineeringPanel } from './components/engineering/EngineeringWorkspace'
import TopologyWorkspace from './components/engineering/TopologyWorkspace'
import './App.css'

// API base URL - use proxy in dev
const API_BASE = '/api'
const ACTIVE_SESSION_KEY = 'sepmind_active_session'
const LEGACY_SESSION_KEY = 'pha_active_session'
const INITIAL_TOPOLOGY_RUN = new URLSearchParams(window.location.search).get('topology_run')

function App() {
  const [config, setConfig] = useState(null)
  const [session, setSession] = useState(null)
  const [userId, setUserId] = useState('test')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [workspace, setWorkspace] = useState(INITIAL_TOPOLOGY_RUN ? 'topology' : 'engineering')

  // Fetch configuration on mount
  useEffect(() => {
    fetchConfig()
  }, [])

  const clearActiveSession = () => {
    localStorage.removeItem(ACTIVE_SESSION_KEY)
    localStorage.removeItem(LEGACY_SESSION_KEY)
  }

  const saveActiveSession = (sessionData, activeUserId) => {
    const payload = {
      session_id: sessionData.session_id,
      user_id: activeUserId || sessionData?.config?.user_id || 'test',
    }
    localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(payload))
  }

  const restoreSession = async (latestConfig) => {
    const raw = localStorage.getItem(ACTIVE_SESSION_KEY) || localStorage.getItem(LEGACY_SESSION_KEY)
    if (!raw) return false

    let storedSession
    try {
      storedSession = JSON.parse(raw)
    } catch {
      clearActiveSession()
      return false
    }

    if (!storedSession?.session_id) {
      clearActiveSession()
      return false
    }

    try {
      const res = await fetch(`${API_BASE}/sessions/${storedSession.session_id}`)
      if (!res.ok) throw new Error('Stored session is unavailable')
      const restoredState = await res.json()

      // Validate that the restored session's model is still in the curated list
      // for its provider. If it isn't (because we updated the curated set since
      // the session was created), drop the session and force the user back to
      // the splash screen — otherwise they'd be silently using a stale model.
      const restoredProvider = restoredState.config?.provider
      const restoredModel = restoredState.config?.model_id
      const cfg = latestConfig || config
      const providerModels = (restoredProvider && cfg?.models?.[restoredProvider]) || []
      const restoredModelExists = providerModels.some(m => m.id === restoredModel)
      if (restoredState.config?.workspace !== 'engineering') {
        clearActiveSession()
        return false
      }

      setSession({
        session_id: restoredState.session_id,
        config: restoredState.config,
        created_at: restoredState.created_at,
        status: restoredState.status,
      })
      setUserId(restoredState.config?.user_id || storedSession.user_id || 'test')
      saveActiveSession(restoredState, storedSession.user_id)
      localStorage.removeItem(LEGACY_SESSION_KEY)
      setWorkspace(INITIAL_TOPOLOGY_RUN ? 'topology' : 'engineering')
      return true
    } catch {
      clearActiveSession()
      return false
    }
  }

  const fetchConfig = async () => {
    try {
      setLoading(true)
      const res = await fetch(`${API_BASE}/config`)
      if (!res.ok) throw new Error('Failed to fetch config')
      const data = await res.json()
      setConfig(data)
      await restoreSession(data)
      setLoading(false)
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  const createSession = async (sessionConfig) => {
    try {
      setLoading(true)
      // Extract userId from sessionConfig and save it
      if (sessionConfig.user_id) {
        setUserId(sessionConfig.user_id)
      }
      const res = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sessionConfig),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to create session')
      }
      const data = await res.json()
      setSession(data)
      saveActiveSession(data, sessionConfig.user_id)
      setLoading(false)
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  const endSession = async () => {
    if (session) {
      try {
        await fetch(`${API_BASE}/sessions/${session.session_id}`, {
          method: 'DELETE',
        })
      } catch (err) {
        console.error('Error ending session:', err)
      }
    }
    setSession(null)
    clearActiveSession()
  }

  const handleRefresh = async () => {
    if (!session) return

    let sessionConfig = session.config
    let recreating = false
    setError(null)
    setLoading(true)

    try {
      if (sessionConfig.workspace === 'engineering') {
        const current = await fetch(`${API_BASE}/engineering/sessions/${session.session_id}/state`)
        if (!current.ok) throw new Error('无法读取当前设计依据，原会话已保留，请稍后重试')
        const state = await current.json()
        const basis = state.design_basis || state.run?.basis
        if (basis) sessionConfig = { ...sessionConfig, engineering_basis: basis }
      }
      recreating = true
      try {
        await fetch(`${API_BASE}/sessions/${session.session_id}`, {
          method: 'DELETE',
        })
      } catch (err) {
        console.error('Error ending session during refresh:', err)
      }

      clearActiveSession()

      const res = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sessionConfig),
      })
      if (!res.ok) {
        let detail = 'Failed to refresh session'
        try {
          const errData = await res.json()
          detail = errData.detail || detail
        } catch {
          // Keep default detail if response is not JSON.
        }
        throw new Error(detail)
      }

      const data = await res.json()
      setSession(data)
      setUserId(sessionConfig.user_id || data?.config?.user_id || 'test')
      saveActiveSession(data, sessionConfig.user_id)
    } catch (err) {
      if (recreating) {
        setSession(null)
        clearActiveSession()
      }
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Loading state
  if (loading && !config) {
    return (
      <div className="app-loading">
        <div className="spinner"></div>
        <p>正在加载SepMind分离设计…</p>
      </div>
    )
  }

  // Error state
  if (error && !config) {
    return (
      <div className="app-error">
        <h2>⚠️ Connection Error</h2>
        <p>{error}</p>
        <p className="hint">请在 SepMind 仓库根目录启动后端。</p>
        <code>python -m uvicorn api.main:app --host 127.0.0.1 --port 8000</code>
        <button onClick={() => { setError(null); fetchConfig(); }}>
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="app">
      {(!session || workspace === 'topology') && <nav className="workspace-choice" aria-label="工作区">
        <button onClick={() => { setWorkspace('engineering'); setError(null) }}>既定拓扑设计</button>
        <button onClick={() => { setWorkspace('topology'); setError(null) }}>自主流程设计</button>
      </nav>}
      {workspace === 'topology' ? <TopologyWorkspace initialRunId={INITIAL_TOPOLOGY_RUN} /> : !session ? (
        <EngineeringStart onStart={createSession} loading={loading} error={error} />
      ) : (
        <div className={session.config?.workspace === 'engineering' ? 'engineering-workspace' : undefined}>
        <ChatInterface
          session={session}
          apiBase={API_BASE}
          onEndSession={endSession}
          onRefresh={handleRefresh}
          refreshing={loading}
          userId={userId}
        />
        {session.config?.workspace === 'engineering' && <EngineeringPanel session={session} onOpenTopology={() => setWorkspace('topology')} />}
        </div>
      )}
    </div>
  )
}

export default App
