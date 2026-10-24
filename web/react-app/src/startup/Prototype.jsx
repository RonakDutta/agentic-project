import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api.js'
import { PROTOTYPE_PIPELINE } from '../pipelines.js'
import RunPanel from '../components/RunPanel.jsx'
import { More, Tag, plainText, seconds } from '../components/ui.jsx'

const BY = { ai: ['AI', 'info'], fallback: ['Built-in fallback', 'warn'], template: ['Template', ''] }
const RANK = { 'must have': 0, 'should have': 1, 'nice to have': 2 }

function planned(out) {
  const reqs = [...(out.prd?.functional_requirements || [])]
  reqs.sort((a, b) => (RANK[String(a.priority).toLowerCase()] ?? 3) - (RANK[String(b.priority).toLowerCase()] ?? 3))
  const picked = reqs.slice(0, 3).map((r) => r.title)
  return picked.length ? picked : (out.mvp_features || []).slice(0, 3)
}

function clock(s) {
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function Code({ text }) {
  return (
    <div className="codebox" style={{ maxHeight: 460 }}>
      <pre>{text.replace(/\n$/, '').split('\n').map((l, i) => (
        <div className="ln" key={i}><span>{i + 1}</span><span>{l || ' '}</span></div>
      ))}</pre>
    </div>
  )
}

function Check({ ok, label, detail }) {
  return (
    <div className="row small" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
      <span className={`check ${ok ? 'ok' : 'no'}`} style={{ minWidth: 44, justifyContent: 'center' }}>{ok ? 'Pass' : 'Fail'}</span>
      <span><strong style={{ fontWeight: 600 }}>{label}</strong>{detail && <span className="muted"> {detail}</span>}</span>
    </div>
  )
}

/** Live process status, read from the prototype's own request log every 2 seconds. */
function useMonitor(id, initial) {
  const [status, setStatus] = useState(initial)
  useEffect(() => {
    if (!id) return undefined
    let alive = true
    const load = () => getJSON(`/api/prototype/${id}/status`).then((s) => alive && setStatus(s)).catch(() => {})
    load()
    const t = setInterval(load, 2000)
    return () => { alive = false; clearInterval(t) }
  }, [id])
  return [status, setStatus]
}

function Monitor({ build }) {
  const [status, setStatus] = useMonitor(build.id, null)
  const [busy, setBusy] = useState(false)
  const s = status || {}
  const running = s.state === 'running'

  async function toggle() {
    setBusy(true)
    try {
      const next = running
        ? await postJSON(`/api/prototype/${build.id}/stop`, {})
        : (await postJSON(`/api/prototype/${build.id}/start`, {})).status
      setStatus(next)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="card pad stack">
        <div className="row between">
          <div className="row">
            <h3>Live app</h3>
            <span className={`state ${running ? 'good' : s.state === 'crashed' ? 'risk' : 'warn'}`}>
              {running ? 'Running' : s.state === 'crashed' ? 'Crashed' : 'Stopped'}
            </span>
            {running && <span className="tiny muted">stops by itself in {clock(s.auto_stop_in_s || 0)}</span>}
          </div>
          <div className="row">
            {running && <a className="btn sm" href={s.url} target="_blank" rel="noopener noreferrer">Open in new tab</a>}
            <button className="btn sm" disabled={busy} onClick={toggle}>{busy ? 'Please wait...' : running ? 'Stop app' : 'Start app'}</button>
          </div>
        </div>
        {running ? (
          <div className="preview">
            <div className="preview-bar mono tiny">{s.url}</div>
            <iframe title="Prototype preview" src={s.url} sandbox="allow-scripts allow-forms allow-same-origin" />
          </div>
        ) : (
          <div className="empty">
            {s.stopped_reason || 'The app is not running.'} Press "Start app" to run it again.
            {s.server_log?.length > 0 && <pre className="soft tiny" style={{ textAlign: 'left', padding: 10, marginTop: 10, overflowX: 'auto' }}>{s.server_log.join('\n')}</pre>}
          </div>
        )}
      </div>

      <div className="card pad stack">
        <div className="row between"><h3>Monitor</h3><span className="tiny muted">Read from the app's own request log every 2 s</span></div>
        <div className="grid g4">
          <div className="mini"><div className="v">{s.requests_visitors ?? 0}</div><div className="l">Requests from people</div></div>
          <div className="mini"><div className="v">{s.requests_checks ?? 0}</div><div className="l">Requests from the builder's checks</div></div>
          <div className="mini"><div className={`v ${s.server_errors ? 'risk' : ''}`}>{s.server_errors ?? 0}</div><div className="l">Server errors (5xx)</div></div>
          <div className="mini"><div className="v">{s.avg_ms ?? 0}<small> ms</small></div><div className="l">Average response time</div></div>
        </div>
        {(s.recent || []).length > 0 ? (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>Time</th><th>Request</th><th>Status</th><th>Time taken</th><th>From</th></tr></thead>
              <tbody>
                {[...s.recent].reverse().slice(0, 8).map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{new Date(r.t * 1000).toLocaleTimeString()}</td>
                    <td className="mono">{r.method} {r.path}</td>
                    <td><Tag tone={r.status >= 500 ? 'risk' : r.status >= 400 ? 'warn' : 'good'}>{r.status}</Tag></td>
                    <td className="mono">{r.ms} ms</td>
                    <td className="muted">{r.check ? 'Builder check' : 'Person'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="small muted">No requests yet.</div>}
        {(s.recent_errors || []).length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="small" style={{ color: 'var(--risk)', fontWeight: 600 }}>Last errors</div>
            {s.recent_errors.map((e, i) => <div key={i} className="mono tiny">{e.method} {e.path}: {e.error || e.status}</div>)}
          </div>
        )}
      </div>
    </>
  )
}

function Result({ build, onReview }) {
  const [file, setFile] = useState(build.files[0]?.path)
  const c = build.checks || {}
  const tests = c.tests || {}
  const called = (c.endpoints || []).filter((e) => e.status !== null)
  const answered = called.filter((e) => e.status >= 200 && e.status < 300).length
  const aiFiles = build.files.filter((f) => f.written_by !== 'template')
  const current = build.files.find((f) => f.path === file) || build.files[0]

  return (
    <div className="stack-lg">
      <div className="grid g4">
        <div className="card stat"><div className="value">{tests.passed ?? 0}<small>/ {tests.total ?? 0}</small></div><div className="label">Tests passed</div></div>
        <div className="card stat"><div className="value">{answered}<small>/ {called.length}</small></div><div className="label">Endpoints answered</div></div>
        <div className="card stat"><div className="value">{aiFiles.reduce((n, f) => n + f.lines, 0)}</div><div className="label">Lines written by {build.generation_source === 'llm' ? 'AI' : 'the fallback'}</div></div>
        <div className="card stat"><div className="value">{c.server?.ok ? 'Yes' : 'No'}</div><div className="label">App started</div></div>
      </div>

      <div className="row tiny">
        <Tag tone={build.generation_source === 'llm' ? 'info' : 'warn'}>{build.generation_source === 'llm' ? 'Code written by AI' : 'Built-in fallback prototype'}</Tag>
        {build.repaired && <Tag tone="accent">AI fixed its own code once after a failed check</Tag>}
        <Tag>Generated prototype, not a finished product</Tag>
        {build.fallback_reason && <span className="muted">Why the fallback: {plainText(build.fallback_reason)}</span>}
      </div>

      <Monitor build={build} />

      <div className="card pad stack">
        <h3>Checks (all run by code, not AI)</h3>
        <Check ok={c.safety_ok} label="Safety check" detail="only safe imports, no eval/exec/open, no outside scripts" />
        <Check ok={c.compile_ok} label="Compiles" detail="every Python file" />
        <Check ok={tests.ok} label="Tests" detail={`${tests.passed || 0} passed, ${tests.failed || 0} failed (${seconds(tests.duration_ms)})`} />
        <Check ok={!!c.server?.ok} label="App starts" detail={c.server?.ok ? `answered /health in ${seconds(c.server.ms)}` : c.server?.error} />
        <More label="Test output">
          <pre className="soft tiny" style={{ padding: 10, overflowX: 'auto', margin: 0 }}>{tests.output || 'No output.'}</pre>
        </More>
        <div className="table-wrap">
          <table className="tbl">
            <thead><tr><th>Endpoint</th><th>Result</th></tr></thead>
            <tbody>
              {(c.endpoints || []).map((e, i) => (
                <tr key={i}>
                  <td className="mono">{e.method} {e.path}</td>
                  <td>{e.status === null ? <span className="muted">covered by the tests</span> : <><Tag tone={e.status < 300 ? 'good' : 'risk'}>{e.status}</Tag> <span className="mono tiny muted">{e.ms} ms</span></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card pad stack">
        <div className="row between">
          <h3>Code</h3>
          <div className="row">
            <button className="btn sm" onClick={() => onReview(build)}>Review with Codebase Evaluation</button>
            <a className="btn sm" href={`/api/prototype/${build.id}/download`}>Download zip</a>
          </div>
        </div>
        <div className="row">
          {build.files.map((f) => (
            <button key={f.path} className={`chip mono ${f.path === current?.path ? 'on' : ''}`} onClick={() => setFile(f.path)}>{f.path}</button>
          ))}
        </div>
        {current && (
          <>
            <div className="row tiny"><Tag tone={BY[current.written_by]?.[1]}>{BY[current.written_by]?.[0]}</Tag><span className="muted">{current.lines} lines</span></div>
            <Code text={current.content} />
          </>
        )}
        <div className="tiny muted">Saved in {build.path}</div>
      </div>
    </div>
  )
}

/** Prototype tab: builds, tests, runs and monitors a tiny app made from this idea. */
export default function Prototype({ out, sessionId, protoRun }) {
  const { run, start } = protoRun
  const build = run?.result?.final_output
  const features = planned(out)

  function review(b) {
    window.dispatchEvent(new CustomEvent('copilot:review', {
      detail: { path: b.path, question: 'Check the API endpoints in features.py for bugs and missing input checks.' },
    }))
  }

  return (
    <div className="stack-lg">
      {!run && (
        <div className="card pad-lg stack">
          <div className="eyebrow accent">Prototype Builder</div>
          <h2 className="display">Turn this idea into a small working app</h2>
          <p style={{ margin: 0, color: 'var(--ink-2)', maxWidth: 640 }}>
            The AI writes a tiny FastAPI app with one web page for the top requirements. Then code checks it, runs its tests, starts it on this computer and keeps an eye on it.
          </p>
          {features.length > 0 && (
            <div className="stack" style={{ gap: 6 }}>
              <div className="small muted">It will try to build:</div>
              <ol className="list small" style={{ margin: 0 }}>{features.map((f, i) => <li key={i}>{f}</li>)}</ol>
            </div>
          )}
          <div className="row">
            <button className="btn primary" onClick={() => start({ session_id: sessionId })}>Build prototype</button>
            <span className="tiny muted">About 30 to 60 seconds · 1 or 2 AI calls · runs only on this computer</span>
          </div>
        </div>
      )}
      {run && <RunPanel run={run} pipeline={PROTOTYPE_PIPELINE} />}
      {run?.phase === 'error' && (
        <div className="card pad row between">
          <span className="small" style={{ color: 'var(--risk)' }}>{run.error}</span>
          <button className="btn sm" onClick={() => start({ session_id: sessionId })}>Try again</button>
        </div>
      )}
      {build && (
        <>
          <Result key={build.id} build={build} onReview={review} />
          <div className="row"><button className="btn sm" onClick={() => start({ session_id: sessionId })}>Build again</button></div>
        </>
      )}
    </div>
  )
}
