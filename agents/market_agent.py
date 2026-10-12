"""
Market & Tech Stack Agent.
Conducts competitor and market intelligence using the WebSearchTool,
identifies existing solutions with citations, and recommends a tailored technical architecture.
"""

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from core.llm import llm_client, AGENT_MAX_TOKENS
from tools.search_tool import web_search_tool, SearchResultItem
from agents.idea_agent import DecomposedIdea

_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "that", "this", "to", "of", "in", "on",
    "using", "based", "system", "platform", "app", "application", "tool", "smart", "low-cost",
}


def build_search_queries(idea: DecomposedIdea) -> List[str]:
    """A few short, different queries: the product, its alternatives, and the problem."""
    title = (idea.project_title or "").strip()
    words = [w for w in re.findall(r"[A-Za-z0-9-]+", idea.raw_idea or title) if w.lower() not in _STOPWORDS]
    keywords = " ".join(words[:8])
    queries = [
        title,
        f"{title} alternatives competitors",
        keywords,
    ]
    out: List[str] = []
    for q in queries:
        q = q.strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out


@dataclass
class MarketAnalysis:
    competitors: List[Dict[str, Any]]
    tech_stack: Dict[str, Dict[str, str]]  # category -> {choice, justification, alternatives}
    key_differentiators: List[str]
    citations: List[Dict[str, str]]
    trace: List[str]
    implementation_pitfall: Optional[Dict[str, str]] = None
    # "llm" when the model wrote this section, "fallback" when built-in defaults were used.
    generation_source: str = "llm"
    fallback_reason: str = ""
    # Which search backend produced the citations, and how many were live results.
    search_backend: str = "none"
    live_citation_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


MARKET_SYSTEM_PROMPT = """You are a Principal Software Architect and Market Intelligence Agent.
Your role is to analyze a project idea against retrieved real-world solutions and recommend an optimal technology stack.

CRITICAL INSTRUCTIONS:
1. Review the provided search evidence and synthesize 2-3 existing solutions/competitors with strengths & gaps.
2. Recommend a modern, production-grade technology stack with explicit engineering tradeoffs.
3. Ground your citations in the provided search results.
4. Do NOT execute browser commands, tools, or function calls. Output pure JSON only.
5. Output strict JSON matching this exact schema:
{
  "competitors": [
    {
      "name": "Competitor / Existing Solution Name",
      "summary": "1-2 sentence description of what they do",
      "advantages": "What they do well",
      "gaps": "What they lack or where our project wins",
      "reference_url": "URL from the provided search results, or empty if not in the evidence",
      "evidence": "search if this competitor appears in the provided evidence, otherwise model_knowledge"
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
  ],
  "implementation_pitfall": {
    "title": "Short title of common technical mistake or architectural trap",
    "explanation": "Clear 1-2 sentence explanation of why developers make this mistake",
    "wrong_code": "# Common Mistake / Wrong Approach (5-10 lines of realistic Python)",
    "correct_code": "# Recommended Fix / Correct Approach (5-10 lines of production Python)"
  }
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

        # 1. Gather live search evidence (several short queries, merged by URL)
        queries = build_search_queries(idea)
        search_results: List[SearchResultItem] = self.search_tool.search_many(queries, max_results=5)
        search_backend = getattr(self.search_tool, "last_backend", "unknown")
        live_results = [r for r in search_results if r.is_live]

        trace.append(
            f"Search backend: {search_backend}. {len(live_results)} live results, "
            f"{len(search_results) - len(live_results)} offline references."
        )

        citations = [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "is_live": r.is_live}
            for r in search_results
        ]

        # Keep the prompt inside the free token window: long search abstracts
        # are the biggest TPM cost, so each snippet is clipped short. Full
        # text stays in `citations` for the report.
        evidence_text = "\n".join(
            f"Source [{i+1}] {r.title} ({r.url}){'' if r.is_live else ' [offline reference, not a live search result]'}:\n{r.snippet[:350]}"
            for i, r in enumerate(search_results)
        )[:2500] or "No live search evidence was reachable. Name well-known competitors you are confident exist, set evidence to model_knowledge and leave reference_url empty."

        # 2. Synthesize with LLM
        trace.append("Synthesizing competitive matrix and architectural tradeoffs...")
        user_prompt = (
            f"Project Title: {idea.project_title}\n"
            f"Problem Statement: {idea.problem_statement}\n"
            f"MVP Features: {', '.join(idea.mvp_features)}\n\n"
            f"Market Search Evidence:\n{evidence_text}\n\n"
            f"Analyze existing competitors, recommend technology stack, and identify one high-risk code implementation pitfall (wrong code vs correct code) in required JSON format."
        )

        generation_source, fallback_reason = "llm", ""
        try:
            json_output = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": MARKET_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                # Largest schema (competitors + stack + code pitfall); a truncated
                # answer is retried once with +1,024 tokens by the client.
                max_tokens=AGENT_MAX_TOKENS["market"],
            )
        except Exception as err:
            trace.append(f"LLM market analysis note ({err}). Using search results as the competitor list.")
            generation_source, fallback_reason = "fallback", f"LLM unavailable: {err}"
            json_output = {
                "competitors": [
                    {
                        "name": r.title[:60],
                        "summary": r.snippet[:200],
                        "advantages": "Not analysed (LLM unavailable).",
                        "gaps": "Not analysed (LLM unavailable).",
                        "reference_url": r.url,
                        "evidence": "search" if r.is_live else "offline_reference",
                    }
                    for r in search_results[:3]
                ],
                "tech_stack": {
                    "frontend": {"choice": "React + Tailwind CSS", "rationale": "Component reusability and rapid prototyping."},
                    "backend": {"choice": "FastAPI (Python 3.11)", "rationale": "High-concurrency async ASGI performance."},
                    "database": {"choice": "PostgreSQL", "rationale": "ACID compliance and relational integrity."},
                    "infrastructure": {"choice": "Docker + AWS ECS", "rationale": "Containerized portability and horizontal scale."}
                },
                "key_differentiators": [
                    "Tailored domain workflows reducing time-to-insight.",
                    "Transparent pricing and open data export."
                ],
            }

        trace.append("Market & Tech Stack analysis completed.")

        default_pitfall = {
            "title": "Synchronous Blocking Calls vs Async Pipeline",
            "explanation": "Many early implementations use synchronous network calls that freeze the server worker when handling concurrent user requests.",
            "wrong_code": "# Common Mistake: Synchronous blocking call\nimport requests\n\ndef fetch_data(endpoints):\n    data = []\n    for url in endpoints:\n        # Blocks worker thread, fails under concurrent traffic\n        resp = requests.get(url, timeout=5)\n        data.append(resp.json())\n    return data",
            "correct_code": "# Recommended Fix: Async non-blocking with connection pool\nimport httpx\nimport asyncio\n\nasync def fetch_data(endpoints: list[str]) -> list[dict]:\n    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)\n    async with httpx.AsyncClient(limits=limits, timeout=5.0) as client:\n        tasks = [client.get(url) for url in endpoints]\n        responses = await asyncio.gather(*tasks, return_exceptions=True)\n        return [r.json() for r in responses if isinstance(r, httpx.Response) and r.status_code == 200]",
        }

        pitfall = json_output.get("implementation_pitfall")
        if not isinstance(pitfall, dict) or not pitfall.get("wrong_code"):
            pitfall = dict(default_pitfall, generic=True)

        tech_stack = json_output.get("tech_stack") or {}
        if not isinstance(tech_stack, dict):
            tech_stack = {}
        defaults = {
            "backend": {"choice": "FastAPI (Python 3.11+)", "rationale": "High-concurrency async ASGI performance and automatic OpenAPI schemas.", "tradeoffs": "Requires async database drivers for optimal throughput."},
            "frontend": {"choice": "React + Tailwind CSS", "rationale": "Component reusability, rapid design prototyping, and responsive dashboards.", "tradeoffs": "Adds bundle size and requires a modern client build pipeline."},
            "database": {"choice": "PostgreSQL", "rationale": "ACID compliance, relational integrity, and rich JSON / time-series support.", "tradeoffs": "Requires dedicated connection pooling under heavy spikes."},
        }
        for k, v in defaults.items():
            if k not in tech_stack or not tech_stack[k]:
                tech_stack[k] = v

        competitors = [c for c in (json_output.get("competitors") or []) if isinstance(c, dict) and c.get("name")]
        live_urls = {c["url"].rstrip("/").lower() for c in citations if c.get("is_live") and c.get("url")}
        for comp in competitors:
            url = (comp.get("reference_url") or "").rstrip("/").lower()
            # Trust the citation check, not the model's own label.
            if url and url in live_urls:
                comp["evidence"] = "search"
            elif comp.get("evidence") == "search":
                comp["evidence"] = "model_knowledge"
            comp.setdefault("evidence", "model_knowledge")
        if not competitors:
            trace.append("No competitors could be identified from evidence or the model.")

        differentiators = json_output.get("key_differentiators")
        if not isinstance(differentiators, list) or not differentiators:
            differentiators = ["Automated end-to-end intelligence.", "Transparent extensible architecture."]
            if generation_source == "llm":
                generation_source, fallback_reason = "fallback", "Model returned no differentiators."

        return MarketAnalysis(
            competitors=competitors,
            tech_stack=tech_stack,
            key_differentiators=[str(d) for d in differentiators],
            citations=citations,
            trace=trace,
            implementation_pitfall=pitfall,
            generation_source=generation_source,
            fallback_reason=fallback_reason,
            search_backend=search_backend,
            live_citation_count=len(live_results),
        )

