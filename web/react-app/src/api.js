/* Backend API client. Same endpoints and payloads as web/templates/index.html. */

async function parseJson(res) {
  return res.json().catch(() => ({}))
}

export async function runQuery({ query, repoPath, forceIntent, signal }) {
  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({ query, repo_path: repoPath, force_intent: forceIntent }),
  })
  if (!res.ok) {
    const errData = await parseJson(res)
    throw new Error(errData.error || `Server responded with status ${res.status} (${res.statusText})`)
  }
  const state = await res.json()
  if (state.status === 'failed' || state.error) {
    throw new Error(state.error || 'Pipeline execution failed on server.')
  }
  return state
}

export async function sendFollowupRequest({ query, context, sessionId, repoPath }) {
  const res = await fetch('/api/followup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, context, session_id: sessionId, repo_path: repoPath }),
  })
  if (!res.ok) {
    const errData = await parseJson(res)
    throw new Error(errData.error || `Server responded with status ${res.status}`)
  }
  const data = await res.json()
  if (data.status === 'failed' || data.error) {
    throw new Error(data.error || 'Follow-up pipeline failed on the server.')
  }
  return data
}

export async function inspectRepoRequest(repoPath) {
  const res = await fetch('/api/inspect-repo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_path: repoPath }),
  })
  return res.json()
}

export async function fetchSampleRepoPath() {
  const res = await fetch('/api/sample-repo-path')
  return res.json()
}

export async function fetchHealth() {
  const res = await fetch('/api/health')
  if (!res.ok) return null
  return res.json()
}

export function downloadMarkdown(filename, text) {
  const blob = new Blob([text], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
