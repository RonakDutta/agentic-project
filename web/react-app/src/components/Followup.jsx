import React, { useEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import mermaid from 'mermaid'
import {
  CODE_DIRECT_AGENTS, FOLLOWUP_QUICK_CHIPS, IDEA_DIRECT_AGENTS,
  getAgentAvatarClass, getAgentInitials, getSpecialistBadgeClass,
} from '../data.js'

function renderMermaidIn(el) {
  const blocks = el.querySelectorAll('pre code.language-mermaid, pre code[class*="language-mermaid"]')
  const jobs = []
  blocks.forEach((codeEl) => {
    const definition = codeEl.textContent || ''
    const wrapper = codeEl.closest('pre')
    if (!wrapper || !definition.trim()) return
    const holder = document.createElement('div')
    holder.className = 'my-3 p-3 bg-white/[0.02] rounded-md overflow-x-auto'
    jobs.push(
      mermaid.render(`mermaid_reply_${Math.random().toString(36).substring(2, 10)}`, definition.trim())
        .then(({ svg }) => { holder.innerHTML = svg; wrapper.replaceWith(holder) })
        .catch((e) => { console.warn('Mermaid reply render failed, showing source instead:', e) })
    )
  })
  return Promise.all(jobs)
}

function AgentMessage({ msg }) {
  const bodyRef = useRef(null)
  useEffect(() => {
    if (bodyRef.current) renderMermaidIn(bodyRef.current)
  }, [msg.html])
  return (
    <div className="panel p-6 sm:p-7 space-y-4 animate-step-reveal">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borderSubtle pb-3">
        <div className="flex items-center space-x-2.5">
          <div className={`agent-avatar ${getAgentAvatarClass(msg.agentName)}`}>{getAgentInitials(msg.agentName)}</div>
          <div>
            <span className={`tag ${getSpecialistBadgeClass(msg.agentName)}`}>{msg.agentName}</span>
            <div className="text-[11px] text-zinc-500 mt-0.5">{msg.actionTaken || 'Response'}</div>
          </div>
        </div>
        <span className="text-[11px] text-zinc-500">{msg.directAgent ? `asked @${msg.directAgent}` : 'specialist'}</span>
      </div>

      <div ref={bodyRef} className="prose-chat reply-body" dangerouslySetInnerHTML={{ __html: msg.html }} />

      {msg.symbols.length > 0 && (
        <div className="pt-2 rule flex flex-wrap items-center gap-1.5 text-xs">
          <span className="label is-inline" style={{ margin: 0 }}>It looked at:</span>
          {msg.symbols.map((s, i) => (
            <span key={i} className="font-mono text-[11px] text-blue-300 bg-canvas px-2 py-0.5 rounded">{s}</span>
          ))}
        </div>
      )}

      {msg.files.length > 0 && (
        <div className="pt-1 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="label is-inline" style={{ margin: 0 }}>Files used:</span>
          {msg.files.map((f, i) => (
            <span key={i} className="font-mono text-[11px] text-zinc-300 bg-canvas px-2 py-0.5 rounded">{f}</span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Followup({ pillar, messages, thinkingStart, sendError, onSend, sending }) {
  const [input, setInput] = useState('')
  const [menu, setMenu] = useState({ open: false, items: [], index: 0 })
  const [thinkingSec, setThinkingSec] = useState(0)
  const inputRef = useRef(null)
  const threadRef = useRef(null)

  useEffect(() => {
    if (!thinkingStart) return undefined
    setThinkingSec(0.2)
    const id = setInterval(() => setThinkingSec((Date.now() - thinkingStart) / 1000), 500)
    return () => clearInterval(id)
  }, [thinkingStart])

  const agentList = pillar === 'code' ? CODE_DIRECT_AGENTS : IDEA_DIRECT_AGENTS
  const quickChips = FOLLOWUP_QUICK_CHIPS[pillar]

  const mentionMatch = useMemo(() => {
    const m = input.match(/^\s*@([a-zA-Z_-]+)\b/)
    return m ? m[1].toLowerCase() : null
  }, [input])

  function autoGrow() {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  function hideMenu() {
    setMenu({ open: false, items: [], index: 0 })
  }

  function applyMention(key) {
    const rest = input.replace(/^\s*@[a-zA-Z_-]*\s*/, '')
    setInput(`@${key} ${rest}`)
    hideMenu()
    requestAnimationFrame(() => {
      inputRef.current?.focus()
      autoGrow()
    })
  }

  function handleInput(e) {
    const value = e.target.value
    setInput(value)
    requestAnimationFrame(autoGrow)
    const caret = e.target.selectionStart
    const beforeCaret = value.slice(0, caret)
    const trigger = beforeCaret.match(/(?:^|\s)@([a-zA-Z_-]*)$/)
    if (!trigger) {
      hideMenu()
      return
    }
    const prefix = trigger[1].toLowerCase()
    const matches = agentList.filter((a) => a.key.startsWith(prefix) || a.name.toLowerCase().startsWith(prefix))
    if (!matches.length) {
      hideMenu()
      return
    }
    setMenu({ open: true, items: matches, index: 0 })
  }

  // Replaces the partially typed @token with the chosen agent.
  // Takes an explicit index so mouse clicks do not depend on hover state.
  function selectMentionItem(forcedIndex) {
    const item = menu.items[forcedIndex ?? menu.index]
    if (!item || !inputRef.current) return
    const el = inputRef.current
    const caret = el.selectionStart
    const beforeCaret = input.slice(0, caret)
    const token = beforeCaret.match(/(?:^|\s)@([a-zA-Z_-]*)$/)
    if (!token) {
      hideMenu()
      return
    }
    const start = caret - token[0].length
    let replacement = `${start === 0 ? '' : ' '}@${item.key} `
    if (input.slice(caret).startsWith(' ')) replacement = replacement.replace(/ $/, '')
    const next = input.slice(0, start) + replacement + input.slice(caret)
    setInput(next)
    hideMenu()
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + replacement.length, start + replacement.length)
      autoGrow()
    })
  }

  function handleKeyDown(e) {
    if (menu.open) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMenu((m) => ({ ...m, index: (m.index + 1) % m.items.length })); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMenu((m) => ({ ...m, index: (m.index - 1 + m.items.length) % m.items.length })); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); selectMentionItem(); return }
      if (e.key === 'Escape') { e.preventDefault(); hideMenu(); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const q = input.trim()
    if (!q || sending) return
    setInput('')
    hideMenu()
    requestAnimationFrame(autoGrow)
    onSend(q)
  }

  useEffect(() => {
    threadRef.current?.lastElementChild?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, thinkingStart])

  return (
    <div className="panel p-8 sm:p-10 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-borderSubtle pb-4">
        <div>
          <h3 className="text-base sm:text-lg font-bold text-white">Ask a follow-up question</h3>
          <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
            Ask anything about the result, or talk to one specialist directly by starting your message with{' '}
            <span className="text-blue-300 font-semibold">@kill</span>,{' '}
            <span className="text-blue-300 font-semibold">@market</span> or{' '}
            <span className="text-blue-300 font-semibold">@architect</span>.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-zinc-500 font-medium shrink-0">Talk to one agent:</span>
        <div className="flex flex-wrap items-center gap-2">
          {agentList.map((a) => (
            <button
              key={a.key}
              title={a.blurb}
              onClick={() => applyMention(a.key)}
              className={mentionMatch === a.key ? 'chip is-active flex items-center gap-1.5' : 'chip flex items-center gap-1.5'}
            >
              <span className="text-blue-400 font-bold">@</span>
              <span>{a.name}</span>
            </button>
          ))}
        </div>
      </div>

      <div ref={threadRef} className="space-y-4">
        {messages.map((m, i) => {
          if (m.kind === 'user') {
            return (
              <div key={i} className="subpanel p-4 space-y-1 ml-auto max-w-2xl animate-step-reveal">
                <div className="flex items-center justify-between gap-3">
                  <span className="label is-inline is-accent" style={{ margin: 0 }}>
                    You{m.mention ? ` / to @${m.mention}` : ''}
                  </span>
                </div>
                <p className="text-sm text-zinc-100 font-medium">{m.text}</p>
              </div>
            )
          }
          if (m.kind === 'error') {
            return (
              <div key={i} className="border border-rose-900/60 bg-rose-950/20 p-5 rounded-lg space-y-2 max-w-2xl animate-step-reveal">
                <div className="label is-risk" style={{ marginBottom: 0 }}>
                  <span>{m.rateLimited ? 'The free AI limit was reached' : 'That question could not be answered'}</span>
                </div>
                <p className="text-xs text-zinc-300 leading-relaxed">{m.text}</p>
                {m.rateLimited && (
                  <p className="text-[11px] text-zinc-400">
                    The engine waits a few seconds and then tries the next model by itself. Send the question again, or ask a specialist such as <span className="text-blue-300">@scorecard</span>, which answers from the report without using the AI limit.
                  </p>
                )}
              </div>
            )
          }
          return <AgentMessage key={i} msg={m} />
        })}

        {thinkingStart && (
          <div className="subpanel p-4 space-y-1.5 max-w-2xl">
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <span className="font-medium text-zinc-300">The agent is answering</span>
              <span className="text-zinc-500">({thinkingSec.toFixed(1)}s)</span>
            </div>
          </div>
        )}
      </div>

      {messages.length === 0 && !thinkingStart && (
        <div className="fade-soft subpanel p-6 text-center">
          <p className="text-xs text-zinc-500 leading-relaxed">
            No questions yet. Ask anything about the validated idea, or address a specialist directly by typing <span className="font-mono text-blue-300">@</span> in the input below.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <span className="text-xs text-zinc-500 font-medium">Common questions:</span>
        <div className="flex flex-wrap items-center gap-2">
          {quickChips.map((c) => (
            <button
              key={c.label}
              className="chip"
              onClick={() => { setInput(c.prompt); requestAnimationFrame(autoGrow); inputRef.current?.focus() }}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative bg-canvas border border-borderSubtle focus-within:border-zinc-500 rounded-lg p-3.5">
        {menu.open && (
          <div className="mention-menu" role="listbox" aria-label="Agent suggestions">
            {menu.items.map((a, idx) => (
              <button
                key={a.key}
                type="button"
                role="option"
                aria-selected={idx === menu.index}
                className={`mention-item ${idx === menu.index ? 'is-active' : ''}`}
                onMouseEnter={() => setMenu((m) => ({ ...m, index: idx }))}
                onMouseDown={(e) => { e.preventDefault(); selectMentionItem(idx) }}
              >
                <span className="font-mono text-[11px] text-blue-300 w-24 shrink-0">@{a.key}</span>
                <span className="text-xs text-zinc-200 font-semibold">{a.name}</span>
                <span className="text-[11px] text-zinc-500 truncate">{a.blurb}</span>
              </button>
            ))}
          </div>
        )}
        <textarea
          ref={inputRef}
          rows="2"
          aria-label="Follow-up question"
          placeholder="Ask any question about architecture, risks, code, or milestones..."
          value={input}
          onChange={handleInput}
          onBlur={() => setTimeout(hideMenu, 120)}
          onKeyDown={handleKeyDown}
          className="w-full bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none resize-none leading-relaxed max-h-40"
        />
        <div className="flex items-center justify-between pt-2.5 border-t border-borderSubtle/50 mt-1">
          <span className="text-[11px] font-mono text-zinc-500 flex items-center space-x-1">
            <span>Press</span>
            <kbd className="px-1.5 py-0.5 rounded bg-surface border border-borderSubtle text-zinc-400 text-[10px]">Enter ↵</kbd>
            <span>to send,</span>
            <kbd className="px-1.5 py-0.5 rounded bg-surface border border-borderSubtle text-zinc-400 text-[10px]">Shift + Enter</kbd>
            <span>for new line</span>
          </span>
          <button onClick={submit} disabled={sending} aria-label="Send follow-up question" className="btn btn-primary py-2.5">
            <span>{sending ? 'Thinking...' : 'Send'}</span>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        </div>
      </div>

      {sendError && <p className="text-xs text-rose-300">{sendError}</p>}
    </div>
  )
}
