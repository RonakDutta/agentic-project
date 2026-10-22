import { useState } from 'react'
import Papers from './Papers.jsx'
import TraceView from '../components/TraceView.jsx'
import FollowUp from '../components/FollowUp.jsx'
import { Bar, Mermaid, More, SafeLink, Score, Source, Tabs, Tag, downloadText, toneFor } from '../components/ui.jsx'

const SEV_TONE = { Critical: 'risk', High: 'risk', Medium: 'warn', Low: '' }
const SECTION_NAMES = {
  idea: 'Idea brief', market: 'Market', prior_art: 'Research papers', kill_report: "Devil's advocate",
  reconciliation: 'Judge', scorecard: 'Scorecard', prd: 'PRD', roadmap: 'Roadmap',
}

function shortText(s, n = 140) {
  const t = String(s || '')
  return t.length > n ? `${t.slice(0, n).trim()}...` : t
}

function Overview({ out, goTo }) {
  const sc = out.scorecard || {}
  const pa = out.prior_art
  const closest = pa?.papers?.[0]
  const flaw = (out.kill_report?.fatal_flaws || [])[0]
  const mustDo = (out.reconciliation?.must_have_mitigations || [])[0]
  const prov = out.provenance || {}
  return (
    <div className="stack-lg">
      <div className="card pad-lg verdict">
        <div className="stack" style={{ gap: 10 }}>
          <div className="eyebrow">Feasibility score</div>
          <Score value={sc.total_score ?? out.feasibility_score ?? 0} />
          <div className={`verdict-word ${sc.verdict || out.feasibility_verdict}`}>{sc.verdict || out.feasibility_verdict}</div>
        </div>
        <div className="stack">
          <div className="eyebrow accent">Verdict</div>
          <h2 className="display">{out.project_title}</h2>
          <p style={{ margin: 0, color: 'var(--ink-2)' }}>{shortText(sc.verdict_summary || out.core_value_prop, 220)}</p>
          <div className="row tiny">
            <Tag>Evidence confidence: {sc.evidence_confidence || out.evidence_confidence}</Tag>
            <Tag>{out.live_citation_count || 0} live web sources</Tag>
            {pa && <Tag tone="accent">{(pa.papers || []).length} research papers</Tag>}
            <Tag tone="good">Score computed in code</Tag>
          </div>
        </div>
      </div>

      <div className="grid g3">
        <button type="button" className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 8 }} onClick={() => goTo('papers')}>
          <div className="eyebrow accent">Novelty vs research</div>
          <div className="display" style={{ fontSize: 40, lineHeight: 1 }}>{pa?.novelty_index ?? 'n/a'}<span className="muted" style={{ fontSize: 15, fontWeight: 500 }}> / 100</span></div>
          <div className="small">{pa?.novelty_band || 'Research check not run'}</div>
          {closest && <div className="tiny muted clamp-2">Closest: {closest.title}</div>}
          <div className="tiny" style={{ color: 'var(--info)' }}>See the papers</div>
        </button>
        <div className="card pad stack" style={{ gap: 8 }}>
          <div className="eyebrow" style={{ color: 'var(--risk)' }}>Biggest risk</div>
          {flaw ? (
            <>
              <div style={{ fontWeight: 650 }}>{flaw.title}</div>
              <div className="small muted clamp-3">{flaw.argument}</div>
              <div><Tag tone={SEV_TONE[flaw.severity]}>{flaw.severity}</Tag></div>
            </>
          ) : <div className="small muted">No fatal flaw found.</div>}
        </div>
        <div className="card pad stack" style={{ gap: 8 }}>
          <div className="eyebrow" style={{ color: 'var(--good)' }}>Must do first</div>
          <div className="small">{mustDo || (sc.recommended_actions || [])[0] || 'No precondition listed.'}</div>
          <div className="tiny muted">Judge's verdict: {out.reconciliation?.verdict}</div>
        </div>
      </div>

      {closest && (
        <div className="card pad row between" style={{ gap: 16 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="eyebrow accent">Closest paper</div>
            <SafeLink href={closest.url} className="paper-title">{closest.title}</SafeLink>
            <div className="tiny muted">{closest.year} · similarity {closest.similarity.toFixed(2)} · {closest.venue || closest.source}</div>
          </div>
          <div className="row">
            <SafeLink href={closest.url} className="btn sm">Open</SafeLink>
            {closest.pdf_url && <SafeLink href={closest.pdf_url} className="btn sm">PDF</SafeLink>}
          </div>
        </div>
      )}

      <div className="card pad stack">
        <div className="row between"><h3>Score breakdown</h3><button type="button" className="chip" onClick={() => goTo('score')}>Details</button></div>
        <div className="grid g2" style={{ columnGap: 28 }}>
          {(sc.categories || []).map((c) => (
            <div key={c.category_name} className="stack" style={{ gap: 5 }}>
              <div className="row between small"><span>{c.category_name}</span><span className="mono">{c.score}/{c.max_score}</span></div>
              <Bar value={c.score} max={c.max_score} tone={toneFor((c.score / c.max_score) * 100)} />
            </div>
          ))}
        </div>
      </div>

      <div className="card pad stack" style={{ gap: 10 }}>
        <h3>Where each part came from</h3>
        <div className="row">
          {Object.entries(prov).map(([k, v]) => (
            <span key={k} className="row tiny" style={{ gap: 5 }}><span className="muted">{SECTION_NAMES[k] || k}</span><Source value={v} /></span>
          ))}
        </div>
      </div>
    </div>
  )
}

function Scorecard({ sc }) {
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>{sc.rubric_disclaimer}</p>
      {(sc.categories || []).map((c) => (
        <div key={c.category_name} className="card pad stack" style={{ gap: 8 }}>
          <div className="row between">
            <h3>{c.category_name}</h3>
            <span className="display" style={{ fontSize: 24 }}>{c.score}<span className="muted small" style={{ fontWeight: 500 }}>/{c.max_score}</span></span>
          </div>
          <Bar value={c.score} max={c.max_score} tone={toneFor((c.score / c.max_score) * 100)} />
          <div className="grid g2">
            <ul className="list small" style={{ listStyle: 'none', paddingLeft: 0 }}>
              {(c.criteria_met || []).map((x, i) => <li key={i}><span style={{ color: 'var(--good)' }}>✓</span> {x}</li>)}
            </ul>
            <ul className="list small" style={{ listStyle: 'none', paddingLeft: 0 }}>
              {(c.gaps || []).map((x, i) => <li key={i}><span style={{ color: 'var(--risk)' }}>✗</span> {x}</li>)}
            </ul>
          </div>
        </div>
      ))}
      {[...(sc.verdict_notes || []), ...(sc.confidence_notes || [])].length > 0 && (
        <ul className="list tiny muted">{[...(sc.verdict_notes || []), ...(sc.confidence_notes || [])].map((n, i) => <li key={i}>{n}</li>)}</ul>
      )}
    </div>
  )
}

function Market({ out }) {
  const live = (out.citations || []).filter((c) => c.is_live)
  return (
    <div className="stack-lg">
      <div className="stack">
        <div className="row between"><h3>Competitors</h3><Source value={out.provenance?.market} /></div>
        <div className="grid g3">
          {(out.competitors || []).map((c) => (
            <div key={c.name} className="card pad stack" style={{ gap: 8 }}>
              <div style={{ fontWeight: 650 }}>{c.reference_url ? <SafeLink href={c.reference_url}>{c.name}</SafeLink> : c.name}</div>
              <div className="small muted clamp-3">{c.summary}</div>
              <div className="small"><span style={{ color: 'var(--good)', fontWeight: 600 }}>Your gap: </span>{shortText(c.gaps, 120)}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="stack">
        <h3>Suggested tech stack</h3>
        <div className="grid g4">
          {Object.entries(out.tech_stack || {}).map(([layer, v]) => (
            <div key={layer} className="card pad stack" style={{ gap: 6 }}>
              <div className="eyebrow">{layer.replace(/_/g, ' ')}</div>
              <div style={{ fontWeight: 600 }}>{v.choice}</div>
              <More label="Why"><div className="small muted">{v.rationale}</div><div className="small" style={{ marginTop: 6 }}><strong>Trade-off:</strong> {v.tradeoffs}</div></More>
            </div>
          ))}
        </div>
      </div>
      <div className="card pad stack">
        <div className="row between"><h3>Web sources</h3><span className="tiny muted">{live.length} live · search: {out.search_backend}</span></div>
        <ul className="list small">
          {(out.citations || []).map((c, i) => (
            <li key={i}><SafeLink href={c.url}>{c.title}</SafeLink> {!c.is_live && <Tag tone="warn">offline reference</Tag>}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function Risks({ out }) {
  const kr = out.kill_report || {}
  const rc = out.reconciliation || {}
  return (
    <div className="stack-lg">
      <div className="card pad stack">
        <div className="row between"><div className="eyebrow" style={{ color: 'var(--risk)' }}>Devil's advocate says</div><Source value={kr.generation_source} /></div>
        <p style={{ margin: 0, fontSize: 17 }}>{kr.bear_case_summary}</p>
      </div>
      <div className="grid g3">
        {(kr.fatal_flaws || []).map((f, i) => (
          <div key={i} className="card pad stack" style={{ gap: 8 }}>
            <div className="row between"><Tag tone={SEV_TONE[f.severity]}>{f.severity}</Tag><span className="tiny muted">{f.category}</span></div>
            <div style={{ fontWeight: 650 }}>{f.title}</div>
            <div className="small muted clamp-3">{f.argument}</div>
          </div>
        ))}
      </div>
      <div className="card pad stack">
        <div className="row between"><h3>Judge's verdict: {rc.verdict}</h3><Source value={rc.generation_source} /></div>
        <div className="grid g2">
          <div><div className="eyebrow" style={{ color: 'var(--good)' }}>Must do</div><ul className="list small">{(rc.must_have_mitigations || []).map((m, i) => <li key={i}>{m}</li>)}</ul></div>
          <div><div className="eyebrow">Trade-offs</div><ul className="list small">{(rc.key_tradeoffs || []).map((m, i) => <li key={i}>{m}</li>)}</ul></div>
        </div>
      </div>
      <div className="card pad stack">
        <h3>Risk matrix</h3>
        {(out.risks || []).map((r, i) => (
          <div key={i} className="row" style={{ alignItems: 'flex-start', borderBottom: '1px solid var(--line)', paddingBottom: 8, flexWrap: 'nowrap' }}>
            <Tag tone={SEV_TONE[r.severity]}>{r.severity}</Tag>
            <div className="small" style={{ flex: 1 }}><strong>{r.category}:</strong> {r.risk}<div className="muted">Fix: {r.mitigation}</div></div>
          </div>
        ))}
      </div>
    </div>
  )
}

const DIAGRAMS = [
  ['architecture_diagram_mermaid', 'Architecture'],
  ['component_diagram_mermaid', 'Components'],
  ['dataflow_diagram_mermaid', 'Data flow'],
]

function Plan({ out }) {
  const prd = out.prd || {}
  const [diagram, setDiagram] = useState(DIAGRAMS[0][0])
  return (
    <div className="stack-lg">
      <div className="grid g3">
        {(out.phases || []).map((p) => (
          <div key={p.phase_number} className="card pad stack" style={{ gap: 8 }}>
            <div className="row between"><span className="eyebrow accent">Phase {p.phase_number}</span><Tag>{p.duration_weeks}</Tag></div>
            <div style={{ fontWeight: 650 }}>{p.phase_name}</div>
            <ul className="list small">{(p.deliverables || []).slice(0, 4).map((d, i) => <li key={i}>{d}</li>)}</ul>
            <div className="tiny muted">Done when: {p.exit_criteria}</div>
          </div>
        ))}
      </div>
      <div className="card pad stack">
        <div className="row between">
          <h3>System diagrams</h3>
          <div className="switch">
            {DIAGRAMS.map(([k, label]) => <button key={k} className={diagram === k ? 'on' : ''} onClick={() => setDiagram(k)}>{label}</button>)}
          </div>
        </div>
        <Mermaid key={diagram} chart={prd[diagram]} />
      </div>
      <div className="card pad stack">
        <div className="row between"><h3>Product requirements</h3><Source value={prd.generation_source || out.provenance?.prd} /></div>
        <p style={{ margin: 0, color: 'var(--ink-2)' }}>{prd.product_vision}</p>
        <div className="stack" style={{ gap: 6 }}>
          {(prd.functional_requirements || []).map((r) => (
            <div key={r.req_id} className="row small" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <span className="mono muted" style={{ minWidth: 54 }}>{r.req_id}</span>
              <span style={{ flex: 1 }}><strong style={{ fontWeight: 600 }}>{r.title}</strong> <span className="muted">{shortText(r.description, 110)}</span></span>
              <Tag tone={r.priority === 'Must Have' ? 'accent' : ''}>{r.priority}</Tag>
            </div>
          ))}
        </div>
        <More label={`User stories (${(prd.user_stories || []).length})`}>
          <div className="stack" style={{ gap: 8 }}>
            {(prd.user_stories || []).map((s) => (
              <div key={s.story_id} className="soft small" style={{ padding: 10 }}>
                <strong>{s.story_id}</strong> As a {s.persona}, I want to {s.want} so that {s.so_that}.
              </div>
            ))}
          </div>
        </More>
      </div>
    </div>
  )
}

export default function StartupResult({ run }) {
  const state = run.result
  const out = state.final_output || {}
  const [tab, setTab] = useState('overview')
  const pa = out.prior_art
  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'papers', label: 'Research papers', count: pa?.papers?.length ?? 0 },
    { id: 'score', label: 'Scorecard' },
    { id: 'market', label: 'Market' },
    { id: 'risks', label: 'Risks' },
    { id: 'plan', label: 'Plan' },
    { id: 'trace', label: 'How it ran' },
  ]
  const go = (id) => { setTab(id) }
  return (
    <div className="stack-lg fade-in">
      <div className="row between">
        <div className="eyebrow">Report · session {state.session_id}</div>
        <div className="row">
          {out.full_report_markdown && <button className="btn sm" onClick={() => downloadText(`${(out.project_title || 'report').replace(/\W+/g, '_')}.md`, out.full_report_markdown, 'text/markdown')}>Download report</button>}
        </div>
      </div>
      <Tabs tabs={tabs} value={tab} onChange={go} />
      {tab === 'overview' && <Overview out={out} goTo={go} />}
      {tab === 'papers' && <Papers pa={pa} title={out.project_title} />}
      {tab === 'score' && <Scorecard sc={out.scorecard || {}} />}
      {tab === 'market' && <Market out={out} />}
      {tab === 'risks' && <Risks out={out} />}
      {tab === 'plan' && <Plan out={out} />}
      {tab === 'trace' && <TraceView state={state} calls={run.calls} />}
      <FollowUp pillar="startup" sessionId={state.session_id} finalOutput={out} />
    </div>
  )
}
