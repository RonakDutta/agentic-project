import { More, Tag, modelName, plainText, seconds } from './ui.jsx'

/** Every recorded agent step, plus every AI call with its model, tokens and latency. */
export default function TraceView({ state, calls }) {
  const trace = state.execution_trace || []
  const live = calls.filter((c) => !c.cached)
  const tokens = live.reduce((s, c) => s + (c.tokens || 0), 0)
  const models = [...new Set(live.map((c) => c.model))]
  return (
    <div className="stack-lg">
      <div className="grid g4">
        <div className="card stat"><div className="value">{trace.length}</div><div className="label">steps recorded</div></div>
        <div className="card stat"><div className="value">{live.length}</div><div className="label">AI calls ({calls.length - live.length} from cache)</div></div>
        <div className="card stat"><div className="value">{tokens.toLocaleString()}</div><div className="label">tokens used</div></div>
        <div className="card stat"><div className="value">{seconds(state.total_latency_ms)}</div><div className="label">total time</div></div>
      </div>
      {models.length > 0 && (
        <div className="card pad stack">
          <h3>AI calls</h3>
          <div className="stack" style={{ gap: 6 }}>
            {live.map((c, i) => (
              <div key={i} className="row between small" style={{ borderBottom: '1px dashed var(--line)', paddingBottom: 6 }}>
                <span className="mono">{modelName(c.model)}</span>
                <span className="muted mono">{c.tokens} tokens · {seconds(c.latency_ms)} · at {seconds(c.elapsed_ms)}</span>
              </div>
            ))}
          </div>
          <div className="tiny muted">Three models share the work; the engine moves to another model when one is busy.</div>
        </div>
      )}
      <div className="card pad stack">
        <h3>Agent steps</h3>
        {trace.map((t) => {
          const d = t.details || {}
          const tone = t.status === 'warning' ? 'warn' : t.status === 'revised' ? 'accent' : 'good'
          return (
            <div key={t.step_id} className="stack" style={{ gap: 4, borderBottom: '1px solid var(--line)', paddingBottom: 10 }}>
              <div className="row between">
                <span className="row"><Tag tone={tone}>{t.status}</Tag><strong style={{ fontWeight: 600 }}>{t.agent_name}</strong></span>
                <span className="tiny muted mono">{seconds(t.elapsed_ms)}</span>
              </div>
              <div className="small muted">{plainText(t.action)}</div>
              {(d.findings || d.rubric || d.papers || d.notes) && (
                <More label="Details">
                  <ul className="list small">
                    {[...(d.findings || []), ...(d.rubric || []), ...(d.papers || []), ...(d.notes || [])].map((f, i) => <li key={i}>{plainText(String(f))}</li>)}
                  </ul>
                  {d.tool && <div className="tiny muted" style={{ marginTop: 6 }}>Tool: {plainText(d.tool)}</div>}
                  {d.fallback_reason && <div className="tiny" style={{ color: 'var(--warn)', marginTop: 4 }}>Fallback: {plainText(d.fallback_reason)}</div>}
                </More>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
