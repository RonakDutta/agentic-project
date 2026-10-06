/* API client for the FastAPI backend. Same contracts as web/templates/index.html. */

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const msg = data.message || data.error || `Request failed (${res.status})`
    throw new Error(msg)
  }
  return data
}

export function runQuery({ query, repo_path, force_intent, signal }) {
  return request('/api/query', {
    method: 'POST',
    signal,
    body: JSON.stringify({ query, repo_path: repo_path || undefined, force_intent }),
  })
}

export function runGraph({ query, repo_path, force_intent, signal }) {
  return request('/api/graph/run', {
    method: 'POST',
    signal,
    body: JSON.stringify({ query, repo_path: repo_path || undefined, force_intent }),
  })
}

export function sendFollowup({ query, context, session_id, repo_path }) {
  return request('/api/followup', {
    method: 'POST',
    body: JSON.stringify({ query, context, session_id, repo_path: repo_path || undefined }),
  })
}

export function inspectRepo(repo_path) {
  return request('/api/inspect-repo', {
    method: 'POST',
    body: JSON.stringify({ repo_path }),
  })
}

export function fetchSampleRepoPath() {
  return request('/api/sample-repo-path')
}

export function fetchHealth() {
  return request('/api/health')
}

export function fetchSynopsisAgents() {
  return request('/api/synopsis/agents')
}

export function kbLookup(q, top_k = 3) {
  return request(`/api/kb/lookup?q=${encodeURIComponent(q)}&top_k=${top_k}`)
}

export function downloadMarkdown(filename, text) {
  const blob = new Blob([text], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
