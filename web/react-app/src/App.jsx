import { useEffect, useState } from 'react'
import { getJSON, postJSON } from './api.js'
import { useRun } from './useRun.js'
import { CODE_PIPELINE, STARTUP_PIPELINE } from './pipelines.js'
import PipelineGraph from './components/PipelineGraph.jsx'
import RunPanel from './components/RunPanel.jsx'
import StartupResult from './startup/StartupResult.jsx'
import CodeResult from './code/CodeResult.jsx'
import { Tag } from './components/ui.jsx'
import Landing from './Landing.jsx'

const IDEA_EXAMPLES = [
  ['Smart water meter', 'A smart ultrasonic water meter for residential buildings using LoRaWAN to detect pipe leakages in real time and estimate daily household consumption.'],
  ['AI code reviewer', 'An automated AI peer review platform for engineering students that checks their lab code submissions for code quality, linting and AST-based standards.'],
  ['Energy spike monitor', 'A low-cost IoT energy auditing system for residential societies that detects abnormal power spikes using ESP32 with CT current sensors and alerts residents.'],
]
// Short answers to "a chatbot can do this too, what is different?"
const STARTUP_WHY = [
  ['Real papers, real links', 'Papers come live from arXiv, Semantic Scholar and OpenAlex. Every link opens the actual paper.'],
  ['Scores computed in code', 'The rubric and the novelty index are formulas. Same idea, same score, every time.'],
  ['Checked before it is shown', 'Invented citations are removed. The prototype is tested and started before you see it.'],
]
const CODE_WHY = [
  ['Reads the whole project', 'It parses every file (AST) and builds a call graph, instead of looking at one pasted snippet.'],
  ['Every answer checked on disk', 'File, function, line numbers and quoted code are compared with the real files.'],
  ['Read-only', 'Nothing in your project is changed. Suggested fixes are compiled, not applied.'],
]

function Why({ items }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <h3>Why not just ask a chatbot?</h3>
      <div className="why grid g3">
        {items.map(([title, text], i) => (
          <div key={title} className="card">
            <span className="num">0{i + 1}</span>
            <strong style={{ fontWeight: 650 }}>{title}</strong>
            <p>{text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

const CODE_EXAMPLES = [
  ['Duplicate orders bug', 'Orders sometimes get processed twice when the user double clicks checkout. Where is the bug?'],
  ['Expired token crash', 'ValueError: Token expired when verify_token validates customer credentials during checkout.'],
  ['Blast radius', 'What is the blast radius if I modify verify_token in the auth module?'],
  ['Where is auth checked?', 'Where is customer authentication verified when placing an order, and how is expiry checked?'],
]

function readTheme() {
  try { return localStorage.getItem('copilot-theme') || 'light' } catch { return 'light' }
}

function Header({ pillar, setPillar, theme, setTheme, onHome }) {
  const [health, setHealth] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => getJSON('/api/health').then((h) => alive && setHealth(h)).catch(() => alive && setHealth(false))
    load()
    const t = setInterval(load, 20000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  let status = <>Connecting...</>
  if (health === false) status = <span className="state risk">Server offline</span>
  else if (health) {
    const m = health.metrics || {}
    status = m.llm_configured
      ? <>{health.rate_limits?.all_rate_limited ? <span className="state warn">Engine busy</span> : <span className="state good">Engine ready</span>} · {health.model_chain?.length} models · {m.total_calls || 0} AI calls served{m.cache_hits ? `, ${m.cache_hits} from cache` : ''}</>
      : <span className="state warn">AI engine offline: built-in fallbacks</span>
  }
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">AC</div>
          <div>
            <button className="brand-name link" onClick={onHome} title="Back to the start page">Agentic Co-Pilot</button>
            <div className="brand-sub">Multi-agent AI · GGSIPU USAR minor project</div>
          </div>
        </div>
        <div className="switch" role="tablist" aria-label="Choose a tool">
          <button className={pillar === 'startup' ? 'on' : ''} onClick={() => setPillar('startup')}>Startup Assistance</button>
          <button className={pillar === 'code' ? 'on' : ''} onClick={() => setPillar('code')}>Codebase Evaluation</button>
        </div>
        <div className="engine">{status}</div>
        <button className="icon-btn" aria-label="Toggle dark mode" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? '☀' : '☾'}
        </button>
      </div>
    </header>
  )
}

function RunButton({ running, onRun, onStop, disabled }) {
  return running
    ? <button className="btn" onClick={onStop}>Stop</button>
    : <button className="btn primary" disabled={disabled} onClick={onRun}>Run agents</button>
}

function StartupPage() {
  const [idea, setIdea] = useState('')
  const { run, start, stop } = useRun()
  const running = run?.phase === 'running'
  const go = () => idea.trim().length >= 15 && start({ query: idea.trim(), force_intent: 'idea_validation' })
  return (
    <div className="stack-lg">
      {!run && (
        <div className="hero">
          <div className="eyebrow accent">Startup Assistance</div>
          <h1 className="display">Is your idea worth building?</h1>
          <p>Seven agents check it against the market, real research papers and a devil's advocate, score it with a fixed rubric, and can then build a small working prototype.</p>
        </div>
      )}
      <div className="card composer" style={{ marginTop: run ? 24 : 0 }}>
        <textarea className="textarea" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Describe your idea: the problem, who has it, and how you would solve it."
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }} />
        <div className="composer-foot">
          <span className="tiny muted">Try:</span>
          {IDEA_EXAMPLES.map(([label, text]) => <button key={label} className="chip" onClick={() => setIdea(text)}>{label}</button>)}
          <RunButton running={running} onRun={go} onStop={stop} disabled={idea.trim().length < 15} />
        </div>
      </div>
      {!run && (
        <div className="card pad stack">
          <div className="row between"><h3>How a run works</h3><span className="tiny muted">The same graph lights up live while it runs</span></div>
          <PipelineGraph pipeline={STARTUP_PIPELINE} events={[]} phase="idle" />
        </div>
      )}
      {!run && <Why items={STARTUP_WHY} />}
      {run && <RunPanel run={run} pipeline={STARTUP_PIPELINE} />}
      {run?.phase === 'error' && <div className="card pad small" style={{ color: 'var(--risk)' }}>{run.error}</div>}
      {run?.result && <StartupResult run={run} />}
    </div>
  )
}

function CodePage() {
  const [repo, setRepo] = useState('')
  const [scan, setScan] = useState(null)
  const [question, setQuestion] = useState('')
  const { run, start, stop } = useRun()
  const running = run?.phase === 'running'
  const isUrl = /^https?:\/\//.test(repo.trim())

  async function useDemo() {
    const data = await getJSON('/api/sample-repo-path')
    setRepo(data.path)
    inspect(data.path)
  }
  async function inspect(path = repo) {
    if (!path.trim()) return
    setScan({ busy: true })
    try {
      const res = await postJSON('/api/inspect-repo', { repo_path: path.trim() })
      setScan(res)
    } catch (err) {
      setScan({ error: err.message })
    }
  }
  const go = () => repo.trim() && question.trim() && start({ query: question.trim(), repo_path: repo.trim(), force_intent: 'codebase_analysis' })

  // "Review with Codebase Evaluation" on a generated prototype fills in this page.
  useEffect(() => {
    const onReview = (e) => { setRepo(e.detail.path); setQuestion(e.detail.question); inspect(e.detail.path) }
    window.addEventListener('copilot:review', onReview)
    return () => window.removeEventListener('copilot:review', onReview)
  })

  return (
    <div className="stack-lg">
      {!run && (
        <div className="hero">
          <div className="eyebrow accent">Codebase Evaluation</div>
          <h1 className="display">Find the bug. See what a change would break.</h1>
          <p>Point it at a Python project. It reads the code structure, finds the right functions, and a critic checks every answer against your real files. Nothing is edited.</p>
        </div>
      )}
      <div className="card composer" style={{ marginTop: run ? 24 : 0 }}>
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <input className="input mono" value={repo} onChange={(e) => { setRepo(e.target.value); setScan(null) }} placeholder="C:/path/to/project  or  https://github.com/owner/repo" />
          <button className="btn" onClick={() => inspect()} disabled={!repo.trim() || scan?.busy}>{scan?.busy ? (isUrl ? 'Cloning...' : 'Scanning...') : 'Scan'}</button>
          <button className="btn" onClick={useDemo}>Demo repo</button>
        </div>
        {scan && !scan.busy && (
          scan.error
            ? <div className="small" style={{ color: 'var(--risk)' }}>{scan.error}</div>
            : <div className="row tiny"><Tag tone="good">{scan.summary?.total_files} files · {scan.summary?.total_chunks} functions and classes</Tag><span className="muted">{scan.is_remote ? `Cloned ${scan.repo_name}` : 'Local folder'}</span></div>
        )}
        <textarea className="textarea" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Paste an error, describe a bug, or ask what a change would break."
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }} />
        <div className="composer-foot">
          <span className="tiny muted">Try:</span>
          {CODE_EXAMPLES.map(([label, text]) => <button key={label} className="chip" onClick={() => setQuestion(text)}>{label}</button>)}
          <RunButton running={running} onRun={go} onStop={stop} disabled={!repo.trim() || !question.trim()} />
        </div>
      </div>
      {!run && (
        <div className="card pad stack">
          <div className="row between"><h3>How a run works</h3><span className="tiny muted">Only one step uses AI. The rest is code you can check.</span></div>
          <PipelineGraph pipeline={CODE_PIPELINE} events={[]} phase="idle" />
        </div>
      )}
      {!run && <Why items={CODE_WHY} />}
      {run && <RunPanel run={run} pipeline={CODE_PIPELINE} />}
      {run?.phase === 'error' && <div className="card pad small" style={{ color: 'var(--risk)' }}>{run.error}</div>}
      {run?.result && <CodeResult run={run} repoPath={repo} />}
    </div>
  )
}

// "#/app" (or "#/app/code") shows the tools; anything else shows the landing page.
function readRoute() {
  const hash = window.location.hash
  return { inApp: hash.startsWith('#/app'), pillar: hash === '#/app/code' ? 'code' : 'startup' }
}

export default function App() {
  const [route, setRoute] = useState(readRoute)
  const [pillar, setPillar] = useState(route.pillar)
  const [theme, setTheme] = useState(readTheme)
  useEffect(() => {
    const onHash = () => { const r = readRoute(); setRoute(r); if (r.inApp) setPillar(r.pillar) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const enter = (p) => { window.location.hash = p === 'code' ? '#/app/code' : '#/app'; window.scrollTo({ top: 0 }) }
  const home = () => { window.location.hash = ''; window.scrollTo({ top: 0 }) }
  useEffect(() => {
    const toCode = () => { setPillar('code'); window.scrollTo({ top: 0 }) }
    window.addEventListener('copilot:review', toCode)
    return () => window.removeEventListener('copilot:review', toCode)
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('copilot-theme', theme) } catch { /* private mode */ }
  }, [theme])
  if (!route.inApp) return <Landing onEnter={enter} theme={theme} setTheme={setTheme} />
  return (
    <>
      <Header pillar={pillar} setPillar={setPillar} theme={theme} setTheme={setTheme} onHome={home} />
      <main className="shell">
        {/* Both pages stay mounted so a running review keeps going when you switch. */}
        <div hidden={pillar !== 'startup'}><StartupPage /></div>
        <div hidden={pillar !== 'code'}><CodePage /></div>
        <footer className="foot">
          <span>Every score is computed in code. AI text is labelled, and so are fallbacks.</span>
          <span>Agentic Co-Pilot · B.Tech minor project, GGSIPU USAR</span>
        </footer>
      </main>
    </>
  )
}
