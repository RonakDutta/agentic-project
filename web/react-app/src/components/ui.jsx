import { useEffect, useId, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { SOURCE_LABEL } from '../pipelines.js'

export function Tag({ tone = '', children, title }) {
  return <span className={`tag ${tone}`} title={title}>{children}</span>
}

/** Where a section came from: AI, built-in fallback, or computed in code. */
export function Source({ value }) {
  const tone = value === 'llm' ? 'info' : value === 'fallback' ? 'warn' : 'good'
  return <Tag tone={tone}>{SOURCE_LABEL[value] || value}</Tag>
}

export function Bar({ value, max = 100, tone = '' }) {
  const pct = Math.max(0, Math.min(100, max ? (value / max) * 100 : 0))
  return <div className={`bar ${tone}`}><i style={{ width: `${pct}%` }} /></div>
}

export function toneFor(pct) {
  return pct >= 70 ? 'good' : pct >= 45 ? 'warn' : 'risk'
}

/** A big plain number with a bar under it (no rings, no gauges). */
export function Score({ value, max = 100, tone, unit }) {
  const pct = max ? (value / max) * 100 : 0
  return (
    <div className="score">
      <div><span className="num">{value}</span><span className="of">{unit || `/ ${max}`}</span></div>
      <Bar value={value} max={max} tone={tone || toneFor(pct)} />
    </div>
  )
}

export function Stat({ value, unit, label, children }) {
  return (
    <div className="card stat">
      <div className="value">{value}{unit && <small>{unit}</small>}</div>
      <div className="label">{label}</div>
      {children}
    </div>
  )
}

export function More({ label = 'Show more', children }) {
  return (
    <details className="more">
      <summary>{label}</summary>
      <div style={{ marginTop: 10 }}>{children}</div>
    </details>
  )
}

export function SafeLink({ href, children, ...rest }) {
  const ok = /^https?:\/\//i.test(href || '')
  if (!ok) return <span>{children}</span>
  return <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>
}

/** Markdown from the AI is sanitised before it touches the DOM. */
export function Markdown({ text }) {
  const html = DOMPurify.sanitize(marked.parse(text || '', { breaks: true }))
  return <div className="prose" dangerouslySetInnerHTML={{ __html: html }} />
}

let mermaidPromise = null
function loadMermaid(dark) {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => m.default)
  }
  return mermaidPromise.then((mermaid) => {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'neutral', fontFamily: 'Inter Variable, sans-serif' })
    return mermaid
  })
}

/** Mermaid in strict mode, loaded only when a diagram is shown. */
export function Mermaid({ chart }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '')
  const ref = useRef(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    if (!chart) return undefined
    const dark = document.documentElement.dataset.theme === 'dark'
    loadMermaid(dark)
      .then((mermaid) => mermaid.render(`m${id}${Date.now()}`, chart))
      .then(({ svg }) => {
        // securityLevel 'strict' makes mermaid sanitise every label itself.
        if (alive && ref.current) ref.current.innerHTML = svg
      })
      .catch((err) => alive && setError(String(err.message || err).slice(0, 160)))
    return () => { alive = false }
  }, [chart, id])
  if (!chart) return <div className="empty">No diagram.</div>
  if (error) return <pre className="soft tiny" style={{ padding: 12, overflowX: 'auto' }}>{chart}</pre>
  return <div className="mermaid-box" ref={ref} />
}

export function Section({ eyebrow, title, right, children }) {
  return (
    <section className="stack fade-in">
      <div className="row between">
        <div>
          {eyebrow && <div className="eyebrow accent">{eyebrow}</div>}
          {title && <h2 className="display">{title}</h2>}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id} className={value === t.id ? 'on' : ''} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && <span className="count">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function downloadText(filename, text, type = 'text/plain') {
  const blob = new Blob([text], { type })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export function seconds(ms) {
  if (ms === undefined || ms === null) return ''
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

/** Model ids without the hosting provider prefix (e.g. "openai/gpt-oss-20b" -> "gpt-oss-20b"). */
export function modelName(id) {
  return String(id || '').split('/').pop()
}

/** Backend step text mentions the hosting service and keys; the UI keeps it generic. */
export function plainText(text) {
  return String(text || '')
    .replace(/GROQ_API_KEY is not configured[^.]*\.?(\s*Add it in Settings[^.]*\.)?/gi, 'AI engine is offline.')
    .replace(/All configured Groq models are rate-limited\.?/gi, 'All AI models are busy.')
    .replace(/Groq LLM/g, 'AI model')
    .replace(/Groq API/g, 'AI engine')
    .replace(/Groq/g, 'AI')
    .replace(/free[- ]tier/gi, 'shared')
}
