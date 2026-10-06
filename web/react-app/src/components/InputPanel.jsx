import React from 'react'
import { SAMPLE_PROMPTS } from '../data.js'

const IDEA_CHIPS = [
  { type: 'iot', label: 'IoT Energy Spike Monitor' },
  { type: 'peer', label: 'AI Student Code Reviewer' },
  { type: 'water', label: 'Smart Water Meter' },
]

const CODE_CHIPS = [
  { type: 'orchestrator_flow', label: 'Orchestrator Intent Bug' },
  { type: 'token_err', label: 'Token Expired Bug' },
  { type: 'auth_flow', label: 'Order Auth Flow' },
  { type: 'blast', label: 'Blast Radius Check' },
]

export default function InputPanel({
  pillar, onSelectPillar,
  prompt, onPromptChange,
  repoPath, onRepoPathChange, repoBadge, onLoadSample, onInspectRepo, inspecting,
  errorHint, running, onRun,
}) {
  const isIdea = pillar === 'idea'
  return (
    <section className="panel p-6 sm:p-8 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="tabs">
          <button onClick={() => onSelectPillar('idea')} className={isIdea ? 'tab is-active' : 'tab'}>Idea Assistance</button>
          <button onClick={() => onSelectPillar('code')} className={!isIdea ? 'tab is-active' : 'tab'}>Codebase Analysis</button>
        </div>
        <div className="text-xs text-zinc-500 pb-2">
          <span>
            {isIdea
              ? 'Problem extraction, market research, roadmap and risk evaluation'
              : 'AST structure navigation, dependency mapping, and issue diagnosis'}
          </span>
        </div>
      </div>

      {!isIdea && (
        <div className="space-y-3 subpanel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="label is-inline">Repository to scan (read only, nothing is edited)</span>
            <div className="flex items-center gap-2">
              <button onClick={onLoadSample} className="chip">Load demo project</button>
              <button onClick={onInspectRepo} disabled={inspecting} className="chip">
                {inspecting ? 'Scanning...' : 'Scan files'}
              </button>
              {repoBadge.visible && (
                <span className={repoBadge.className}>{repoBadge.text}</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 bg-canvas/70 p-2.5 rounded-md border border-borderSubtle">
            <svg className="w-4 h-4 text-zinc-500 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <input
              type="text"
              value={repoPath}
              onChange={(e) => onRepoPathChange(e.target.value)}
              placeholder="C:/path/to/python-project or https://github.com/owner/repo"
              className="flex-1 bg-transparent text-xs font-mono text-zinc-200 placeholder:text-zinc-600 focus:outline-none px-1"
            />
          </div>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <label className="font-semibold text-zinc-200">
            {isIdea ? 'Describe your startup or project idea' : 'Paste an error message, or ask about the code'}
          </label>
          <span className="text-zinc-500 text-[11px]">Write it in your own words, or pick a sample below</span>
        </div>
        <textarea
          rows="4"
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder={isIdea
            ? 'What problem are you solving? Who is it for? What is your solution...'
            : 'Paste an exception traceback or ask about code structure (e.g. ValueError in verify_token)...'}
          className="w-full bg-canvas/70 border border-borderSubtle focus:border-blue-500 rounded-lg p-4 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none resize-none leading-relaxed"
        />
        {errorHint && <p className="text-xs text-rose-300">{errorHint}</p>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500">Try an example:</span>
          <div className="flex flex-wrap items-center gap-2">
            {(isIdea ? IDEA_CHIPS : CODE_CHIPS).map((c) => (
              <button key={c.type} onClick={() => onPromptChange(SAMPLE_PROMPTS[c.type])} className="chip">
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <button onClick={onRun} disabled={running} aria-label="Run multi-agent review pipeline" className="btn btn-primary ml-auto">
          <span>{running ? 'The 4 agents are working' : isIdea ? 'Run Idea Assistance Pipeline' : 'Run Codebase Analysis Pipeline'}</span>
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
          </svg>
        </button>
      </div>
    </section>
  )
}
