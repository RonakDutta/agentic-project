import React from 'react'

export default function Header({ health, canExport, onExport }) {
  return (
    <header className="border-b border-borderSubtle bg-canvas sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <svg className="w-5 h-5 text-blue-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <div className="min-w-0">
            <div className="text-white text-[15px] font-semibold leading-tight">Agentic AI Co-Pilot</div>
            <div className="text-[11px] text-zinc-500 leading-tight hidden sm:block">A Multi-Agent RAG System for Idea Validation & Codebase Analysis</div>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <span className={`hidden sm:flex items-center text-xs ${health.className}`}>
            <span className="font-medium">{health.text}</span>
          </span>
          {canExport && (
            <button onClick={onExport} className="btn btn-quiet">Download report (.md)</button>
          )}
        </div>
      </div>
    </header>
  )
}
