import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  runQuery, sendFollowup, inspectRepo, fetchSampleRepoPath,
  fetchHealth, downloadMarkdown,
} from './api.js'

const IDEA_SAMPLES = [
  { label: 'Hostel food review app', prompt: 'A mobile app where hostel students rate mess food daily, see weekly trends, and wardens get a quality report. Who is it for and will it work?' },
  { label: 'EV charging finder', prompt: 'An app that helps EV owners in Delhi find free charging slots nearby, reserve a slot, and pay per minute. Validate the idea, list competitors and risks.' },
  { label: 'Attendance with QR', prompt: 'A QR based classroom attendance system for colleges with proxy detection and a teacher dashboard. Plan the MVP, stack and roadmap.' },
]

const CODE_SAMPLES = [
  { label: 'Traceback: ValueError', prompt: 'ValueError: invalid token in verify_token (auth/jwt_handler.py). The login endpoint returns 500 after the last change. Where is it defined and what calls it?' },
  { label: 'Where is processor?', prompt: 'Where is OrderProcessor defined, what imports it, and what is the blast radius if I change its retry logic?' },
  { label: 'Trace call flow', prompt: 'Trace the request flow from main.py into the orders processor and list unresolved external calls.' },
]

const IDEA_AGENTS = [
  { name: 'Orchestrator Agent', role: 'Intent and plan', desc: 'Classifies the goal and writes the step plan' },
  { name: 'Idea and Research Agent', role: 'Problem and market', desc: 'Extracts problem, personas, competitors' },
  { name: 'Roadmap and Risk Agent', role: 'Plan and risks', desc: 'Phases, milestones, mitigations' },
  { name: 'Critic Agent', role: 'Grounding check', desc: 'Verifies claims against evidence' },
]

const CODE_AGENTS = [
  { name: 'Orchestrator Agent', role: 'Intent and plan', desc: 'Classifies the goal and writes the step plan' },
  { name: 'Code Navigation Agent', role: 'AST search', desc: 'Symbol lookup and hybrid retrieval' },
  { name: 'Diagnosis Agent', role: 'Root cause', desc: 'Ranked hypotheses with fix direction' },
  { name: 'Critic Agent', role: 'Grounding check', desc: 'File, symbol and line verification' },
]

function verdictClass(verdict) {
  const v = String(verdict || '').toUpperCase()
  if (v.includes('GO') && !v.includes('NO')) return 'tag tag-good'
  if (v.includes('PIVOT')) return 'tag tag-warn'
  return 'tag tag-risk'
}

function severityClass(sev) {
  const s = String(sev || '').toLowerCase()
  if (s.includes('high') || s.includes('crit')) return 'tag tag-risk'
  if (s.includes('med') || s.includes('mod')) return 'tag tag-warn'
  return 'tag tag-info'
}

function useTimer(running) {
  const [elapsed, setElapsed] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    if (running) {
      const start = Date.now()
      ref.current = setInterval(() => setElapsed((Date.now() - start) / 1000), 100)
    } else {
      clearInterval(ref.current)
    }
    return () => clearInterval(ref.current)
  }, [running])
  return elapsed
}

function Header({ health, onExport, canExport }) {
  return (
    <header className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">Agentic AI Co-Pilot</h1>
          <p className="section-sub">Multi-agent RAG for idea validation and codebase analysis. Read-only, human review required.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`status-text ${health.state === 'ready' ? 'status-ready' : health.state === 'limited' ? 'status-running' : 'status-error'}`}>
            [{health.label}]
          </span>
          <button className="btn btn-quiet" onClick={onExport} disabled={!canExport}>Export report</button>
        </div>
      </div>
    </header>
  )
}

function TraceStep({ step, index }) {
  const [open, setOpen] = useState(false)
  const d = step.details || {}
  return (
    <div className="subpanel p-4">
      <button className="w-full text-left" onClick={() => setOpen((v) => !v)}>
        <div className="text-xs text-muted">Step {index + 1}</div>
        <div className="font-semibold text-white text-sm mt-1">{step.agent_name}</div>
        <div className="text-sm text-slate-300 mt-1">{step.action}</div>
        <div className="mt-2 flex flex-wrap gap-2 items-center">
          <span className="tag tag-info">{step.status}</span>
          {d.tool && <span className="tag">{d.tool}</span>}
          <span className="status-text">{step.elapsed_ms} ms</span>
        </div>
      </button>
      {open && (
        <div className="mt-3 space-y-2 text-sm">
          {d.thinking && <p className="text-slate-300">{d.thinking}</p>}
          {Array.isArray(d.findings) && d.findings.length > 0 && (
            <ul className="list-disc ml-5 text-slate-300">
              {d.findings.map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          )}
          {d.handoff && <p className="text-muted text-xs">Handoff: {d.handoff}</p>}
        </div>
      )}
    </div>
  )
}

function IdeaView({ out }) {
  if (!out || out.type === 'error') return null
  const sc = out.scorecard || {}
  const cats = sc.categories || sc.breakdown || []
  const kill = out.kill_report || {}
  const rec = out.reconciliation || {}
  const prd = out.prd || {}
  return (
    <div className="space-y-6">
      <section className="panel p-6">
        <h2 className="section-title">Executive brief</h2>
        <p className="section-sub">Problem, value, and verdict in one place</p>
        <div className="rule my-4" />
        <h3 className="font-semibold text-white">{out.project_title || 'Validated concept'}</h3>
        <p className="text-sm text-slate-300 mt-2">{out.problem_statement}</p>
        {out.core_value_prop && <p className="text-sm text-slate-300 mt-2">{out.core_value_prop}</p>}
        {(sc.total_score != null) && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-2xl font-bold text-white">{sc.total_score}/100</span>
            <span className={verdictClass(sc.verdict)}>{sc.verdict}</span>
          </div>
        )}
        {sc.verdict_summary && <p className="text-sm text-muted mt-2">{sc.verdict_summary}</p>}
      </section>

      {Array.isArray(cats) && cats.length > 0 && (
        <section className="panel p-6">
          <h2 className="section-title">Feasibility scorecard</h2>
          <p className="section-sub">Deterministic rubric, 7 categories</p>
          <div className="rule my-4" />
          <div className="grid md:grid-cols-2 gap-3">
            {cats.map((c, i) => (
              <div key={i} className="subpanel p-3">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-200">{c.name || c.category}</span>
                  <span className="text-white font-semibold">{c.score}{c.max ? `/${c.max}` : ''}</span>
                </div>
                {c.reason && <p className="text-xs text-muted mt-1">{c.reason}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel p-6">
        <h2 className="section-title">Risks and verdict</h2>
        <p className="section-sub">Bear case, flaws, preconditions</p>
        <div className="rule my-4" />
        {kill.bear_case_summary && <p className="text-sm text-slate-300">{kill.bear_case_summary}</p>}
        {Array.isArray(kill.fatal_flaws) && kill.fatal_flaws.length > 0 && (
          <div className="mt-4 space-y-2">
            {kill.fatal_flaws.map((f, i) => (
              <div key={i} className="subpanel p-3">
                <div className="flex flex-wrap gap-2 items-center">
                  <span className="font-semibold text-white text-sm">{f.title || `Flaw ${i + 1}`}</span>
                  {f.severity && <span className={severityClass(f.severity)}>{f.severity}</span>}
                </div>
                {f.argument && <p className="text-sm text-slate-300 mt-1">{f.argument}</p>}
              </div>
            ))}
          </div>
        )}
        {rec.synthesis_rationale && (
          <div className="mt-4">
            <span className="label">Synthesis</span>
            <p className="text-sm text-slate-300">{rec.synthesis_rationale}</p>
          </div>
        )}
        {Array.isArray(rec.must_have_mitigations) && rec.must_have_mitigations.length > 0 && (
          <ul className="list-disc ml-5 mt-3 text-sm text-slate-300">
            {rec.must_have_mitigations.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        )}
      </section>

      <section className="panel p-6">
        <h2 className="section-title">PRD and architecture</h2>
        <p className="section-sub">Stories, requirements, diagrams</p>
        <div className="rule my-4" />
        {prd.product_vision && <p className="text-sm text-slate-300">{prd.product_vision}</p>}
        {Array.isArray(prd.user_stories) && prd.user_stories.length > 0 && (
          <div className="mt-3 space-y-2">
            {prd.user_stories.slice(0, 6).map((s, i) => (
              <div key={i} className="subpanel p-3 text-sm text-slate-300">
                <span className="font-semibold text-white">{s.story_id || `US-0${i + 1}`} </span>
                {s.persona ? `(${s.persona}): ` : ''}{s.want || s.title || JSON.stringify(s).slice(0, 160)}
              </div>
            ))}
          </div>
        )}
        {(prd.architecture_diagram_mermaid || prd.component_mermaid) && (
          <details className="mt-4">
            <summary className="text-sm text-muted cursor-pointer">Diagram source (Mermaid)</summary>
            <pre className="codeblock mt-2">{prd.architecture_diagram_mermaid || prd.component_mermaid}</pre>
          </details>
        )}
      </section>

      <div className="grid md:grid-cols-2 gap-6">
        <section className="panel p-6">
          <h2 className="section-title">Competitors</h2>
          <div className="rule my-4" />
          {(out.competitors || []).slice(0, 5).map((c, i) => (
            <div key={i} className="py-2 rule">
              <div className="font-semibold text-white text-sm">{c.name || `Option ${i + 1}`}</div>
              <div className="text-sm text-slate-300">{c.summary || c.gaps || ''}</div>
              {c.url && <a className="text-xs text-accent" href={c.url} target="_blank" rel="noreferrer">{c.url}</a>}
            </div>
          ))}
          {(!out.competitors || out.competitors.length === 0) && <p className="text-sm text-muted">No competitors returned for this run.</p>}
        </section>
        <section className="panel p-6">
          <h2 className="section-title">Roadmap</h2>
          <div className="rule my-4" />
          {(out.phases || []).map((p, i) => (
            <div key={i} className="subpanel p-3 mb-2">
              <div className="font-semibold text-white text-sm">Phase {p.phase_number || i + 1}: {p.phase_name || p.title}</div>
              <div className="text-xs text-muted">{p.duration_weeks || ''}</div>
              {Array.isArray(p.deliverables) && <ul className="list-disc ml-5 text-sm text-slate-300 mt-1">{p.deliverables.map((d, j) => <li key={j}>{d}</li>)}</ul>}
            </div>
          ))}
          {(!out.phases || out.phases.length === 0) && <p className="text-sm text-muted">No phases returned for this run.</p>}
        </section>
      </div>
    </div>
  )
}

function CodeView({ out }) {
  if (!out || out.type === 'error') return null
  const list = out.candidates || []
  return (
    <div className="space-y-6">
      <section className="panel p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="section-title">Diagnosis</h2>
          {out.critic && <span className="tag tag-info">Grounding {Math.round((out.critic.grounding_score || 0) * 100)} percent</span>}
        </div>
        <div className="rule my-4" />
        <p className="text-sm text-slate-300">{out.summary}</p>
      </section>
      {list.map((c, i) => (
        <section key={i} className="panel p-6">
          <div className="flex flex-wrap gap-2 items-center">
            <h3 className="font-semibold text-white text-sm">{i + 1}. {c.symbol_name || c.file_path}</h3>
            {c.confidence != null && <span className="tag">{Math.round(c.confidence * 100)} percent</span>}
          </div>
          <p className="text-xs text-muted mt-1">{c.file_path}{c.start_line ? `, lines ${c.start_line} to ${c.end_line}` : ''}</p>
          {c.why_problematic && <p className="text-sm text-slate-300 mt-3">{c.why_problematic}</p>}
          <div className="grid lg:grid-cols-2 gap-3 mt-4">
            <div>
              <span className="label">Current code</span>
              <pre className="codeblock">{c.wrong_code || c.code_snippet || 'See file lines cited above.'}</pre>
            </div>
            <div>
              <span className="label">Suggested pattern (review before use)</span>
              <pre className="codeblock">{c.recommended_pattern || c.suggestion || 'No pattern returned.'}</pre>
            </div>
          </div>
        </section>
      ))}
    </div>
  )
}

export default function App() {
  const [pillar, setPillar] = useState('idea')
  const [prompts, setPrompts] = useState({ idea: '', code: '' })
  const [repoPath, setRepoPath] = useState('')
  const [repoBadge, setRepoBadge] = useState('Not scanned')
  const [session, setSession] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [followups, setFollowups] = useState([])
  const [followupInput, setFollowupInput] = useState('')
  const [sending, setSending] = useState(false)
  const [health, setHealth] = useState({ label: 'Checking engine', state: 'unknown' })
  const abortRef = useRef(null)
  const elapsed = useTimer(running)

  const prompt = prompts[pillar]
  const agents = pillar === 'idea' ? IDEA_AGENTS : CODE_AGENTS
  const trace = useMemo(() => session?.execution_trace || [], [session])
  const out = session?.final_output || null

  const refreshHealth = useCallback(async () => {
    try {
      const h = await fetchHealth()
      const cool = h.rate_limits?.cooldowns || {}
      const limited = h.rate_limits?.all_rate_limited
      setHealth(limited
        ? { label: 'Engine resting (rate limit cooldown)', state: 'limited' }
        : Object.keys(cool).length
          ? { label: `Engine ready (${Object.keys(cool).length} model cooling)`, state: 'limited' }
          : { label: 'Engine ready', state: 'ready' })
    } catch {
      setHealth({ label: 'Engine offline', state: 'error' })
    }
  }, [])

  useEffect(() => {
    refreshHealth()
    const t = setInterval(refreshHealth, 30000)
    return () => clearInterval(t)
  }, [refreshHealth])

  function setPrompt(v) {
    setPrompts((p) => ({ ...p, [pillar]: v }))
  }

  async function loadSample() {
    try {
      const s = await fetchSampleRepoPath()
      await scanRepo(s.path)
    } catch (e) { setRepoBadge(`Scan failed: ${e.message}`) }
  }

  async function scanRepo(path) {
    const target = (path ?? repoPath).trim()
    if (!target) { setRepoBadge('Enter a repo path or GitHub URL first'); return }
    setRepoBadge('Scanning...')
    try {
      const r = await inspectRepo(target)
      setRepoPath(r.local_path || target)
      const sum = r.summary || {}
      setRepoBadge(`Indexed: ${sum.total_files ?? '?'} files, ${sum.total_chunks ?? sum.total_symbols ?? '?'} units`)
    } catch (e) { setRepoBadge(`Scan failed: ${e.message}`) }
  }

  async function run() {
    if (!prompt.trim() || running) return
    setError('')
    setRunning(true)
    setSession(null)
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const timeout = setTimeout(() => ctrl.abort(), 150000)
    try {
      const data = await runQuery({
        query: prompt,
        repo_path: pillar === 'code' ? repoPath || undefined : undefined,
        force_intent: pillar === 'idea' ? 'idea_validation' : 'codebase_analysis',
        signal: ctrl.signal,
      })
      setSession(data)
      if (data.final_output?.type === 'error' || data.final_output?.error) {
        setError(data.final_output.error || 'Run returned an error.')
      }
    } catch (e) {
      setError(e.name === 'AbortError' ? 'Run timed out after 150 seconds. Try a smaller repo or shorter prompt.' : e.message)
    } finally {
      clearTimeout(timeout)
      setRunning(false)
    }
  }

  async function send() {
    const q = followupInput.trim()
    if (!q || sending || !out) return
    setSending(true)
    setFollowups((f) => [...f, { role: 'user', text: q }])
    setFollowupInput('')
    try {
      const r = await sendFollowup({
        query: q,
        context: out,
        session_id: session?.session_id,
        repo_path: pillar === 'code' ? repoPath || undefined : undefined,
      })
      setFollowups((f) => [...f, { role: 'agent', name: r.agent_name || 'Agent', text: r.answer || 'No answer returned.' }])
    } catch (e) {
      setFollowups((f) => [...f, { role: 'agent', name: 'Agent', text: `Follow-up failed: ${e.message}` }])
    } finally { setSending(false) }
  }

  function exportReport() {
    if (!out) return
    if (out.full_report_markdown) {
      downloadMarkdown(`agentic_copilot_report_${session?.session_id || 'export'}.md`, out.full_report_markdown)
      return
    }
    let md = `# Agentic AI Co-Pilot: Project Analysis Report\nDate: ${new Date().toLocaleDateString()}\n`
    md += `Session: ${session?.session_id || 'unassigned'}\n\n`
    if (out.type === 'idea_validation') {
      md += `## ${out.project_title || 'Validated concept'}\n\n${out.problem_statement || ''}\n`
    } else {
      md += `## Codebase analysis\n\n${out.summary || ''}\n`
    }
    downloadMarkdown(`agentic_copilot_report_${session?.session_id || 'export'}.md`, md)
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-10 space-y-8">
      <Header health={health} onExport={exportReport} canExport={!!out} />

      <section className="panel p-6">
        <div className="tabs">
          <button className={`tab ${pillar === 'idea' ? 'tab-active' : ''}`} onClick={() => setPillar('idea')}>Idea Assistance</button>
          <button className={`tab ${pillar === 'code' ? 'tab-active' : ''}`} onClick={() => setPillar('code')}>Codebase Analysis</button>
        </div>
        <p className="section-sub mt-3">
          {pillar === 'idea'
            ? 'Problem extraction, market research, roadmap and risk evaluation'
            : 'AST structure navigation, dependency mapping, and issue diagnosis'}
        </p>

        {pillar === 'code' && (
          <div className="mt-4">
            <span className="label">Repository target (local path or public GitHub URL, Python, 300 files max)</span>
            <div className="flex flex-wrap gap-2">
              <input className="input flex-1 min-w-[240px]" value={repoPath} onChange={(e) => setRepoPath(e.target.value)} placeholder="C:/path/to/repo or https://github.com/user/repo" />
              <button className="btn btn-quiet" onClick={loadSample}>Load demo project</button>
              <button className="btn btn-quiet" onClick={() => scanRepo()}>Scan files</button>
            </div>
            <p className="status-text mt-2">[{repoBadge}]</p>
          </div>
        )}

        <div className="mt-4">
          <span className="label">{pillar === 'idea' ? 'Describe your startup or project idea' : 'Paste an error message, or ask about the code'}</span>
          <textarea className="input" rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder={pillar === 'idea' ? 'What problem are you solving? Who is it for? What is your solution...' : 'Paste an exception traceback or ask about code structure (for example: ValueError in verify_token)...'} />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {(pillar === 'idea' ? IDEA_SAMPLES : CODE_SAMPLES).map((s) => (
            <button key={s.label} className="chipbtn" onClick={() => setPrompt(s.prompt)}>{s.label}</button>
          ))}
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button className="btn btn-primary" onClick={run} disabled={running || !prompt.trim()}>
            {running ? 'Running agents...' : pillar === 'idea' ? 'Run Idea Assistance Pipeline' : 'Run Codebase Analysis Pipeline'}
          </button>
          {running && <span className="status-text status-running">[Running: {elapsed.toFixed(1)}s]</span>}
        </div>
        {error && <p className="text-sm mt-3 text-red-300">{error}</p>}
      </section>

      {(running || trace.length > 0) && (
        <section className="panel p-6">
          <h2 className="section-title">Orchestration pipeline</h2>
          <p className="section-sub">Plan, tool choice, retry, and critic check stay visible (synopsis Sec 6.1)</p>
          <div className="rule my-4" />
          <div className="grid md:grid-cols-4 gap-3">
            {agents.map((a, i) => {
              const done = trace[i] != null
              const active = running && trace.length === i
              return (
                <div key={a.name} className="subpanel p-3">
                  <div className="text-xs text-muted">Step {i + 1}</div>
                  <div className="font-semibold text-white text-sm mt-1">{a.name}</div>
                  <div className="text-xs text-muted">{a.role}</div>
                  <div className="text-xs mt-1 text-slate-300">{a.desc}</div>
                  <div className={`status-text mt-2 ${done ? 'status-ready' : active ? 'status-running' : ''}`}>
                    [{done ? 'Done' : active ? 'Running' : 'Queued'}]
                  </div>
                </div>
              )
            })}
          </div>
          {trace.length > 0 && (
            <div className="grid md:grid-cols-2 gap-3 mt-4">
              {trace.map((t, i) => <TraceStep key={t.step_id || i} step={t} index={i} />)}
            </div>
          )}
        </section>
      )}

      {session && (
        <section className="panel p-6">
          <div className="flex flex-wrap gap-6 text-sm">
            <div><span className="label">Intent</span><span className="text-white font-semibold">{session.intent}</span></div>
            <div><span className="label">Latency</span><span className="text-white font-semibold">{(session.total_latency_ms / 1000).toFixed(1)}s</span></div>
            <div><span className="label">Revisions</span><span className="text-white font-semibold">{session.revision_count}</span></div>
            <div><span className="label">Session</span><span className="text-white font-semibold font-mono text-xs">{session.session_id}</span></div>
          </div>
        </section>
      )}

      {out && out.type === 'idea_validation' && <IdeaView out={out} />}
      {out && out.type === 'codebase_analysis' && <CodeView out={out} />}

      {out && (
        <section className="panel p-6">
          <h2 className="section-title">Follow-up</h2>
          <p className="section-sub">Ask about this result. Session memory keeps repo and report context.</p>
          <div className="rule my-4" />
          <div className="space-y-3">
            {followups.length === 0 && <p className="text-sm text-muted">No follow-ups yet. Try: what is the biggest risk, or what calls this function.</p>}
            {followups.map((m, i) => (
              <div key={i} className="subpanel p-3">
                <div className="text-xs text-muted">{m.role === 'user' ? 'You' : m.name}</div>
                <p className="text-sm text-slate-200 mt-1 whitespace-pre-wrap">{m.text}</p>
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <input className="input flex-1" value={followupInput} onChange={(e) => setFollowupInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              placeholder="Ask a follow-up about this result..." />
            <button className="btn btn-primary" onClick={send} disabled={sending || !followupInput.trim()}>
              {sending ? 'Sending...' : 'Send'}
            </button>
          </div>
        </section>
      )}

      <footer className="text-xs text-muted">Agentic AI Co-Pilot, Minor Project, GGSIPU. Read-only analysis, human review required.</footer>
    </div>
  )
}
