import React, { useCallback, useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'
import InputPanel from './components/InputPanel.jsx'
import Pipeline from './components/Pipeline.jsx'
import KpiStrip from './components/KpiStrip.jsx'
import IdeaView from './components/IdeaView.jsx'
import CodeView from './components/CodeView.jsx'
import Followup from './components/Followup.jsx'
import { CODE_AGENTS, IDEA_AGENTS, buildExportMarkdown, getAgentActionDescription } from './data.js'
import {
  downloadMarkdown, fetchHealth, fetchSampleRepoPath,
  inspectRepoRequest, runQuery, sendFollowupRequest,
} from './api.js'

const delay = (ms) => new Promise((r) => setTimeout(r, ms))

function emptyPillarState() {
  return {
    prompt: '',
    session: null,
    steps: [],
    nodes: ['waiting', 'waiting', 'waiting', 'waiting'],
    loader: null,
    statusText: 'Ready to review',
    statusClass: 'text-zinc-200 font-semibold',
    finalElapsed: '(0.0s)',
    hasOutput: false,
    isRunning: false,
    runError: null,
    messages: [],
    thinkingStart: null,
    sendError: '',
  }
}

function TimerDisplay({ startTime, finalText, running }) {
  const [text, setText] = useState('(0.0s)')
  useEffect(() => {
    if (!running || !startTime) return undefined
    setText('(0.0s)')
    const id = setInterval(() => {
      setText(`(${(Date.now() - startTime) / 1000 > 0 ? ((Date.now() - startTime) / 1000).toFixed(1) : '0.0'}s)`)
    }, 100)
    return () => clearInterval(id)
  }, [running, startTime])
  return <span className="ml-2 text-zinc-500">{running ? text : finalText}</span>
}

export default function App() {
  const [pillar, setPillar] = useState('idea')
  const [pillars, setPillars] = useState({ idea: emptyPillarState(), code: emptyPillarState() })
  const [repoPath, setRepoPath] = useState('')
  const [repoBadge, setRepoBadge] = useState({ visible: false, className: '', text: '' })
  const [inspecting, setInspecting] = useState(false)
  const [errorHint, setErrorHint] = useState('')
  const [runBusy, setRunBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)
  const [health, setHealth] = useState({ text: 'AI engine ready', className: 'text-zinc-400' })

  const runStartRef = useRef({ idea: null, code: null })
  const runIdRef = useRef({ idea: 0, code: 0 })

  const ps = pillars[pillar]
  const agents = pillar === 'idea' ? IDEA_AGENTS : CODE_AGENTS
  const out = ps.session?.final_output || null

  const patchPillar = useCallback((name, patch) => {
    setPillars((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }))
  }, [])

  /* ---------------- health ---------------- */
  useEffect(() => {
    let alive = true
    async function refresh() {
      try {
        const data = await fetchHealth()
        if (!alive || !data) return
        const rl = data.rate_limits || {}
        if (rl.all_rate_limited) {
          setHealth({ text: 'AI engine resting (free tier limit reached)', className: 'text-rose-300' })
        } else if (Object.keys(rl.cooldowns || {}).length > 0) {
          setHealth({ text: 'One model is resting, another is answering', className: 'text-amber-300' })
        } else {
          setHealth({ text: 'AI engine ready', className: 'text-zinc-400' })
        }
      } catch { /* best-effort */ }
    }
    refresh()
    const id = setInterval(refresh, 30000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  /* ---------------- repo ---------------- */
  async function loadSampleRepo() {
    try {
      const data = await fetchSampleRepoPath()
      setRepoPath(data.path)
      inspectRepo(data.path)
    } catch (e) {
      console.error(e)
    }
  }

  async function inspectRepo(forcedPath) {
    const target = (forcedPath ?? repoPath).trim()
    if (!target) return
    setInspecting(true)
    setRepoBadge({ visible: true, className: 'text-blue-400 text-xs px-2 py-1 bg-surface rounded border border-blue-900/60', text: target.startsWith('http') ? 'Cloning GitHub repo & indexing AST...' : 'Scanning AST...' })
    try {
      const data = await inspectRepoRequest(target)
      if (data.status === 'ok') {
        const filesCount = data.summary ? data.summary.total_files : 0
        const chunksCount = data.summary ? data.summary.total_chunks : 0
        const label = data.is_remote ? `GitHub: ${data.repo_name || 'Cloned'}` : 'Local'
        setRepoBadge({ visible: true, className: 'text-emerald-400 text-xs px-2 py-1 bg-surface rounded border border-emerald-900/60', text: `${filesCount} files, ${chunksCount} functions scanned (${label})` })
        setPillars((prev) => ({
          ...prev,
          code: {
            ...prev.code, session: null, steps: [], messages: [], hasOutput: false, runError: null,
            statusText: `Scanned ${filesCount} files - ready to review`, statusClass: 'text-emerald-400 font-semibold',
          },
        }))
      } else {
        setRepoBadge({ visible: true, className: 'text-rose-400 text-xs px-2 py-1 bg-surface rounded border border-rose-900/60', text: data.message || 'Failed to scan repository.' })
      }
    } catch {
      setRepoBadge({ visible: true, className: 'text-rose-400 text-xs px-2 py-1 bg-surface rounded border border-rose-900/60', text: 'Connection error while scanning repo.' })
    } finally {
      setInspecting(false)
    }
  }

  /* ---------------- workflow ---------------- */
  async function executeWorkflow() {
    const thisPillar = pillar
    const query = pillars[thisPillar].prompt.trim()
    if (!query) {
      setErrorHint('Describe your idea or paste an error first, then run the pipeline.')
      setTimeout(() => setErrorHint(''), 3200)
      return
    }
    setRunBusy(true)
    const runId = ++runIdRef.current[thisPillar]
    runStartRef.current[thisPillar] = Date.now()
    setPillars((prev) => ({
      ...prev,
      [thisPillar]: {
        ...prev[thisPillar], steps: [], messages: [], runError: null, hasOutput: false,
        isRunning: true, nodes: ['working', 'waiting', 'waiting', 'waiting'],
        statusText: 'Review in progress', statusClass: 'text-blue-400 font-semibold',
      },
    }))

    const abortController = new AbortController()
    const timeoutId = setTimeout(() => {
      abortController.abort(new Error('Request timed out after 150 seconds. The free-tier engine may be rate-limited; please retry.'))
    }, 150000)
    const startTime = Date.now()

    const alive = () => runIdRef.current[thisPillar] === runId

    try {
      const state = await runQuery({
        query,
        repoPath: repoPath.trim(),
        forceIntent: thisPillar === 'idea' ? 'idea_validation' : 'codebase_analysis',
        signal: abortController.signal,
      })
      clearTimeout(timeoutId)
      if (!alive()) return

      const traces = state.execution_trace || []
      const agentSteps = traces.filter((t) => t.details && (t.details.thinking || t.details.findings))
      const currentAgents = thisPillar === 'idea' ? IDEA_AGENTS : CODE_AGENTS

      for (let i = 0; i < agentSteps.length; i++) {
        if (!alive()) return
        const step = agentSteps[i]
        const nodeIdx = Math.min(i, currentAgents.length - 1)
        setPillars((prev) => {
          const nodes = [...prev[thisPillar].nodes]
          nodes[nodeIdx] = 'working'
          return { ...prev, [thisPillar]: { ...prev[thisPillar], nodes, loader: { step, idx: i, actionText: getAgentActionDescription(step.agent_name, i) } } }
        })
        await delay(650)
        if (!alive()) return
        setPillars((prev) => {
          const nodes = [...prev[thisPillar].nodes]
          nodes[nodeIdx] = 'done'
          return { ...prev, [thisPillar]: { ...prev[thisPillar], nodes, loader: null, steps: [...prev[thisPillar].steps, { step, idx: i }] } }
        })
        await delay(600)
      }

      if (!alive()) return
      const elapsed = `(${((Date.now() - startTime) / 1000).toFixed(1)}s)`
      setPillars((prev) => ({
        ...prev,
        [thisPillar]: {
          ...prev[thisPillar], session: state, isRunning: false, hasOutput: true,
          nodes: ['done', 'done', 'done', 'done'], finalElapsed: elapsed,
          statusText: 'Review complete', statusClass: 'text-emerald-400 font-semibold',
        },
      }))
      document.getElementById('outputArea')?.scrollIntoView({ behavior: 'smooth' })
    } catch (err) {
      clearTimeout(timeoutId)
      if (!alive()) return
      const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1)
      setPillars((prev) => {
        const nodes = [...prev[thisPillar].nodes]
        const activeIdx = nodes.findIndex((n) => n === 'working')
        if (activeIdx >= 0) nodes[activeIdx] = 'error'
        return {
          ...prev,
          [thisPillar]: {
            ...prev[thisPillar], isRunning: false, loader: null, nodes,
            finalElapsed: `(${elapsedSec}s - Stopped)`,
            statusText: 'Stopped: something went wrong', statusClass: 'text-rose-400 font-semibold',
            runError: { message: err.message || String(err), onRetry: () => executeWorkflow() },
          },
        }
      })
    } finally {
      if (alive()) setRunBusy(false)
    }
  }

  /* ---------------- follow-up ---------------- */
  async function handleSendFollowup(query) {
    const thisPillar = pillar
    const session = pillars[thisPillar].session
    const mentionMatch = query.match(/^@([a-zA-Z_-]+)\b/)
    const mentionLabel = mentionMatch ? mentionMatch[1] : null

    setPillars((prev) => ({
      ...prev,
      [thisPillar]: {
        ...prev[thisPillar],
        messages: [...prev[thisPillar].messages, { kind: 'user', text: query, mention: mentionLabel }],
        thinkingStart: Date.now(),
        sendError: '',
      },
    }))
    setSending(true)

    try {
      const minDelay = delay(600)
      const data = await sendFollowupRequest({
        query,
        context: session ? session.final_output : null,
        sessionId: session ? session.session_id : null,
        repoPath: repoPath.trim() || null,
      })
      await minDelay
      setPillars((prev) => ({
        ...prev,
        [thisPillar]: {
          ...prev[thisPillar],
          thinkingStart: null,
          messages: [...prev[thisPillar].messages, {
            kind: 'agent',
            agentName: data.agent_name || 'Technical Co-Pilot',
            actionTaken: data.action_taken || 'Response',
            directAgent: data.direct_agent || '',
            html: data.answer || '',
            symbols: data.referenced_symbols || [],
            files: data.referenced_files || [],
          }],
        },
      }))
    } catch (err) {
      const msg = err && err.message ? err.message : String(err)
      const isRateLimit = /rate.?limit|429|cooldown|exhausted/i.test(msg)
      setPillars((prev) => ({
        ...prev,
        [thisPillar]: {
          ...prev[thisPillar],
          thinkingStart: null,
          messages: [...prev[thisPillar].messages, { kind: 'error', text: msg, rateLimited: isRateLimit }],
        },
      }))
    } finally {
      setSending(false)
    }
  }

  /* ---------------- export ---------------- */
  function handleExport() {
    const session = pillars[pillar].session
    if (!session?.final_output) return
    const { filename, md } = buildExportMarkdown(session)
    downloadMarkdown(filename, md)
  }

  /* ---------------- metrics ---------------- */
  const metrics = (() => {
    if (!out) return { track: 'Pending', latency: '0 seconds', agents: '4 of 4', diagrams: '3' }
    const seconds = (((ps.session.total_latency_ms || 0) / 1000).toFixed(1))
    let track = 'Reviewed'
    if (out.feasibility_score !== undefined) track = `${out.feasibility_score} / 100`
    else if (ps.session.intent === 'codebase_analysis') track = `${(out.candidates || []).length} findings`
    const prd = out.prd || {}
    const diagrams = ['architecture_diagram_mermaid', 'component_diagram_mermaid', 'dataflow_diagram_mermaid']
      .filter((k) => typeof prd[k] === 'string' && prd[k].trim()).length
    const agentCount = (ps.session.execution_trace || []).filter((t) => t.details && (t.details.thinking || t.details.findings)).length
    return {
      track,
      latency: `${seconds} seconds`,
      agents: agentCount > 0 ? `${agentCount} agents` : '4 agents',
      diagrams: diagrams > 0 ? `${diagrams} diagrams` : 'Not applicable',
    }
  })()

  const trace = ps.session?.execution_trace || []

  return (
    <div className="min-h-screen flex flex-col font-sans selection:bg-blue-900 selection:text-white bg-canvas text-slate-100">
      <Header health={health} canExport={ps.hasOutput && !!out} onExport={handleExport} />

      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-10 space-y-12">
        <InputPanel
          pillar={pillar}
          onSelectPillar={setPillar}
          prompt={ps.prompt}
          onPromptChange={(v) => patchPillar(pillar, { prompt: v })}
          repoPath={repoPath}
          onRepoPathChange={setRepoPath}
          repoBadge={repoBadge}
          onLoadSample={loadSampleRepo}
          onInspectRepo={() => inspectRepo()}
          inspecting={inspecting}
          errorHint={errorHint}
          running={runBusy}
          onRun={executeWorkflow}
        />

        <Pipeline
          agents={agents}
          nodeStates={ps.nodes}
          steps={ps.steps}
          loader={ps.loader}
          statusText={ps.statusText}
          statusClass={ps.statusText ? ps.statusClass : 'text-zinc-200 font-semibold'}
          timerText={<TimerDisplay startTime={runStartRef.current[pillar]} finalText={ps.finalElapsed} running={ps.isRunning} />}
          trace={trace}
          traceOpen={traceOpen}
          onToggleTrace={() => setTraceOpen((v) => !v)}
          error={ps.runError}
        />

        <section id="outputArea" className={ps.hasOutput && out ? 'space-y-12' : 'hidden space-y-12'}>
          <KpiStrip track={metrics.track} latency={metrics.latency} agents={metrics.agents} diagrams={metrics.diagrams} />
          {pillar === 'idea' ? <IdeaView out={out || {}} /> : <CodeView out={out || {}} />}
          <Followup
            pillar={pillar}
            messages={ps.messages}
            thinkingStart={ps.thinkingStart}
            sendError={ps.sendError}
            onSend={handleSendFollowup}
            sending={sending}
          />
        </section>
      </main>

      <Footer />
    </div>
  )
}
