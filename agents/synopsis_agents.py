"""Canonical 6-agent mapping from synopsis Table 2 / Fig 1.

Synopsis defines exactly six agents. The codebase implements more
specialists (market, kill, scorecard, prd, roadmap, flow-trace...).
This module maps the canonical names to the real implementations so the
viva diagram and the code agree.

Canonical set:
  Orchestrator Agent | Retrieval Agent | Idea and Research Agent |
  Roadmap and Risk Agent | Code Navigation Agent | Diagnosis Agent |
  Critic Agent (shared)
"""

from dataclasses import dataclass
from typing import Dict, List

CANONICAL_AGENTS: List[Dict[str, str]] = [
    {"name": "Orchestrator Agent", "responsibility": "Classify goal, plan sub-tasks, route work, assemble answer",
     "tools": "Intent classifier, task list, budget limit", "implements": "agents.orchestrator:OrchestratorAgent"},
    {"name": "Retrieval Agent", "responsibility": "Rewrite queries, choose index, hybrid search, retry if insufficient",
     "tools": "Vector search, keyword search, web search", "implements": "indexer.hybrid_retriever:HybridRetriever"},
    {"name": "Idea and Research Agent", "responsibility": "Extract problem/users/assumptions, research solutions",
     "tools": "Web search, knowledge base retrieval", "implements": "agents.idea_agent + agents.market_agent"},
    {"name": "Roadmap and Risk Agent", "responsibility": "Phased plan with milestones, risks with mitigations",
     "tools": "Knowledge base retrieval", "implements": "agents.roadmap_agent + agents.kill_agent"},
    {"name": "Code Navigation Agent", "responsibility": "Answer structural questions, narrow files to functions",
     "tools": "AST parser, symbol table, import graph, code vector index",
     "implements": "agents.code_nav_agent + agents.flow_trace_agent + agents.change_impact_agent"},
    {"name": "Diagnosis Agent", "responsibility": "Ranked cause hypothesis with fix direction",
     "tools": "Error pattern index, git log/blame, static analysis",
     "implements": "agents.diagnosis_agent + tools.static_analyzer + tools.git_tools"},
    {"name": "Critic Agent", "responsibility": "Grounding and consistency check, shared by both modules",
     "tools": "Index lookup, grounding check", "implements": "agents.critic_agent:DeterministicCriticAgent"},
]


@dataclass
class SynopsisMapping:
    canonical: str
    implements: str


def get_canonical_catalog() -> List[Dict[str, str]]:
    return [dict(a) for a in CANONICAL_AGENTS]


def resolve_canonical(name: str) -> Dict[str, str]:
    lowered = (name or "").strip().lower()
    for agent in CANONICAL_AGENTS:
        if agent["name"].lower() == lowered:
            return dict(agent)
    raise KeyError(f"Unknown canonical agent: {name!r}")
