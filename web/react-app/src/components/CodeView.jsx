import React from 'react'

export default function CodeView({ out }) {
  const critic = out.critic || {}
  const candidates = out.candidates || []
  return (
    <div className="space-y-8">
      <div className="panel p-8 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-borderSubtle pb-4">
          <div>
            <h3 className="text-xl font-bold text-white">Codebase Diagnosis Summary</h3>
            <p className="text-xs text-zinc-400 mt-0.5">Where the bug probably is, and why.</p>
          </div>
          <div className="flex items-center space-x-2">
            <span className="tag info">Read-only: suggests fix direction without modifying code</span>
            <span className={critic.is_valid ? 'tag good' : 'tag warn'}>
              {critic.is_valid ? 'Checked against your source' : 'Needs a second look'}
            </span>
          </div>
        </div>
        <p className="text-sm sm:text-base text-zinc-200 leading-relaxed">{out.summary || 'Review complete.'}</p>
      </div>

      <div className="space-y-5">
        <div className="border-b border-borderSubtle pb-3 flex items-baseline justify-between">
          <h3 className="text-base sm:text-lg font-bold text-white">Ranked Issue Localisation & Suggested Fixes</h3>
          <span className="text-xs text-zinc-500">Matched against the files you scanned</span>
        </div>
        <div className="space-y-6">
          {candidates.map((c, i) => {
            const citations = Array.isArray(c.citations) && c.citations.length > 0
              ? c.citations
              : [`${c.file_path}:${c.line_start}-${c.line_end} (${c.symbol_name})`]
            return (
              <div key={i} className="subpanel p-6 sm:p-8 space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-borderSubtle pb-4">
                  <div className="flex items-center space-x-3">
                    <span className="tag info">Finding {c.rank}</span>
                    <h4 className="font-mono font-bold text-base text-white">{c.symbol_name}</h4>
                    <span className="text-zinc-400 text-xs font-mono">{c.file_path}:{c.line_start}-{c.line_end}</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="tag">Confidence: {(c.confidence || 'medium').toLowerCase()}</span>
                    <span className="tag info">Read only</span>
                  </div>
                </div>

                <div className="space-y-1">
                  <span className="label">Why this is a problem</span>
                  <p className="text-sm text-zinc-200 leading-relaxed">{c.why_problematic || c.root_cause_hypothesis}</p>
                </div>

                <div className="space-y-2 pt-2">
                  <div className="flex items-center justify-between">
                    <span className="label">Side by side comparison</span>
                    <span className="text-[11px] text-zinc-500">Read it before you change anything</span>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="rounded-lg border border-red-900/50 bg-red-950/15 p-4 space-y-2.5">
                      <div className="flex items-center justify-between border-b border-red-900/40 pb-2">
                        <span className="label is-risk">The code as it is now</span>
                        <span className="text-[11px] text-red-300/80">Lines {c.line_start}-{c.line_end}</span>
                      </div>
                      <pre className="text-xs font-mono text-red-200 overflow-x-auto leading-relaxed p-3.5 rounded-md bg-black/50 border border-red-900/30 whitespace-pre">
                        {c.wrong_code || '# Current implementation in retrieved file'}
                      </pre>
                      <div className="pt-1 text-xs text-red-300/90 leading-relaxed">
                        <strong className="label is-inline is-risk">Why it is a problem:</strong>
                        {c.why_problematic || c.root_cause_hypothesis}
                      </div>
                    </div>

                    <div className="rounded-lg border border-emerald-900/50 bg-emerald-950/15 p-4 space-y-2.5">
                      <div className="flex items-center justify-between border-b border-emerald-900/40 pb-2">
                        <span className="label is-good">The code we suggest</span>
                        <span className="text-[11px] text-emerald-300/80">Suggested fix</span>
                      </div>
                      <pre className="text-xs font-mono text-emerald-200 overflow-x-auto leading-relaxed p-3.5 rounded-md bg-black/50 border border-emerald-900/30 whitespace-pre">
                        {c.recommended_pattern || c.correct_code || '# Recommended fix direction'}
                      </pre>
                      <div className="pt-1 text-xs text-emerald-300/90 leading-relaxed">
                        <strong className="label is-inline is-good">What the change does:</strong>
                        {c.explanation_of_change || c.suggested_fix}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-borderSubtle/60 flex flex-wrap items-center gap-2">
                  <span className="label">Where this came from</span>
                  {citations.map((cit, j) => (
                    <span key={j} className="text-[11px] font-mono px-2 py-1 rounded bg-canvas text-blue-300">{cit}</span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
