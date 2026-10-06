"""
Idea Decomposition Agent.
Decomposes raw, unorganized project/startup ideas into structured problem statements,
target user personas, core value propositions, and essential MVP features.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from core.llm import llm_client


@dataclass
class DecomposedIdea:
    raw_idea: str
    project_title: str
    problem_statement: str
    target_personas: List[Dict[str, str]]
    core_value_prop: str
    key_assumptions: List[str]
    mvp_features: List[str]
    trace: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


IDEA_DECOMPOSITION_PROMPT = """You are an expert Startup Product Discovery & Engineering Lead Agent.
Your role is to take a raw, unstructured idea and extract a structured engineering & product brief.

CRITICAL INSTRUCTIONS:
1. Ground the problem in concrete technical reality.
2. Formulate 2-3 specific target user personas (Role, Pain Point, Benefit).
3. Identify core technical and operational assumptions.
4. List the essential MVP features needed for a working proof-of-concept.
5. Output strict JSON matching this exact schema:
{
  "project_title": "Concise, professional title for the project",
  "problem_statement": "2-3 sentences articulating the exact problem, current shortcomings, and why it matters.",
  "target_personas": [
    {
      "persona": "Primary User Role (e.g. Society Facility Manager)",
      "pain_point": "Specific frustration or bottleneck they face today",
      "expected_benefit": "What this product gives them"
    }
  ],
  "core_value_prop": "Single-sentence punchy value proposition.",
  "key_assumptions": [
    "Assumption 1: e.g. Users have access to local Wi-Fi / MQTT gateway.",
    "Assumption 2: e.g. Hardware sensor cost is under $20 per unit."
  ],
  "mvp_features": [
    "Feature 1: Real-time telemetry ingestion pipeline",
    "Feature 2: Anomaly threshold detection with alert triggers"
  ]
}
"""


class IdeaDecompositionAgent:
    def __init__(self):
        self.llm = llm_client

    def decompose(self, raw_idea: str) -> DecomposedIdea:
        """
        Decomposes a raw user idea into a structured product brief.
        """
        trace = [f"Idea Agent received raw idea: '{raw_idea[:100]}...'"]
        trace.append("Analyzing problem domain, extracting target personas, and framing MVP scope...")

        user_prompt = f"Deconstruct and structure this project idea:\n\n{raw_idea}"

        try:
            json_output = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": IDEA_DECOMPOSITION_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
        except Exception as err:
            trace.append(f"LLM decomposition note ({err}). Using structured fallback brief.")
            clean_title = " ".join(raw_idea.split()[:4]).title() or "Engineering Project"
            json_output = {
                "project_title": clean_title,
                "problem_statement": raw_idea,
                "target_personas": [
                    {"persona": "Primary User", "pain_point": "Inefficient workflows and lack of automation."}
                ],
                "core_value_prop": "Streamlines operational bottlenecks with structured automated validation.",
                "key_assumptions": ["Users require automated domain insights.", "System integration points are accessible."],
                "mvp_features": [
                    "Core telemetry and ingestion pipeline",
                    "Automated analysis and reporting engine",
                    "Interactive dashboard with alert rules"
                ]
            }

        trace.append(f"Decomposition complete: Title '{json_output.get('project_title')}' generated.")

        target_personas = json_output.get("target_personas") or []
        if not isinstance(target_personas, list) or len(target_personas) == 0:
            target_personas = [
                {"persona": "Primary Operator", "pain_point": "Manual bottlenecks and lack of real-time insights.", "expected_benefit": "Automated workflow and operational visibility."}
            ]

        mvp_features = json_output.get("mvp_features") or json_output.get("features") or []
        if not isinstance(mvp_features, list):
            mvp_features = [str(mvp_features)]
        if len(mvp_features) < 2:
            clean_title = json_output.get("project_title") or "Core System"
            mvp_features = [
                f"{clean_title} data ingestion and telemetry pipeline",
                f"{clean_title} automated analysis and anomaly trigger engine",
                f"{clean_title} interactive operations dashboard and export service",
            ]

        core_value = json_output.get("core_value_prop") or (
            f"Automated intelligence and streamlined operations for {json_output.get('project_title', 'modern workloads')}."
        )

        return DecomposedIdea(
            raw_idea=raw_idea,
            project_title=json_output.get("project_title", "Engineering Project"),
            problem_statement=json_output.get("problem_statement", raw_idea),
            target_personas=target_personas,
            core_value_prop=core_value,
            key_assumptions=json_output.get("key_assumptions", ["System endpoints are accessible.", "Domain data schemas are consistent."]),
            mvp_features=mvp_features,
            trace=trace,
        )
