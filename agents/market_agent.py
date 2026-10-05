"""
Market & Tech Stack Agent.
Conducts competitor and market intelligence using the WebSearchTool,
identifies existing solutions with citations, and recommends a tailored technical architecture.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from core.llm import llm_client
from tools.search_tool import web_search_tool, SearchResultItem
from agents.idea_agent import DecomposedIdea


@dataclass
class MarketAnalysis:
    competitors: List[Dict[str, Any]]
    tech_stack: Dict[str, Dict[str, str]]  # category -> {choice, justification, alternatives}
    key_differentiators: List[str]
    citations: List[Dict[str, str]]
    trace: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


MARKET_SYSTEM_PROMPT = """You are a Principal Software Architect and Market Intelligence Agent.
Your role is to analyze a project idea against retrieved real-world solutions and recommend an optimal technology stack.

CRITICAL INSTRUCTIONS:
1. Review the provided search evidence and synthesize 2-3 existing solutions/competitors with strengths & gaps.
2. Recommend a modern, production-grade technology stack with explicit engineering tradeoffs.
3. Ground your citations in the provided search results.
4. Output strict JSON matching this exact schema:
{
  "competitors": [
    {
      "name": "Competitor / Existing Solution Name",
      "summary": "1-2 sentence description of what they do",
      "advantages": "What they do well",
      "gaps": "What they lack or where our project wins",
      "reference_url": "URL from the provided search results"
    }
  ],
  "tech_stack": {
    "frontend": {
      "choice": "e.g. React + Tailwind CSS",
      "rationale": "High-velocity component styling, responsive dashboards",
      "tradeoffs": "Requires build tooling unlike vanilla HTML"
    },
    "backend": {
      "choice": "e.g. FastAPI (Python 3.13)",
      "rationale": "Async high-concurrency, native Pydantic validation",
      "tradeoffs": "Single-thread CPU bound unless worker processes are used"
    },
    "database": {
      "choice": "e.g. PostgreSQL + TimescaleDB extension",
      "rationale": "Relational data + high-throughput time-series telemetry",
      "tradeoffs": "Heavier operational overhead than SQLite"
    },
    "protocols_and_ai": {
      "choice": "e.g. MQTT broker + Groq API",
      "rationale": "Low-bandwidth sensor communication + sub-second LLM inference",
      "tradeoffs": "Requires broker setup (e.g. Mosquitto)"
    }
  },
  "key_differentiators": [
    "Differentiator 1: e.g. Open-source, low-cost edge processing",
    "Differentiator 2: e.g. Zero-vendor lock-in"
  ]
}
"""


class MarketTechStackAgent:
    def __init__(self):
        self.llm = llm_client
        self.search_tool = web_search_tool

    def analyze(self, idea: DecomposedIdea) -> MarketAnalysis:
        """
        Executes web search on market solutions and recommends an optimal tech stack.
        """
        trace = list(idea.trace)
        trace.append(f"Market Agent querying web search for existing solutions in '{idea.project_title}'...")

        # 1. Gather live search evidence
        search_query = f"{idea.project_title} {idea.core_value_prop[:40]}"
        search_results: List[SearchResultItem] = self.search_tool.search(search_query, max_results=4)

        trace.append(f"Retrieved {len(search_results)} market intelligence references.")

        citations = [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in search_results
        ]

        evidence_text = "\n".join(
            f"Source [{i+1}] {r.title} ({r.url}):\n{r.snippet}"
            for i, r in enumerate(search_results)
        )

        # 2. Synthesize with LLM
        trace.append("Synthesizing competitive matrix and architectural tradeoffs...")
        user_prompt = (
            f"Project Title: {idea.project_title}\n"
            f"Problem Statement: {idea.problem_statement}\n"
            f"MVP Features: {', '.join(idea.mvp_features)}\n\n"
            f"Market Search Evidence:\n{evidence_text}\n\n"
            f"Analyze existing competitors and recommend the optimal technology stack in required JSON format."
        )

        json_output = self.llm.generate_json(
            messages=[
                {"role": "system", "content": MARKET_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        trace.append("Market & Tech Stack analysis completed.")

        return MarketAnalysis(
            competitors=json_output.get("competitors", []),
            tech_stack=json_output.get("tech_stack", {}),
            key_differentiators=json_output.get("key_differentiators", []),
            citations=citations,
            trace=trace,
        )
