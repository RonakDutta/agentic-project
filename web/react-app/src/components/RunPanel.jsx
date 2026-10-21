import { useEffect, useState } from 'react'
import PipelineGraph from './PipelineGraph.jsx'
import { modelName, plainText, seconds } from './ui.jsx'

function Elapsed({ startedAt, endedAt }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (endedAt) return undefined
    const t = setInterval(() => setNow(Date.now()), 200)
    return () => clearInterval(t)
  }, [endedAt])
  return <span className="mono">{(((endedAt || now) - startedAt) / 1000).toFixed(1)}s</span>
}

/** Live view of a run: the agent graph plus every real step and AI call as it happens. */
export default function RunPanel({ run, pipeline, hidden }) {
  const steps = run.events.filter((e) => e.agent_name !== 'Orchestrator' || e.status !== 'completed' || /Classified|completed in/.test(e.action))
  const feed = [
    ...steps.map((e) => ({ kind: 'step', at: e.elapsed_ms, e })),
    ...run.calls.map((c) => ({ kind: 'call', at: c.elapsed_ms, c })),
  ].sort((a, b) => b.at - a.at)
  const tokens = run.calls.reduce((s, c) => s + (c.tokens || 0), 0)
  const live = run.calls.filter((c) => !c.cached).length

  return (
    <div className="card pad stack fade-in">
      <div className="row between">
        <div className="row">
          <h3 className={`state ${run.phase === 'running' ? 'live' : run.phase === 'error' ? 'risk' : ''}`}>{run.phase === 'running' ? 'Agents at work' : run.phase === 'error' ? 'Run stopped' : 'Run complete'}</h3>
          <span className="muted small">live from the server, nothing replayed</span>
        </div>
        <div className="row small muted">
          <span><Elapsed startedAt={run.startedAt} endedAt={run.endedAt} /></span>
          <span>·</span>
          <span>{live} AI calls</span>
          <span>·</span>
          <span>{tokens.toLocaleString()} tokens</span>
        </div>
      </div>
      <PipelineGraph pipeline={pipeline} events={run.events} phase={run.phase} hidden={hidden} />
      <details className="more" open={run.phase === 'running'}>
        <summary>Step log ({feed.length})</summary>
        <div className="log" style={{ marginTop: 8 }}>
          {feed.map((item, i) => item.kind === 'step' ? (
            <div className="log-item" key={`s${i}`}>
              <span className="log-time">{seconds(item.e.elapsed_ms)}</span>
              <span>
                <strong style={{ fontWeight: 600 }}>{item.e.agent_name}</strong> <span className="muted">{plainText(item.e.action)}</span>
                {item.e.status === 'warning' && <span className="state warn"> (fallback)</span>}
              </span>
            </div>
          ) : (
            <div className="log-item" key={`c${i}`}>
              <span className="log-time">{seconds(item.c.elapsed_ms)}</span>
              <span className="log-call">
                {item.c.cached ? 'AI answer reused from cache (0 tokens)' : `AI call · ${modelName(item.c.model)} · ${item.c.tokens} tokens · ${seconds(item.c.latency_ms)}`}
              </span>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}
