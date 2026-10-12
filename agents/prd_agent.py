"""
MetaGPT-Style Product Requirements Document (PRD) and Architecture Engine.
Inspired by MetaGPT and PRISM.

Task 9.4:
Generates formal Product Requirements Documents:
- Product Vision & Goals
- User Stories with Acceptance Criteria (US-01, US-02)
- Functional Requirements with Priority (FR-01, FR-02)
- Non-Functional Requirements (Performance, Security, Reliability, Scalability)
- Multi-perspective Mermaid Diagrams (System Architecture, Component Topology, Dataflow Sequence)
"""

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from core.llm import llm_client, AGENT_MAX_TOKENS
from agents.idea_agent import DecomposedIdea
from agents.market_agent import MarketAnalysis
from agents.kill_agent import ReconciliationResult


@dataclass
class UserStory:
    story_id: str
    persona: str
    want: str
    so_that: str
    acceptance_criteria: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionalRequirement:
    req_id: str
    title: str
    description: str
    priority: str  # 'Must Have', 'Should Have', 'Nice to Have'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PRDDocument:
    project_title: str
    product_vision: str
    target_audience_summary: str
    user_stories: List[UserStory]
    functional_requirements: List[FunctionalRequirement]
    non_functional_requirements: Dict[str, str]
    architecture_diagram_mermaid: str
    component_diagram_mermaid: str
    dataflow_diagram_mermaid: str
    trace: List[str] = field(default_factory=list)
    generation_source: str = "llm"
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "product_vision": self.product_vision,
            "target_audience_summary": self.target_audience_summary,
            "user_stories": [s.to_dict() for s in self.user_stories],
            "functional_requirements": [r.to_dict() for r in self.functional_requirements],
            "non_functional_requirements": self.non_functional_requirements,
            "architecture_diagram_mermaid": self.architecture_diagram_mermaid,
            "component_diagram_mermaid": self.component_diagram_mermaid,
            "dataflow_diagram_mermaid": self.dataflow_diagram_mermaid,
            "trace": self.trace,
            "generation_source": self.generation_source,
            "fallback_reason": self.fallback_reason,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Product Requirements Document (PRD): {self.project_title}",
            "",
            "## 1. Product Vision & Target Audience",
            f"**Vision**: {self.product_vision}",
            "",
            f"**Target Audience**: {self.target_audience_summary}",
            "",
            "## 2. User Stories & Acceptance Criteria",
        ]
        for s in self.user_stories:
            lines.extend([
                f"### {s.story_id}: {s.persona}",
                f"- **As a**: {s.persona}",
                f"- **I want to**: {s.want}",
                f"- **So that**: {s.so_that}",
                "- **Acceptance Criteria**:",
            ])
            for ac in s.acceptance_criteria:
                lines.append(f"  * [ ] {ac}")
            lines.append("")

        lines.extend([
            "## 3. Functional Requirements",
            "| ID | Title | Priority | Description |",
            "|:---|:---|:---:|:---|",
        ])
        for fr in self.functional_requirements:
            lines.append(f"| {fr.req_id} | {fr.title} | `{fr.priority}` | {fr.description} |")

        lines.extend([
            "",
            "## 4. Non-Functional Requirements",
        ])
        for nfr_key, nfr_val in self.non_functional_requirements.items():
            lines.append(f"- **{nfr_key.capitalize()}**: {nfr_val}")

        lines.extend([
            "",
            "## 5. System Architecture Diagrams",
            "### High-Level Architecture",
            "```mermaid",
            self.architecture_diagram_mermaid,
            "```",
            "",
            "### Component Interaction Topology",
            "```mermaid",
            self.component_diagram_mermaid,
            "```",
            "",
            "### End-to-End Dataflow Sequence",
            "```mermaid",
            self.dataflow_diagram_mermaid,
            "```",
        ])
        return "\n".join(lines)


PRD_SYSTEM_PROMPT = """You are a Principal Product Manager and Enterprise Software Architect (inspired by MetaGPT).
Your role is to transform a product brief and architecture into a formal, production-grade Product Requirements Document (PRD)
and structured Mermaid architecture diagrams.

CRITICAL INSTRUCTIONS:
1. Formulate 2-3 detailed User Stories with concrete acceptance criteria (US-01, US-02).
2. Define 3-5 prioritized Functional Requirements (FR-01, FR-02 with 'Must Have', 'Should Have', 'Nice to Have').
3. Define Non-Functional Requirements (performance, security, scalability, observability).
4. Output strict JSON matching this exact schema:
{
  "product_vision": "2-3 sentence inspiring yet grounded product vision statement.",
  "target_audience_summary": "1-2 sentence overview of ideal customer profile and early adopter segment.",
  "user_stories": [
    {
      "story_id": "US-01",
      "persona": "Specific target role",
      "want": "What action or tool they want",
      "so_that": "The concrete business or workflow benefit",
      "acceptance_criteria": [
        "Criterion 1",
        "Criterion 2"
      ]
    }
  ],
  "functional_requirements": [
    {
      "req_id": "FR-01",
      "title": "Short title",
      "description": "Precise description of expected behavior and boundaries",
      "priority": "Must Have or Should Have or Nice to Have"
    }
  ],
  "non_functional_requirements": {
    "performance": "e.g. API response latency under 300ms at p95",
    "security": "e.g. Encrypted data in transit (TLS 1.3) and at rest (AES-256)",
    "scalability": "e.g. Horizontally scalable stateless worker containers",
    "observability": "e.g. Structured JSON logging and Prometheus metric endpoints"
  }
}
"""


def mermaid_label(text: Any, limit: int = 48) -> str:
    """Makes free text safe inside a quoted Mermaid label (quotes, brackets, pipes break the parser)."""
    clean = re.sub(r'["`<>{}\[\]|;#]', " ", str(text or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    # Drop "Feature 1:" style prefixes the decomposer adds.
    clean = re.sub(r"^(feature|mvp)\s*\d*\s*:\s*", "", clean, flags=re.IGNORECASE)
    if len(clean) > limit:
        clean = clean[: limit - 3].rstrip() + "..."
    return clean or "Component"


def mermaid_message(text: Any, limit: int = 60) -> str:
    """Sequence-diagram message text: no colons/semicolons, which end the message early."""
    return mermaid_label(text, limit).replace(":", " ")


class PRDAgent:
    """
    Generates formal PRDs and multi-diagram Mermaid architectural models.
    """

    def __init__(self):
        self.llm = llm_client

    @staticmethod
    def _safe_choice(stack: Dict[str, Any], key: str, default: str) -> str:
        if not isinstance(stack, dict):
            return default
        val = stack.get(key)
        if isinstance(val, dict):
            return val.get("choice", default) or default
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list) and val:
            return ", ".join(str(x) for x in val)
        return default

    def generate(
        self,
        decomposed: DecomposedIdea,
        market: MarketAnalysis,
        reconciler_result: Optional[ReconciliationResult] = None,
    ) -> PRDDocument:
        trace = [f"PRDAgent activated: Authoring formal PRD and architecture models for '{decomposed.project_title}'"]

        backend_choice = self._safe_choice(market.tech_stack, "backend", "FastAPI")
        frontend_choice = self._safe_choice(market.tech_stack, "frontend", "React")
        db_choice = self._safe_choice(market.tech_stack, "database", "PostgreSQL")

        user_content = (
            f"Project Title: {decomposed.project_title}\n"
            f"Problem Statement: {decomposed.problem_statement}\n"
            f"Personas: {[p.get('persona') for p in decomposed.target_personas]}\n"
            f"Core Value Prop: {decomposed.core_value_prop}\n"
            f"MVP Features: {decomposed.mvp_features}\n"
            f"Backend Stack: {backend_choice}\n"
            f"Frontend Stack: {frontend_choice}\n"
            f"Database: {db_choice}\n\n"
            "Author a formal Product Requirements Document matching the requested JSON schema."
        )

        trace.append("Querying Groq LLM for formal PRD user stories and functional requirements...")
        generation_source, fallback_reason = "llm", ""
        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": PRD_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=AGENT_MAX_TOKENS["prd"],
            )
        except Exception as err:
            trace.append(f"PRD LLM note ({err}). Using structured MetaGPT specification fallback.")
            generation_source, fallback_reason = "fallback", f"LLM unavailable: {err}"
            res = {}

        # Parse User Stories
        raw_stories = res.get("user_stories") or []
        user_stories: List[UserStory] = []
        for idx, s in enumerate([x for x in raw_stories if isinstance(x, dict)] if isinstance(raw_stories, list) else [], 1):
            criteria = s.get("acceptance_criteria") or ["Feature operates without uncaught exceptions"]
            user_stories.append(
                UserStory(
                    story_id=s.get("story_id", f"US-0{idx}"),
                    persona=s.get("persona", "End User"),
                    want=s.get("want", "Access system dashboard"),
                    so_that=s.get("so_that", "I can manage project operations effectively"),
                    acceptance_criteria=[str(c) for c in criteria] if isinstance(criteria, list) else [str(criteria)],
                )
            )

        if not user_stories:
            user_stories.append(
                UserStory(
                    story_id="US-01",
                    persona=decomposed.target_personas[0].get("persona", "Target User") if decomposed.target_personas else "Developer",
                    want=f"Use {decomposed.project_title} to solve core bottlenecks",
                    so_that=decomposed.core_value_prop,
                    acceptance_criteria=[
                        "User can successfully authenticate into the workspace",
                        "System produces validated insights within standard timeouts"
                    ],
                )
            )

        # Parse Functional Requirements
        raw_frs = res.get("functional_requirements") or []
        functional_reqs: List[FunctionalRequirement] = []
        for idx, fr in enumerate([x for x in raw_frs if isinstance(x, dict)] if isinstance(raw_frs, list) else [], 1):
            functional_reqs.append(
                FunctionalRequirement(
                    req_id=fr.get("req_id", f"FR-0{idx}"),
                    title=fr.get("title", f"Feature {idx}"),
                    description=fr.get("description", "System delivers specified functionality."),
                    priority=fr.get("priority", "Must Have"),
                )
            )

        if len(functional_reqs) < 2:
            existing_titles = {f.title.lower() for f in functional_reqs}
            for idx, feat in enumerate(decomposed.mvp_features, start=len(functional_reqs) + 1):
                title = feat[:30]
                if title.lower() not in existing_titles:
                    functional_reqs.append(
                        FunctionalRequirement(
                            req_id=f"FR-0{idx}",
                            title=title,
                            description=feat,
                            priority="Must Have" if idx <= 2 else "Should Have",
                        )
                    )
                if len(functional_reqs) >= 3:
                    break

        nfrs = res.get("non_functional_requirements")
        if not isinstance(nfrs, dict) or not nfrs:
            nfrs = {
                "performance": "Sub-500ms p95 API response times on standard requests.",
                "security": "Enforce strict role-based access control and TLS in transit.",
                "scalability": "Stateless API server design supporting horizontal autoscaling.",
                "observability": "End-to-end tracing and health check endpoints.",
            }

        # Deterministic Mermaid diagrams, built from this idea's stack and MVP
        # features so every project gets its own topology (not a fixed template).
        fe_choice = mermaid_label(self._safe_choice(market.tech_stack, "frontend", "React Dashboard"))
        be_choice = mermaid_label(self._safe_choice(market.tech_stack, "backend", "FastAPI Service"))
        db_choice = mermaid_label(self._safe_choice(market.tech_stack, "database", "PostgreSQL Database"))
        features = [mermaid_label(f, 40) for f in decomposed.mvp_features[:4]] or ["Core Processing Engine"]
        persona = mermaid_label(
            decomposed.target_personas[0].get("persona", "User") if decomposed.target_personas else "User", 30
        )

        # 1. High-Level Architecture Diagram
        arch_lines = [
            "graph TD",
            f'    Client["{persona}<br/>{fe_choice}"] -->|HTTPS / REST| Gateway["API Layer<br/>{be_choice}"]',
            '    Gateway --> Auth["Authentication & Sessions"]',
        ]
        for i, feat in enumerate(features, 1):
            arch_lines.append(f'    Gateway --> F{i}["{feat}"]')
            arch_lines.append(f"    F{i} --> Storage")
        arch_lines.append(f'    Storage[("{db_choice}")]')
        arch_lines.append('    Gateway --> Telemetry["Logging & Monitoring"]')
        arch_mermaid = "\n".join(arch_lines)

        # 2. Component Interaction Topology: one service per MVP feature.
        comp_lines = [
            "graph LR",
            f'    UI["{fe_choice}"] --> API["{be_choice} controllers"]',
            f'    DB[("{db_choice}")]',
        ]
        for i, feat in enumerate(features, 1):
            comp_lines.append(f'    API --> S{i}["{feat}"]')
            comp_lines.append(f"    S{i} --> DB")
        if len(features) > 1:
            comp_lines.append(f'    S1 -.->|events| S2')
        comp_mermaid = "\n".join(comp_lines)

        # 3. End-to-End Dataflow Sequence for the first (primary) MVP feature.
        primary = mermaid_message(features[0], 50)
        dataflow_mermaid = "\n".join([
            "sequenceDiagram",
            "    autonumber",
            f"    actor User as {mermaid_message(persona, 30)}",
            f"    participant UI as {mermaid_message(fe_choice, 30)}",
            f"    participant API as {mermaid_message(be_choice, 30)}",
            f"    participant DB as {mermaid_message(db_choice, 30)}",
            f"    User->>UI: Starts {primary}",
            "    UI->>API: Sends request with validated input",
            "    API->>DB: Reads or stores the records it needs",
            "    DB-->>API: Returns the stored state",
            "    API-->>UI: Returns the result as JSON",
            "    UI-->>User: Shows the updated view",
        ])

        trace.append(f"PRD generated with {len(user_stories)} user stories, {len(functional_reqs)} functional requirements, and 3 Mermaid diagrams.")

        return PRDDocument(
            project_title=decomposed.project_title,
            product_vision=str(res.get("product_vision") or f"Deliver accessible, reliable solutions for {decomposed.project_title}."),
            target_audience_summary=str(res.get("target_audience_summary") or "Early-adopter engineering teams and operations managers."),
            user_stories=user_stories,
            functional_requirements=functional_reqs,
            non_functional_requirements=nfrs,
            architecture_diagram_mermaid=arch_mermaid,
            component_diagram_mermaid=comp_mermaid,
            dataflow_diagram_mermaid=dataflow_mermaid,
            trace=trace,
            generation_source=generation_source,
            fallback_reason=fallback_reason,
        )


prd_agent = PRDAgent()
