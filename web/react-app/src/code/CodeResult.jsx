import { useState } from 'react'
import TraceView from '../components/TraceView.jsx'
import FollowUp from '../components/FollowUp.jsx'
import { Bar, Mermaid, More, Score, Source, Tabs, Tag, toneFor } from '../components/ui.jsx'

const MODE = {
  bug: { label: 'Bug report', hint: 'Where the bug probably is, and a fix to review' },
  impact: { label: 'Change impact', hint: 'What depends on this code and could break' },
  explain: { label: 'Where / how', hint: 'Where this is handled in the code' },
}
const CHECKS = [
  ['file_exists', 'File exists'],
  ['symbol_exists', 'Function found'],
  ['lines_in_bounds', 'Lines valid'],
  ['in_retrieved_evidence', 'In retrieved code'],
  ['quote_matches_disk', 'Quote matches file'],
  ['fix_compiles', 'Fix compiles'],
]
const RISK_TONE = { High: 'risk', Medium: 'warn', Low: 'good' }

function CodeBox({ code, start = 1, tone }) {
  const lines = String(code || '').replace(/\n$/, '').split('\n')
  return (
    <div className={`codebox ${tone}`}>
      <pre>
        {lines.map((l, i) => (
          <div className="ln" key={i}><span>{start ? start + i : ''}</span><span>{l || ' '}</span></div>
        ))}
      </pre>
    </div>
  )
}

function Checks({ v }) {
  return (
    <div className="row" style={{ gap: 6 }}>
      {CHECKS.filter(([k]) => k in (v || {})).map(([k, label]) => (
        <span key={k} className={`check ${v[k] ? 'ok' : 'no'}`}>{v[k] ? '✓' : '✗'} {label}</span>
      ))}
    </div>
  )
}

function Finding({ c, mode }) {
  const isFallback = c.generated_by === 'fallback'
  return (
    <div className="card pad-lg stack">
      <div className="row between">
        <div className="row">
          <span className="display" style={{ fontSize: 26 }}>#{c.rank}</span>
          <div>
            <div className="mono" style={{ fontWeight: 600 }}>{c.symbol_name}</div>
            <div className="tiny muted mono">{c.file_path}:{c.line_start}-{c.line_end}</div>
          </div>
        </div>
        <div className="row">
          <Tag tone={c.confidence === 'high' ? 'good' : c.confidence === 'low' ? 'warn' : ''}>{c.confidence} confidence</Tag>
          <Source value={isFallback ? 'fallback' : 'llm'} />
        </div>
      </div>
      <p style={{ margin: 0, color: 'var(--ink-2)' }}>{c.why_problematic || c.root_cause_hypothesis}</p>
      <Checks v={c.verification} />
      <div className="grid g2">
        <div className="stack" style={{ gap: 6 }}>
          <div className="eyebrow" style={{ color: 'var(--risk)' }}>{mode === 'bug' ? 'Code now' : 'Relevant code'}</div>
          <CodeBox code={c.wrong_code} start={c.line_start} tone="before" />
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <div className="eyebrow" style={{ color: 'var(--good)' }}>{isFallback ? 'Notes (no AI fix)' : 'Suggested version'}</div>
          <CodeBox code={c.recommended_pattern || c.correct_code} start={0} tone="after" />
        </div>
      </div>
      {c.explanation_of_change && <div className="small"><strong>What changes:</strong> <span className="muted">{c.explanation_of_change}</span></div>}
    </div>
  )
}

function Impact({ out }) {
  const im = out.impact
  const flow = out.flow
  if (!im) return <div className="empty">No call-graph target could be resolved for this question.</div>
  return (
    <div className="stack-lg">
      <div className="grid g4">
        <div className="card stat"><div className="value">{im.blast_radius_score}<small>/100</small></div><div className="label">blast radius</div></div>
        <div className="card stat"><div className="value" style={{ color: `var(--${RISK_TONE[im.risk_level] || 'ink'})` }}>{im.risk_level}</div><div className="label">risk if <span className="mono">{im.target_symbol}</span> changes</div></div>
        <div className="card stat"><div className="value">{im.direct_callers_count}</div><div className="label">direct callers ({im.indirect_callers_count} indirect)</div></div>
        <div className="card stat"><div className="value">{(im.affected_tests || []).length}</div><div className="label">tests that cover it</div></div>
      </div>
      <div className="grid g2">
        <div className="card pad stack">
          <h3>Who calls <span className="mono">{im.target_symbol}</span></h3>
          {[...(im.direct_callers || []), ...(im.indirect_callers || [])].map((c, i) => (
            <div key={i} className="row between small" style={{ borderBottom: '1px dashed var(--line)', paddingBottom: 6 }}>
              <span className="mono">{c.symbol_name}</span>
              <span className="muted mono tiny">{c.file_path}:{c.line} · {c.depth === 1 ? 'direct' : `depth ${c.depth}`}{c.is_entrypoint ? ' · entry point' : ''}</span>
            </div>
          ))}
          {!(im.direct_callers || []).length && <div className="small muted">No callers found in the scanned files.</div>}
          {(im.affected_entrypoints || []).length > 0 && <div className="tiny muted">Entry points affected: {im.affected_entrypoints.join(', ')}</div>}
        </div>
        <div className="card pad stack">
          <h3>Call flow</h3>
          {(flow?.hops || []).map((h) => (
            <div key={h.step_number} className="row small" style={{ flexWrap: 'nowrap' }}>
              <span className="mono muted" style={{ minWidth: 22 }}>{h.step_number}</span>
              <span className="mono" style={{ flex: 1 }}>{h.symbol_name}</span>
              <Tag tone={h.status === 'unresolved' ? 'warn' : ''}>{h.relationship.replace(/_/g, ' ')}</Tag>
            </div>
          ))}
          {!(flow?.hops || []).length && <div className="small muted">No flow could be traced.</div>}
        </div>
      </div>
      {im.mermaid_diagram && <div className="card pad stack"><h3>Impact graph</h3><Mermaid chart={im.mermaid_diagram} /></div>}
      {(im.recommendations || []).length > 0 && (
        <div className="card pad stack"><h3>Before you change it</h3><ul className="list small">{im.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
      )}
    </div>
  )
}

function Overview({ out, state, goTo }) {
  const critic = out.critic || {}
  const cands = out.candidates || []
  const top = cands[0]
  const mode = MODE[out.question_mode] || MODE.bug
  const checks = cands.flatMap((c) => Object.entries(c.verification || {}).filter(([k]) => CHECKS.some(([x]) => x === k)))
  const passed = checks.filter(([, v]) => v).length
  const score = Math.round((critic.grounding_score || 0) * 100)
  const im = out.impact
  const idx = out.indexed_summary || {}
  const revised = (state.execution_trace || []).find((t) => t.status === 'revised')
  return (
    <div className="stack-lg">
      <div className="card pad-lg verdict">
        <div className="stack" style={{ gap: 10 }}>
          <div className="eyebrow">Grounding score</div>
          <Score value={score} unit="%" max={100} />
          <div className={`state ${critic.is_valid ? 'good' : 'warn'}`}>{critic.is_valid ? 'Checked against your files' : 'Needs a second look'}</div>
        </div>
        <div className="stack">
          <div className="row"><span className="eyebrow accent">{mode.label}</span><span className="tiny muted">{mode.hint}</span></div>
          <p style={{ margin: 0, fontSize: 18, lineHeight: 1.5 }}>{out.summary}</p>
          <div className="row tiny">
            <Tag>{passed}/{checks.length} checks passed</Tag>
            <Tag>{out.retrieval_backend === 'sentence-transformers' ? 'MiniLM + BM25 search' : 'TF-IDF + BM25 search'}</Tag>
            {revised && <Tag tone="accent">Critic sent it back once</Tag>}
            <Tag tone="good">Read-only, nothing edited</Tag>
          </div>
        </div>
      </div>
      <div className="grid g3">
        <button className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 6 }} onClick={() => goTo('findings')}>
          <div className="eyebrow accent">Top location</div>
          {top ? (
            <>
              <div className="mono" style={{ fontWeight: 600 }}>{top.symbol_name}</div>
              <div className="tiny muted mono">{top.file_path}:{top.line_start}-{top.line_end}</div>
              <div className="small muted clamp-2">{top.why_problematic || top.root_cause_hypothesis}</div>
            </>
          ) : <div className="small muted">No location named. See retrieved code below.</div>}
        </button>
        <button className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 6 }} onClick={() => goTo('impact')}>
          <div className="eyebrow" style={{ color: 'var(--risk)' }}>Blast radius</div>
          {im ? (
            <>
              <div className="row" style={{ alignItems: 'baseline' }}><span className="display" style={{ fontSize: 40, lineHeight: 1 }}>{im.blast_radius_score}</span><Tag tone={RISK_TONE[im.risk_level]}>{im.risk_level} risk</Tag></div>
              <div className="small muted">{im.direct_callers_count} direct callers of <span className="mono">{im.target_symbol}</span></div>
            </>
          ) : <div className="small muted">Not computed.</div>}
        </button>
        <div className="card pad stack" style={{ gap: 6 }}>
          <div className="eyebrow">Codebase scanned</div>
          <div className="row" style={{ alignItems: 'baseline', gap: 6 }}><span className="display" style={{ fontSize: 40, lineHeight: 1 }}>{idx.total_files ?? '?'}</span><span className="muted small">files</span></div>
          <div className="small muted">{idx.total_chunks ?? '?'} functions and classes, parsed with Python's AST</div>
        </div>
      </div>
      {!cands.length && (out.retrieved_locations || []).length > 0 && (
        <div className="card pad stack">
          <h3>Closest code the search found</h3>
          {out.retrieved_locations.map((l, i) => <div key={i} className="mono small">{l.file_path}:{l.line_start}-{l.line_end} <span className="muted">{l.symbol_name}</span></div>)}
        </div>
      )}
      <div className="card pad stack">
        <h3>What the critic checked, without AI</h3>
        <div className="grid g3">
          <div><Bar value={critic.total_verified || 0} max={critic.total_checked || 1} tone="good" /><div className="tiny muted" style={{ marginTop: 5 }}>{critic.total_verified}/{critic.total_checked} locations exist on disk</div></div>
          <div><Bar value={critic.code_quote_matches || 0} max={critic.total_checked || 1} tone="good" /><div className="tiny muted" style={{ marginTop: 5 }}>{critic.code_quote_matches}/{critic.total_checked} quoted code blocks match the file</div></div>
          <div><Bar value={critic.fixes_compiling || 0} max={critic.fixes_checked || 1} tone="good" /><div className="tiny muted" style={{ marginTop: 5 }}>{critic.fixes_compiling}/{critic.fixes_checked} suggested fixes compile</div></div>
        </div>
        {(critic.flags || []).length > 0 && <More label={`Flags (${critic.flags.length})`}><ul className="list small">{critic.flags.map((f, i) => <li key={i}>{f}</li>)}</ul></More>}
      </div>
    </div>
  )
}

export default function CodeResult({ run, repoPath }) {
  const state = run.result
  const out = state.final_output || {}
  const [tab, setTab] = useState('overview')
  if (out.type === 'error' || out.error) {
    return <div className="card pad"><h3>Could not run</h3><p className="small muted">{out.error}</p></div>
  }
  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'findings', label: 'Findings', count: (out.candidates || []).length },
    { id: 'impact', label: 'Impact' },
    { id: 'trace', label: 'How it ran' },
  ]
  const go = (id) => { setTab(id); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  return (
    <div className="stack-lg fade-in">
      <div className="eyebrow">Report · session {state.session_id}</div>
      <Tabs tabs={tabs} value={tab} onChange={go} />
      {tab === 'overview' && <Overview out={out} state={state} goTo={go} />}
      {tab === 'findings' && (
        <div className="stack-lg">
          {(out.candidates || []).map((c) => <Finding key={`${c.rank}-${c.symbol_name}`} c={c} mode={out.question_mode} />)}
          {!(out.candidates || []).length && <div className="empty">The AI named no location for this question.</div>}
        </div>
      )}
      {tab === 'impact' && <Impact out={out} />}
      {tab === 'trace' && <TraceView state={state} calls={run.calls} />}
      <FollowUp pillar="code" sessionId={state.session_id} repoPath={out.local_repo_path || repoPath} finalOutput={out} />
    </div>
  )
}
