import { useRef, useState } from 'react'
import { postJSON, streamRun } from './api.js'

/** State of one streamed run (agent pipeline or prototype build), fed by real SSE events. */
export function useRun(url = '/api/run/stream') {
  const [run, setRun] = useState(null)
  const abortRef = useRef(null)
  const runIdRef = useRef(null)

  async function start(body) {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    runIdRef.current = null
    setRun({ phase: 'running', events: [], calls: [], result: null, error: '', startedAt: Date.now(), endedAt: null, body })
    try {
      await streamRun(body, (type, data) => {
        setRun((r) => {
          if (!r) return r
          if (type === 'start') runIdRef.current = data.run_id
          if (type === 'trace') return { ...r, events: [...r.events, data] }
          if (type === 'llm') return { ...r, calls: [...r.calls, data] }
          if (type === 'result') return { ...r, phase: 'done', result: data, endedAt: Date.now() }
          if (type === 'error') return { ...r, phase: 'error', error: data.error, endedAt: Date.now() }
          return r
        })
      }, controller.signal, url)
      setRun((r) => (r && r.phase === 'running' ? { ...r, phase: 'error', error: 'The connection closed before the run finished.', endedAt: Date.now() } : r))
    } catch (err) {
      if (err.name === 'AbortError') {
        setRun((r) => (r ? { ...r, phase: 'error', error: 'Run stopped. No further agent steps will run.', endedAt: Date.now() } : r))
      } else {
        setRun((r) => (r ? { ...r, phase: 'error', error: err.message, endedAt: Date.now() } : r))
      }
    }
  }
  function stop() {
    // Tell the server to stop before the next agent step, then stop listening.
    if (runIdRef.current) postJSON('/api/run/cancel', { run_id: runIdRef.current }).catch(() => {})
    abortRef.current?.abort()
  }
  return { run, start, stop, reset: () => setRun(null) }
}
