"""
Phase 5 Test Suite: Verifies Idea Validation Pipeline:
WebSearchTool -> IdeaDecompositionAgent -> MarketTechStackAgent -> RoadmapRiskAgent.
"""

import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from tools.search_tool import web_search_tool
from agents.idea_agent import IdeaDecompositionAgent
from agents.market_agent import MarketTechStackAgent
from agents.roadmap_agent import RoadmapRiskAgent


def test_idea_pipeline():
    print("[1/4] Testing WebSearchTool resilience and citations...")
    search_results = web_search_tool.search("IoT energy auditing ESP32", max_results=3)
    assert len(search_results) > 0
    print(f"      Retrieved {len(search_results)} citations: '{search_results[0].title}'")
    assert search_results[0].url.startswith("http")

    raw_idea = (
        "A low-cost IoT energy monitoring system for residential apartment societies "
        "that uses ESP32 with CT current sensors to detect abnormal power spikes and alert residents."
    )

    # 2. Decompose Idea
    print("\n[2/4] Running IdeaDecompositionAgent...")
    idea_agent = IdeaDecompositionAgent()
    decomposed = idea_agent.decompose(raw_idea)
    print(f"      Project Title: {decomposed.project_title}")
    print(f"      Problem: {decomposed.problem_statement[:100]}...")
    print(f"      Personas: {[p.get('persona') for p in decomposed.target_personas]}")
    assert decomposed.project_title != ""
    assert len(decomposed.target_personas) >= 1
    assert len(decomposed.mvp_features) >= 2

    # 3. Market & Tech Stack Analysis
    print("\n[3/4] Running MarketTechStackAgent with live/curated intelligence...")
    market_agent = MarketTechStackAgent()
    market = market_agent.analyze(decomposed)
    print(f"      Competitors identified: {[c.get('name') for c in market.competitors]}")
    print(f"      Recommended Stack: Backend={market.tech_stack.get('backend', {}).get('choice')}, Frontend={market.tech_stack.get('frontend', {}).get('choice')}")
    assert len(market.competitors) >= 1
    assert "backend" in market.tech_stack

    # 4. Roadmap & Risk Synthesis
    print("\n[4/4] Running RoadmapRiskAgent for 3-phase milestones...")
    roadmap_agent = RoadmapRiskAgent()
    report = roadmap_agent.generate(decomposed, market)
    print(f"      Phases created: {len(report.phases)}")
    for p in report.phases:
        print(f"      - {p.phase_name} ({p.duration_weeks}): {p.deliverables[:2]}")
    print(f"      Identified Risks: {len(report.risks)}")
    assert len(report.phases) == 3
    assert len(report.risks) >= 2
    assert len(report.evaluation_tips) >= 1

    print("\nAll Phase 5 Idea Validation tests passed successfully!")


if __name__ == "__main__":
    test_idea_pipeline()
