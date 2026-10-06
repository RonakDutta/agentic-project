import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'

const API = ''

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
}

function App() {
  const [pillar, setPillar] = useState('idea')
  const [prompt, setPrompt] = useState('')
  const [repoPath, setRepoPath] = useState('')
  const [trace, setTrace] = useState([])
  const [output, setOutput] = useState(null)
  const [running, setRunning] = useState(false)

  async function run() {
    if (!prompt.trim() || running) return
    setRunning(true); setOutput(null); setTrace([])
    try {
      const data = await post('/api/query', {
        query: prompt,
        repo_path: repoPath || undefined,
        force_intent: pillar === 'idea' ? 'idea_validation' : 'codebase_analysis',
      })
      setTrace(data.execution_trace || [])
      setOutput(data.final_output || data)
    } catch (e) { setOutput({ error: String(e) }) }
    finally { setRunning(false) }
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6 font-sans">
      <header>
        <h1 className="text-2xl font-bold">Agentic AI Co-Pilot (React)</h1>
        <p className="text-sm text-gray-600">Synopsis-aligned UI: Orchestrator + 6 agents, explicit trace, grounded citations.</p>
        <div className="flex gap-2 mt-3">
          <button onClick={() => setPillar('idea')} className={pillar === 'idea' ? 'px-3 py-1 bg-blue-600 text-white rounded' : 'px-3 py-1 border rounded'}>Idea Assistance</button>
          <button onClick={() => setPillar('code')} className={pillar === 'code' ? 'px-3 py-1 bg-blue-600 text-white rounded' : 'px-3 py-1 border rounded'}>Codebase Analysis</button>
        </div>
      </header>
      {pillar === 'code' && (
        <input value={repoPath} onChange={e => setRepoPath(e.target.value)}
          placeholder="Repo path or GitHub URL (Python, <=300 files)" className="w-full border rounded p-2" />
      )}
      <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={4}
        placeholder={pillar === 'idea' ? 'Describe your project idea...' : 'Paste traceback or ask where a symbol is defined...'}
        className="w-full border rounded p-2" />
      <button onClick={run} disabled={running} className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50">
        {running ? 'Running agents...' : pillar === 'idea' ? 'Run Idea Assistance Pipeline' : 'Run Codebase Analysis Pipeline'}
      </button>
      {trace.length > 0 && (
        <section className="border rounded p-3">
          <h2 className="font-semibold">Agent trace (proves Sec 6.1: plan, tool choice, retry, critic)</h2>
          <ol className="list-decimal ml-5 text-sm">
            {trace.map((t, i) => <li key={i}><b>{t.agent_name}</b>: {t.action} [{t.status}]</li>)}
          </ol>
        </section>
      )}
      {output && (
        <section className="border rounded p-3">
          <h2 className="font-semibold">Result (read-only, human review required)</h2>
          <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(output, null, 2).slice(0, 6000)}</pre>
        </section>
      )}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
