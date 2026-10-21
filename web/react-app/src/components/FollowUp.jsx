import { useState } from 'react'
import { postJSON } from '../api.js'
import { Markdown, Tag } from './ui.jsx'

const AGENTS = {
  startup: ['@idea', '@market', '@roadmap', '@critic'],
  code: ['@planner', '@navigate', '@diagnose', '@critic'],
}
const SUGGESTIONS = {
  startup: ['What is the biggest risk?', 'How is this different from the closest paper?', 'What should the MVP leave out?'],
  code: ['What calls that function?', 'What could break if I change it?', 'Trace the request flow'],
}

/** Follow-up questions use the run's saved session (agents with @ answer from stored evidence). */
export default function FollowUp({ pillar, sessionId, repoPath, finalOutput }) {
  const [text, setText] = useState('')
  const [turns, setTurns] = useState([])
  const [busy, setBusy] = useState(false)

  async function ask(q) {
    const query = (q ?? text).trim()
    if (!query || busy) return
    setBusy(true)
    setText('')
    setTurns((t) => [...t, { q: query }])
    try {
      const res = await postJSON('/api/followup', {
        query,
        session_id: sessionId,
        repo_path: repoPath || undefined,
        context: finalOutput,
      })
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a: res.answer, agent: res.agent_name } : x)))
    } catch (err) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: err.message } : x)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card pad stack">
      <div className="row between">
        <h3>Ask a follow-up</h3>
        <span className="row tiny muted">Ask one agent directly: {AGENTS[pillar].map((a) => <span key={a} className="kbd">{a}</span>)}</span>
      </div>
      {turns.map((t, i) => (
        <div key={i} className="stack" style={{ gap: 6 }}>
          <div className="small" style={{ fontWeight: 600 }}>{t.q}</div>
          {t.a && <div className="soft" style={{ padding: 12 }}>{t.agent && <Tag tone="info">{t.agent}</Tag>}<div style={{ marginTop: 6 }}><Markdown text={t.a} /></div></div>}
          {t.error && <div className="small" style={{ color: 'var(--risk)' }}>{t.error}</div>}
          {!t.a && !t.error && <div className="small muted">Thinking...</div>}
        </div>
      ))}
      <div className="row">
        {SUGGESTIONS[pillar].map((s) => <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>)}
      </div>
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <input className="input" value={text} placeholder="Ask anything about this result" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') ask() }} />
        <button className="btn dark" disabled={busy || !text.trim()} onClick={() => ask()}>Ask</button>
      </div>
    </div>
  )
}
