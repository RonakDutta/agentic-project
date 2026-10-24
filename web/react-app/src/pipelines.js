// Pipeline graphs. Each node is matched to the backend trace steps by agent name.
// A node is "done" when its trace step arrives and "working" while every node it
// depends on is done and the run is still going (that is how the pipeline runs).

export const STARTUP_PIPELINE = {
  rows: 3,
  nodes: [
    { id: 'idea', label: 'Idea brief', sub: 'AI', agents: ['Idea Decomposer'], col: 0, row: 1, deps: [] },
    { id: 'market', label: 'Market search', sub: 'Web + AI', agents: ['Market & Competitor Researcher'], col: 1, row: 0, deps: ['idea'] },
    { id: 'papers', label: 'Research papers', sub: 'arXiv · S2 · OpenAlex', agents: ['Prior-Art Researcher'], col: 1, row: 2, deps: ['idea'], star: true },
    { id: 'kill', label: "Devil's advocate", sub: 'AI', agents: ['Adversarial Kill Agent'], col: 2, row: 0, deps: ['market'] },
    { id: 'roadmap', label: 'Roadmap', sub: 'AI, in parallel', agents: ['Roadmap & Risk Assessor'], col: 2, row: 1, deps: ['market'] },
    { id: 'judge', label: 'Judge', sub: 'AI', agents: ['Evidence Reconciler'], col: 3, row: 0, deps: ['kill'] },
    { id: 'score', label: 'Scorecard', sub: 'Code, no AI', agents: ['Feasibility Scorecard Engine'], col: 4, row: 1, deps: ['judge', 'papers'] },
    { id: 'prd', label: 'PRD + diagrams', sub: 'AI', agents: ['PRD & Architecture Specialist'], col: 5, row: 1, deps: ['score'] },
    { id: 'report', label: 'Report', sub: '14 sections', agents: ['Report Compiler'], col: 6, row: 1, deps: ['prd', 'roadmap'], final: true },
  ],
}

export const CODE_PIPELINE = {
  rows: 2,
  nodes: [
    { id: 'index', label: 'Parse code', sub: 'AST, no AI', agents: ['Code Structure Indexer'], col: 0, row: 0, deps: [] },
    { id: 'retrieve', label: 'Find code', sub: 'BM25 + vectors', agents: ['Code Navigation Agent'], col: 1, row: 0, deps: ['index'] },
    { id: 'graph', label: 'Call graph', sub: 'Blast radius', agents: ['Code Navigation Agent'], col: 1, row: 1, deps: ['index'] },
    { id: 'diagnose', label: 'Diagnose', sub: 'AI', agents: ['Root Cause Diagnosis Agent'], col: 2, row: 0, deps: ['retrieve', 'graph'] },
    { id: 'critic', label: 'Verify on disk', sub: 'Code, no AI', agents: ['Deterministic Critic'], col: 3, row: 0, deps: ['diagnose'], star: true },
    { id: 'report', label: 'Report', sub: 'Read-only', agents: [], col: 4, row: 0, deps: ['critic'], final: true },
  ],
}

export const PROTOTYPE_PIPELINE = {
  rows: 2,
  nodes: [
    { id: 'spec', label: 'Pick features', sub: 'From the PRD', agents: ['Spec Planner'], col: 0, row: 0, deps: [] },
    { id: 'write', label: 'Write code', sub: 'AI, 1 call', agents: ['Code Writer'], col: 1, row: 0, deps: ['spec'] },
    { id: 'safety', label: 'Safety check', sub: 'Code, no AI', agents: ['Safety Check'], col: 2, row: 0, deps: ['write'], star: true, warn: 'problem found' },
    { id: 'compile', label: 'Compile', sub: 'Code, no AI', agents: ['Compiler'], col: 3, row: 0, deps: ['safety'], warn: 'problem found' },
    { id: 'tests', label: 'Run tests', sub: 'pytest', agents: ['Test Runner'], col: 4, row: 0, deps: ['compile'], warn: 'problem found' },
    { id: 'fix', label: 'Fix once', sub: 'AI, only if needed', agents: ['Code Fixer'], col: 4, row: 1, deps: ['tests'] },
    { id: 'run', label: 'Start app', sub: 'Local only', agents: ['App Runner'], col: 5, row: 0, deps: ['tests'], warn: 'problem found' },
    { id: 'probe', label: 'Check endpoints', sub: 'HTTP calls', agents: ['Endpoint Checker'], col: 6, row: 0, deps: ['run'], warn: 'problem found' },
  ],
}

/** Returns {nodeId: {state, ms, step}} from the trace events of a run. */
export function nodeStates(pipeline, events, phase) {
  const out = {}
  for (const node of pipeline.nodes) {
    if (node.final) continue
    const steps = events.filter((e) => node.agents.includes(e.agent_name))
    const last = steps[steps.length - 1]
    if (last && last.status !== 'running') {
      const state = last.details?.skipped ? 'skipped' : last.status === 'warning' ? 'fallback' : 'done'
      out[node.id] = { state, ms: last.duration_ms, step: last }
    }
  }
  if (phase === 'done') out.report = { state: 'done' }
  for (const node of pipeline.nodes) {
    if (out[node.id]) continue
    const ready = node.deps.every((d) => out[d])
    out[node.id] = { state: phase === 'running' && ready ? 'running' : phase === 'done' ? 'notrun' : 'waiting' }
  }
  return out
}

export const SOURCE_LABEL = { llm: 'AI', fallback: 'Built-in fallback', deterministic: 'Computed in code' }
