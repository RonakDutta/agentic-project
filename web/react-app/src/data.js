/* Static catalogs and small helpers. Mirrors the constants in web/templates/index.html. */

export const IDEA_AGENTS = [
  { id: 'node_0', name: 'Idea & Research Agent', role: 'Problem & Target Users', desc: 'Extracts problem, target users and assumptions' },
  { id: 'node_1', name: 'Market & Tech Analyst', role: 'Competitors & Tech Stack', desc: 'Researches existing solutions & technologies' },
  { id: 'node_2', name: 'Roadmap & Risk Agent', role: 'Milestones & Mitigations', desc: 'Produces phased plan and assesses main risks' },
  { id: 'node_3', name: 'Critic & Feasibility Agent', role: 'Grounding & Scorecard', desc: 'Checks evidence grounding and feasibility verdict' },
]

export const CODE_AGENTS = [
  { id: 'node_0', name: 'Orchestrator Agent', role: 'Task Planner & AST Indexer', desc: 'Parses Python AST files and symbol table' },
  { id: 'node_1', name: 'Code Navigation Agent', role: 'Hybrid RAG Retriever', desc: 'Symbol lookup, import graph & hybrid retrieval' },
  { id: 'node_2', name: 'Diagnosis Agent', role: 'Root-Cause Specialist', desc: 'Ranked cause hypotheses with suggested fix direction' },
  { id: 'node_3', name: 'Critic Agent', role: 'Grounding & Verification', desc: 'Verifies evidence grounding against physical code' },
]

export const IDEA_DIRECT_AGENTS = [
  { key: 'idea', name: 'Idea & Research Agent', blurb: 'Problem & MVP scope' },
  { key: 'market', name: 'Market & Tech Analyst', blurb: 'Competitors & stack' },
  { key: 'roadmap', name: 'Roadmap & Risk Agent', blurb: 'Phases, risks & mitigations' },
  { key: 'critic', name: 'Critic & Feasibility Agent', blurb: 'Score & verdict' },
]

export const CODE_DIRECT_AGENTS = [
  { key: 'planner', name: 'Orchestrator Agent', blurb: 'Plan & code index' },
  { key: 'navigate', name: 'Code Navigation Agent', blurb: 'Symbols & structure' },
  { key: 'diagnose', name: 'Diagnosis Agent', blurb: 'Bug diagnosis & fix direction' },
  { key: 'critic', name: 'Critic Agent', blurb: 'Grounding verdict' },
]

export const SAMPLE_PROMPTS = {
  iot: 'A low-cost IoT energy auditing system for residential societies that detects abnormal power spikes using ESP32 with CT current sensors and alerts residents.',
  peer: 'An automated AI peer review platform for engineering students to evaluate their lab code submissions against code quality, linting, and AST standards.',
  water: 'A smart ultrasonic water meter for residential buildings using LoRaWAN to detect pipe leakages in real time and estimate daily household consumption.',
  orchestrator_flow: 'Where is intent classified in orchestrator and how are multi-agent execution steps planned?',
  token_err: 'ValueError: Token expired when verify_token validates customer credentials during checkout in order processor.',
  auth_flow: 'Where is customer authentication verified when placing an order, and how is session expiry checked?',
  blast: 'What is the change impact and blast radius if I modify verify_token in auth.py?',
}

export const FOLLOWUP_QUICK_CHIPS = {
  idea: [
    { label: 'Competitors & rivals', prompt: 'Who are the closest market competitors to this idea?' },
    { label: 'Risks & flaws', prompt: '@roadmap what are the main risks and how do we mitigate them?' },
    { label: 'Tech stack rationale', prompt: '@market explain the database and backend choices.' },
    { label: 'Must-have steps', prompt: 'What are the key preconditions needed to succeed?' },
  ],
  code: [
    { label: 'Where is auth verified?', prompt: 'Where is customer authentication verified in the codebase?' },
    { label: 'What calls that function?', prompt: 'What functions call the authentication handler?' },
    { label: 'What could break?', prompt: 'What is the blast radius and risk if I modify it?' },
    { label: 'Trace request flow', prompt: 'Show me the end-to-end request flow for login and checkout.' },
  ],
}

export function getAgentActionDescription(agentName, idx) {
  if (agentName.includes('Decomposer') || idx === 0) return 'Reading your input and setting the scope'
  if (agentName.includes('Market')) return 'Looking up similar products and the technology to build it'
  if (agentName.includes('Kill') || agentName.includes('Advocate')) return 'Looking for the weaknesses and the ways it could fail'
  if (agentName.includes('Scorecard') || agentName.includes('Roadmap') || idx === 3) return 'Scoring the idea and planning the delivery steps'
  if (agentName.includes('AST') || agentName.includes('Indexer')) return 'Reading the files and building a map of the code'
  if (agentName.includes('Diagnosis')) return 'Working out the likely cause and how to fix it'
  if (agentName.includes('Critic')) return 'Checking every claim against your actual source files'
  return 'Reading the question and choosing the right specialist'
}

export function getSpecialistBadgeClass(agentName) {
  if (!agentName) return 'info'
  if (agentName.includes('Kill') || agentName.includes('Devil')) return 'risk'
  if (agentName.includes('Scorecard') || agentName.includes('Rubric')) return 'warn'
  if (agentName.includes('Roadmap') || agentName.includes('Delivery')) return 'good'
  return 'info'
}

export function getAgentAvatarClass(agentName) {
  const n = (agentName || '').toLowerCase()
  if (n.includes('kill') || n.includes('devil')) return 'border-rose-700 bg-rose-950/70 text-rose-300'
  if (n.includes('market')) return 'border-purple-700 bg-purple-950/70 text-purple-300'
  if (n.includes('scorecard') || n.includes('scorer')) return 'border-amber-700 bg-amber-950/70 text-amber-300'
  if (n.includes('prd') || n.includes('product')) return 'border-cyan-700 bg-cyan-950/70 text-cyan-300'
  if (n.includes('roadmap') || n.includes('planner')) return 'border-emerald-700 bg-emerald-950/70 text-emerald-300'
  if (n.includes('architect')) return 'border-blue-700 bg-blue-950/70 text-blue-300'
  return 'border-zinc-700 bg-zinc-900 text-zinc-300'
}

export function getAgentInitials(agentName) {
  return (agentName || 'AI').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
}

export function buildExportMarkdown(session) {
  const out = session.final_output
  let md = ''
  if (out.full_report_markdown) {
    md = out.full_report_markdown
  } else {
    md = '# Agentic AI Co-Pilot: Project Analysis Report\n'
    md += `Date: ${new Date().toLocaleDateString()}\n`
    md += `Session ID: ${session.session_id || 'unassigned'}\n\n`
    if (session.intent === 'idea_validation') {
      md += `## Project Title: ${out.project_title || 'Validated Concept'}\n\n`
      md += `### Problem Statement\n${out.problem_statement || ''}\n\n`
      if (out.scorecard) {
        md += `### Feasibility Scorecard: ${out.scorecard.total_score}/100 (${out.scorecard.verdict})\n`
        md += `*${out.scorecard.rubric_disclaimer}*\n\n`
      }
      if (out.kill_report) {
        md += `### Adversarial Bear Case Summary\n${out.kill_report.bear_case_summary || ''}\n\n`
      }
    } else {
      md += `## Codebase Diagnosis Summary\n${out.summary || ''}\n\n`
      ;(out.candidates || []).forEach((c) => {
        md += `### Candidate #${c.rank}: ${c.symbol_name} (${c.file_path}:${c.line_start}-${c.line_end})\n`
        md += `Hypothesis: ${c.root_cause_hypothesis}\n`
        md += `Suggested Fix: ${c.suggested_fix}\n\n`
      })
    }
  }
  return { filename: `agentic_copilot_report_${session.session_id || 'export'}.md`, md }
}
