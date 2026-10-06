import React, { useEffect, useState } from 'react'
import MermaidDiagram from './MermaidDiagram.jsx'

function ScoreBar({ pct }) {
  const [width, setWidth] = useState('0%')
  useEffect(() => {
    const t = requestAnimationFrame(() => requestAnimationFrame(() => setWidth(`${pct}%`)))
    return () => cancelAnimationFrame(t)
  }, [pct])
  return (
    <div className="w-36 sm:w-44 bg-slate-900/90 h-2 rounded border border-borderSubtle/60 overflow-hidden">
      <div className="bg-blue-600 h-2 rounded score-bar" style={{ width }} />
    </div>
  )
}

function verdictBadgeClass(verdict) {
  if (verdict === 'GO') return 'tag good'
  if (verdict === 'PIVOT') return 'tag warn'
  return 'tag risk'
}

export default function IdeaView({ out }) {
  const [tab, setTab] = useState('architecture')
  useEffect(() => { setTab('architecture') }, [out])

  const sc = out.scorecard || {}
  const scoreVal = sc.total_score !== undefined ? sc.total_score : (out.feasibility_score || 0)
  const verdictVal = sc.verdict || out.feasibility_verdict || 'GO'
  const disclaimerVal = sc.rubric_disclaimer || out.rubric_disclaimer || 'Feasibility Score: based on the defined project rubric.'
  const kill = out.kill_report || {}
  const rec = out.reconciliation || {}
  const prd = out.prd || {}

  const chart = tab === 'architecture'
    ? prd.architecture_diagram_mermaid || ''
    : tab === 'component'
      ? prd.component_diagram_mermaid || ''
      : prd.dataflow_diagram_mermaid || ''

  return (
    <div className="space-y-12">
      <div className="panel p-8 sm:p-10 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-borderSubtle pb-6">
          <div className="space-y-1">
            <span className="label is-accent">Structured Project Brief</span>
            <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight">
              {out.project_title || 'Validated Engineering Concept'}
            </h2>
          </div>
        </div>

        <div className="space-y-2">
          <span className="label">Problem Statement</span>
          <p className="text-sm sm:text-base text-zinc-200 leading-relaxed">{out.problem_statement || ''}</p>
        </div>

        <div className="rule pt-4">
          <span className="label">Why this idea is worth building</span>
          <p className="text-sm sm:text-base text-white font-medium">{out.core_value_prop || ''}</p>
        </div>
      </div>

      <div className="panel p-8 sm:p-10 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-borderSubtle pb-4">
          <div>
            <span className="label is-accent">Evaluation</span>
            <h3 className="text-xl font-bold text-white mt-1">Feasibility Scorecard</h3>
          </div>
          <div className="flex items-center space-x-3">
            <div className="text-2xl font-semibold text-white">{scoreVal}/100</div>
            <span className={verdictBadgeClass(verdictVal)}>{verdictVal}</span>
          </div>
        </div>

        <div className="subpanel p-3.5 flex items-center gap-3">
          <svg className="w-4 h-4 text-zinc-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-xs text-zinc-400">{disclaimerVal}</p>
        </div>

        <p className="text-sm text-zinc-200 leading-relaxed">
          {sc.verdict_summary || 'Evaluated against the 7-category project rubric.'}
        </p>

        <div className="space-y-2 pt-2">
          <span className="label">Score Breakdown:</span>
          <div className="subpanel overflow-hidden divide-y divide-borderSubtle">
            {(sc.categories || []).map((cat, i) => {
              const pct = Math.round((cat.score / cat.max_score) * 100)
              return (
                <div key={i} className="p-4 sm:p-5 hover:bg-surface/40 transition space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-white font-mono">{cat.category_name}</span>
                      <span className="text-[11px] font-mono text-zinc-400">({cat.score} / {cat.max_score} pts)</span>
                    </div>
                    <ScoreBar pct={pct} />
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">{cat.rationale || ''}</p>
                </div>
              )
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-borderSubtle/60">
          <div className="space-y-2">
            <span className="label is-good">Key Strengths:</span>
            <div className="flex flex-wrap gap-2">
              {(sc.key_strengths || []).map((s, i) => <span key={i} className="tag good">{s}</span>)}
            </div>
          </div>
          <div className="space-y-2">
            <span className="label is-warn">Key Risks:</span>
            <div className="flex flex-wrap gap-2">
              {(sc.key_risks || []).map((r, i) => <span key={i} className="tag warn">{r}</span>)}
            </div>
          </div>
        </div>
      </div>

      <div className="panel p-8 sm:p-10 space-y-6">
        <div className="border-b border-borderSubtle pb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="label is-risk">Risk Analysis</span>
            <h3 className="text-xl font-bold text-white mt-1">Risks & Final Verdict</h3>
          </div>
          <span className="tag">{rec.verdict || 'Synthesis Complete'}</span>
        </div>

        <div className="callout callout-risk space-y-2">
          <div className="flex items-center justify-between">
            <span className="label is-risk">Worst-Case Scenario</span>
            <span className="text-xs text-zinc-400">Why this idea might struggle</span>
          </div>
          <p className="text-sm text-zinc-200 leading-relaxed">
            {kill.bear_case_summary || out.bear_case_critic || 'Bear-case stress testing active.'}
          </p>
        </div>

        <div className="space-y-3">
          <span className="label">Identified Fatal Flaws:</span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {(kill.fatal_flaws || []).map((flaw, i) => {
              const sevClass = flaw.severity === 'CRITICAL' ? 'tag risk' : flaw.severity === 'HIGH' ? 'tag warn' : 'tag info'
              return (
                <div key={i} className="subpanel p-4 sm:p-5 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-bold text-white">{flaw.title}</h4>
                    <span className={sevClass}>{flaw.severity}</span>
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">{flaw.reason}</p>
                  <div className="pt-1 text-[11px] text-zinc-400">
                    <span className="text-zinc-500 font-semibold">How to test it:</span>
                    <span className="text-zinc-300 ml-1">{flaw.mitigation_test}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="space-y-2 pt-2">
          <span className="label">Competitor & Replication Threats:</span>
          <ul className="list-disc list-inside space-y-1.5 pl-2">
            {(kill.incumbent_threats || []).map((t, i) => <li key={i} className="text-xs text-zinc-300">{t}</li>)}
          </ul>
        </div>

        <div className="callout callout-note space-y-4">
          <div className="border-b border-borderSubtle/60 pb-3 flex items-center justify-between">
            <span className="label is-accent">Balanced Final Verdict</span>
            <span className="text-xs text-zinc-500">Pros and cons</span>
          </div>
          <p className="text-sm text-zinc-200 leading-relaxed">{rec.synthesis_rationale || ''}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            <div className="space-y-1.5">
              <span className="label is-good">Must-Have Steps to Succeed:</span>
              <ul className="list-disc list-inside space-y-1 pl-2">
                {(rec.must_have_mitigations || []).map((m, i) => <li key={i} className="text-xs text-zinc-200 leading-relaxed">{m}</li>)}
              </ul>
            </div>
            <div className="space-y-1.5">
              <span className="label is-warn">Key Tradeoffs:</span>
              <ul className="list-disc list-inside space-y-1 pl-2">
                {(rec.key_tradeoffs || []).map((t, i) => <li key={i} className="text-xs text-zinc-300 leading-relaxed">{t}</li>)}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <div className="panel p-8 sm:p-10 space-y-6">
        <div className="border-b border-borderSubtle pb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="label is-accent">Product plan</span>
            <h3 className="text-xl font-bold text-white mt-1">Product requirements and architecture</h3>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="subpanel p-5 space-y-1">
            <span className="label">Product Vision</span>
            <p className="text-xs sm:text-sm text-zinc-200 leading-relaxed">{prd.product_vision || out.problem_statement || ''}</p>
          </div>
          <div className="subpanel p-5 space-y-1">
            <span className="label">Target Audience Profile</span>
            <p className="text-xs sm:text-sm text-zinc-200 leading-relaxed">{prd.target_audience_summary || ''}</p>
          </div>
        </div>

        <div className="space-y-3 pt-2">
          <span className="label">User stories, with acceptance criteria</span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {(prd.user_stories || []).map((story, i) => (
              <div key={i} className="subpanel p-5 space-y-3">
                <div className="flex items-center justify-between border-b border-borderSubtle/60 pb-2">
                  <span className="label is-accent">{story.story_id}</span>
                  <span className="text-[11px] font-mono text-zinc-400">{story.persona}</span>
                </div>
                <div className="text-xs text-zinc-200 space-y-1">
                  <p><strong className="text-zinc-400 text-[11px] font-semibold">Needs:</strong> {story.want}</p>
                  <p><strong className="text-zinc-400 text-[11px] font-semibold">Goal:</strong> {story.so_that}</p>
                </div>
                <div className="pt-2 border-t border-borderSubtle/60 space-y-1.5">
                  <span className="label is-good">This story is done when:</span>
                  <ul className="space-y-1">
                    {(story.acceptance_criteria || []).map((c, j) => (
                      <li key={j} className="flex items-start space-x-2 text-xs text-zinc-300">
                        <span className="text-blue-400 mt-0.5">✓</span>
                        <span>{c}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3 pt-2">
          <span className="label">Functional requirements</span>
          <div className="subpanel overflow-hidden divide-y divide-borderSubtle">
            {(prd.functional_requirements || []).map((fr, i) => {
              const prioClass = fr.priority === 'Must Have' ? 'tag info' : 'tag'
              return (
                <div key={i} className="p-4 sm:p-5 hover:bg-surface/40 transition space-y-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-mono font-bold text-blue-400">{fr.req_id}</span>
                      <span className="text-xs font-bold text-white">{fr.title}</span>
                    </div>
                    <span className={prioClass}>{fr.priority}</span>
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">{fr.description}</p>
                </div>
              )
            })}
          </div>
        </div>

        <div className="space-y-2 pt-2">
          <span className="label">Non-functional requirements</span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.entries(prd.non_functional_requirements || {}).map(([key, val]) => (
              <div key={key} className="subpanel p-4 space-y-1">
                <span className="label">{key}</span>
                <p className="text-xs text-zinc-200 leading-relaxed">{val}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3 pt-4 border-t border-borderSubtle/60">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="label">Architectural Models (Mermaid.js):</span>
            <div className="tabs w-full sm:w-auto">
              {[
                { id: 'architecture', label: 'System architecture' },
                { id: 'component', label: 'Component map' },
                { id: 'dataflow', label: 'Data flow' },
              ].map((t) => (
                <button key={t.id} onClick={() => setTab(t.id)} className={tab === t.id ? 'tab is-active' : 'tab'}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className="subpanel p-4 min-h-[160px] flex items-center justify-center">
            <div className="w-full">
              <MermaidDiagram key={`${tab}-${out.project_title}`} chart={chart} />
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="border-b border-borderSubtle pb-3 flex items-baseline justify-between">
          <h3 className="text-base sm:text-lg font-bold text-white">Target Personas</h3>
          <span className="text-xs text-zinc-500">Who experiences this problem</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {(out.target_personas || []).map((p, i) => (
            <div key={i} className="subpanel p-6 space-y-3">
              <div className="label is-accent">{p.persona}</div>
              <div className="space-y-1">
                <span className="label">Main problem</span>
                <p className="text-sm text-zinc-200 leading-relaxed">{p.pain_point}</p>
              </div>
              <div className="pt-2 border-t border-borderSubtle/60 space-y-1">
                <span className="label is-good">What they gain</span>
                <p className="text-xs text-zinc-300 leading-relaxed">{p.expected_benefit}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        <div className="border-b border-borderSubtle pb-3 flex items-baseline justify-between">
          <h3 className="text-base sm:text-lg font-bold text-white">Competitors & Market Research</h3>
          <span className="text-xs text-zinc-500">Who else solves this, and how we differ</span>
        </div>
        <div className="subpanel overflow-hidden">
          <div className="divide-y divide-borderSubtle">
            {(out.competitors || []).map((c, i) => (
              <div key={i} className="p-5 sm:p-6 space-y-2 hover:bg-surface/40 transition">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h4 className="font-bold text-white text-sm">{c.name}</h4>
                  <span className="text-[11px] text-zinc-500">Found from public sources</span>
                </div>
                <p className="text-sm text-zinc-300 leading-relaxed">{c.summary || ''}</p>
                <div className="pt-1 flex items-baseline space-x-2 text-xs">
                  <span className="label is-inline is-accent" style={{ margin: 0 }}>How we are different:</span>
                  <span className="text-zinc-200">{c.gaps || 'Built around your exact requirements'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="border-b border-borderSubtle pb-3 flex items-baseline justify-between">
          <h3 className="text-base sm:text-lg font-bold text-white">Recommended Tech Stack</h3>
          <span className="text-xs text-zinc-500">What we would use in production, and why</span>
        </div>
        <div className="subpanel overflow-hidden">
          <div className="divide-y divide-borderSubtle">
            {Object.entries(out.tech_stack || {}).map(([category, item]) => (
              <div key={category} className="p-5 sm:p-6 space-y-2 hover:bg-surface/40 transition">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="label is-accent">{category}</span>
                  <span className="tag info">{item.choice || ''}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1 text-xs sm:text-sm">
                  <div>
                    <span className="label">Why this choice:</span>
                    <p className="text-zinc-300 leading-relaxed mt-0.5">{item.rationale || ''}</p>
                  </div>
                  <div>
                    <span className="label is-warn">What you give up:</span>
                    <p className="text-zinc-400 leading-relaxed mt-0.5">{item.tradeoffs || 'Standard operational overhead'}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-5">
        <div className="border-b border-borderSubtle pb-3 flex items-baseline justify-between">
          <h3 className="text-base sm:text-lg font-bold text-white">Development Roadmap & Major Risks</h3>
          <span className="text-xs text-zinc-500">Timeline, and what could go wrong</span>
        </div>

        <div className="space-y-4">
          {(out.phases || []).map((ph, i) => (
            <div key={i} className="subpanel p-6 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-borderSubtle/60 pb-3">
                <div>
                  <span className="label is-accent">Phase {ph.phase_number}</span>
                  <h4 className="font-bold text-base text-white mt-0.5">{ph.phase_name}</h4>
                </div>
                <span className="tag">{ph.duration_weeks}</span>
              </div>
              <div className="space-y-1.5">
                <span className="label">What gets built:</span>
                <ul className="list-disc list-inside space-y-1 text-sm text-zinc-200 leading-relaxed">
                  {(ph.deliverables || []).map((d, j) => <li key={j}>{d}</li>)}
                </ul>
              </div>
              <div className="pt-2 rule flex items-baseline gap-2 text-xs">
                <span className="label is-inline is-good" style={{ margin: 0 }}>Done when:</span>
                <span className="text-zinc-200">{ph.exit_criteria}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-2 pt-2">
          <span className="label">Identified Vulnerabilities & Mitigations</span>
          <div className="subpanel overflow-hidden">
            <div className="divide-y divide-borderSubtle">
              {(out.risks || []).map((r, i) => (
                <div key={i} className="p-5 sm:p-6 space-y-2 hover:bg-surface/40 transition">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h4 className="text-sm font-bold text-white">{r.risk}</h4>
                    <span className="tag">{r.category}: {r.severity}</span>
                  </div>
                  <div className="flex items-baseline gap-2 text-xs sm:text-sm">
                    <span className="label is-inline is-accent" style={{ margin: 0 }}>How to handle it:</span>
                    <span className="text-zinc-300">{r.mitigation}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="panel p-8 space-y-3">
        <div className="flex items-center justify-between border-b border-borderSubtle pb-3">
          <h3 className="section-title">What to do next</h3>
          <span className="text-xs text-zinc-500">Practical steps before you build</span>
        </div>
        <ul className="list-disc list-inside text-sm text-zinc-200 space-y-2 leading-relaxed pt-1">
          {(out.evaluation_tips || []).map((tip, i) => <li key={i}>{tip}</li>)}
        </ul>
      </div>
    </div>
  )
}
