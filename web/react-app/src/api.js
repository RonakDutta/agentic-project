// Thin client for the FastAPI backend. Runs stream real progress over SSE.

async function readError(res) {
  const data = await res.json().catch(() => ({}))
  return new Error(data.error || data.message || `Server error ${res.status}`)
}

export async function getJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw await readError(res)
  return res.json()
}

export async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await readError(res)
  return res.json()
}

/**
 * POST /api/run/stream and call onEvent(type, data) for each Server-Sent Event:
 * start, trace, llm, heartbeat, result, error.
 */
export async function streamRun(body, onEvent, signal) {
  const res = await fetch('/api/run/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await readError(res)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let cut
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let type = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event: ')) type = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) onEvent(type, JSON.parse(data))
    }
  }
}
