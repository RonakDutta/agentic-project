import React from 'react'

function nodeClass(state) {
  // state: 'waiting' | 'working' | 'done' | 'error'
  if (state === 'error') return 'subpanel p-3.5 space-y-1 border-l-2 border-l-rose-500'
  if (state === 'working') return 'subpanel p-3.5 space-y-1 border-l-2 border-l-blue-500'
  if (state === 'done') return 'subpanel p-3.5 space-y-1 border-l-2 border-l-emerald-500'
  return 'subpanel p-3.5 space-y-1'
}

function badgeClass(state) {
  if (state === 'error') return 'status-badge text-rose-400 font-semibold text-[11px]'
  if (state === 'working') return 'status-badge text-blue-400 font-semibold text-[11px]'
  if (state === 'done') return 'status-badge text-emerald-400 font-semibold text-[11px]'
  return 'status-badge text-zinc-500 font-semibold text-[11px]'
}

function badgeText(state) {
  if (state === 'working') return 'Working...'
  if (state === 'done') return 'Done'
  if (state === 'error') return 'Error'
  return 'Waiting'
}

function StoryCard({ step, idx }) {
  const d = step.details || {}
  const findings = Array.isArray(d.findings) ? d.findings : []
  return (
    <div className="subpanel p-5 sm:p-6 space-y-3 animate-step-reveal">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borderSubtle/70 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="label is-inline is-accent" style={{ margin: 0 }}>Step {idx + 1}</span>
          <h4 className="text-sm sm:text-base font-semibold text-white">{step.agent_name}</h4>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="tag">{d.tool || 'Reasoning engine'}</span>
          <span className="text-zinc-400">{((step.elapsed_ms || 0) / 1000).toFixed(1)} s</span>
        </div>
      </div>

      <div className="space-y-1">
        <span className="label">What it was trying to do</span>
        <p className="text-xs sm:text-sm text-zinc-300 leading-relaxed subpanel p-3.5">
          {d.thinking || step.action}
        </p>
      </div>

      {findings.length > 0 && (
        <div className="space-y-1.5 pt-1">
          <span className="label is-good">What it found</span>
          <ul className="space-y-1 text-xs sm:text-sm text-zinc-200 pl-4 list-disc leading-relaxed">
            {findings.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}

      {d.handoff && (
        <div className="pt-2 rule flex items-center gap-2 text-xs">
          <span className="label is-inline" style={{ margin: 0 }}>Passed to the next step:</span>
          <span className="text-zinc-300 font-medium">{d.handoff}</span>
        </div>
      )}
    </div>
  )
}

export default function Pipeline({
  agents, nodeStates, steps, loader,
  statusText, statusClass, timerText,
  trace, traceOpen, onToggleTrace, error,
}) {
  return (
    <section className="panel p-6 sm:p-8 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="section-title">Multi-Agent Orchestration Pipeline</h2>
          <p className="section-sub">Coordinated agents execute goal decomposition, retrieval, and synthesis with live trace.</p>
        </div>
        <div className="text-xs text-zinc-400 pt-1">
          Status: <span className={statusClass}>{statusText}</span>
          <span className="ml-2 text-zinc-500">{timerText}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {agents.map((ag, idx) => (
          <div key={ag.id} className={nodeClass(nodeStates[idx])}>
            <div className="flex items-center justify-between text-[11px] text-zinc-500">
              <span>Agent {idx + 1} of {agents.length}</span>
              <span className={badgeClass(nodeStates[idx])}>{badgeText(nodeStates[idx])}</span>
            </div>
            <div className="font-bold text-xs sm:text-sm text-zinc-100">{ag.name}</div>
            <p className="text-[11px] text-zinc-400 leading-snug">{ag.desc}</p>
          </div>
        ))}
      </div>

      <div className="space-y-4 pt-2">
        {steps.map((step, i) => <StoryCard key={`${step.step_id}-${i}`} step={step} idx={i} />)}
        {loader && (
          <div className="subpanel p-4 space-y-1 border-l-2 border-l-blue-500">
            <div className="space-y-0.5">
              <div className="label is-accent" style={{ marginBottom: 0 }}>
                Step {loader.idx + 1} of {agents.length}: {loader.step.agent_name} is working
              </div>
              <div className="text-xs text-zinc-300">{loader.actionText}</div>
            </div>
          </div>
        )}
        {error && (
          <div className="callout callout-risk space-y-3 animate-step-reveal">
            <div>
              <h4 className="text-sm sm:text-base font-semibold text-rose-300">The review stopped</h4>
              <p className="text-xs text-zinc-400">Nothing was lost. You can run it again in a moment.</p>
            </div>
            <div className="p-3.5 bg-canvas/90 rounded-md text-xs text-rose-300 break-words leading-relaxed">
              {error}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs text-zinc-400">
              <span>If the free AI limit was reached, wait about 30 seconds and try again.</span>
              <button onClick={error.onRetry} className="btn btn-primary py-2">Run again</button>
            </div>
          </div>
        )}
      </div>

      {trace.length > 0 && (
        <div className="pt-2 rule">
          <button onClick={onToggleTrace} className="text-xs text-zinc-400 hover:text-white flex items-center gap-1.5">
            <span>Show timing log ({trace.length} steps)</span>
            <svg className={`w-3.5 h-3.5 transform transition-transform ${traceOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {traceOpen && (
            <div className="mt-3 max-h-48 overflow-y-auto space-y-1.5 p-3 rounded-lg bg-canvas border border-borderSubtle text-xs font-mono">
              {trace.map((t, i) => (
                <div key={i} className="border-l border-borderSubtle pl-3 py-1 flex items-start justify-between text-xs">
                  <div>
                    <span className="text-white font-bold">[{t.agent_name}]</span>
                    <span className="text-zinc-400 ml-2">{t.action}</span>
                  </div>
                  <span className="text-zinc-500 text-[11px] whitespace-nowrap ml-3">+{t.elapsed_ms}ms</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
