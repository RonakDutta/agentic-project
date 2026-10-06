"""
Test Suite for Deterministic Conversational Follow-up Domain Routers.
Verifies that all prompt chips and key domain inquiries route deterministically
without consuming LLM tokens and without triggering rate limits.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from agents.orchestrator import orchestrator


def test_idea_followup_deterministic_routers():
    """Verifies that Idea track questions route directly to domain specialists with 0 tokens."""
    mock_context = {
        "type": "idea_validation",
        "project_title": "IoT Energy Auditor",
        "problem_statement": "Residential energy waste from unmonitored power spikes.",
        "core_value_prop": "Real-time circuit-level power spike detection using ESP32 CT sensors.",
        "target_personas": [
            {"persona": "Homeowner", "pain_point": "High bills", "expected_benefit": "30% reduction"}
        ],
        "competitors": [
            {
                "name": "Sense Energy Monitor",
                "summary": "High-frequency machine learning energy monitor.",
                "advantages": "Established brand and mobile app ecosystem.",
                "gaps": "Requires expensive installation and lacks LoRaWAN mesh.",
                "reference_url": "https://sense.com",
            }
        ],
        "reconciliation": {
            "verdict": "GO_WITH_MITIGATIONS",
            "synthesis_rationale": "Strong unit economics if hardware bill-of-materials is capped at $25.",
            "must_have_mitigations": [
                "Pre-calibrate CT sensors against utility revenue meters.",
                "Implement offline edge buffering for mesh disconnections.",
            ],
            "key_tradeoffs": [
                "Battery longevity versus telemetry frequency.",
                "Local inference versus cloud model complexity.",
            ],
        },
        "prd": {
            "user_stories": [
                {
                    "id": "US-01",
                    "persona": "Facility Manager",
                    "action": "view real-time phase balance across breaker panels",
                    "benefit": "abnormal transformer loads are detected before equipment failure",
                    "acceptance_criteria": [
                        "Dashboard refreshes telemetry at 1Hz interval",
                        "Alert fires when phase imbalance exceeds 15%",
                    ],
                }
            ],
            "functional_requirements": ["Ingest MQTT telemetry from ESP32"],
        },
        "kill_report": {
            "bear_case_summary": "High installation friction and utility pushback could stall residential adoption.",
            "fatal_flaws": [
                {
                    "title": "Breaker Box Safety Regulations",
                    "severity": "CRITICAL",
                    "argument": "Licensed electrician required for panel installation in most jurisdictions.",
                    "counter_evidence": "Split-core current transformers do not require direct wiring into mains.",
                }
            ],
            "incumbent_threats": ["Smart meter rollouts by municipal utilities."],
            "distribution_traps": ["Direct-to-consumer hardware sales have high return rates."],
        },
        "scorecard": {
            "total_score": 82,
            "verdict": "CONDITIONAL_PURSUIT",
            "rubric_disclaimer": "Feasibility score: 82/100 based on the defined project rubric.",
            "category_breakdown": {
                "technical_feasibility": {"score": 14, "max_points": 15, "weight": 15, "rationale": "Proven ESP32 stack"},
                "market_demand": {"score": 17, "max_points": 20, "weight": 20, "rationale": "High residential interest"},
            },
            "key_strengths": ["Low BOM cost", "Open-source firmware"],
            "key_risks": ["Regulatory hurdles in electrical panels"],
            "recommended_actions": ["Conduct pilot with 10 residential units"],
        },
        "tech_stack": {
            "firmware": {
                "choice": "ESP-IDF / FreeRTOS",
                "rationale": "Deterministic ADC sampling for 50Hz/60Hz AC waveforms.",
                "tradeoffs": "Requires C/C++ development instead of MicroPython.",
            }
        },
        "phases": [
            {
                "phase_number": 1,
                "phase_name": "Hardware Prototype & ADC Calibration",
                "duration_weeks": "4 weeks",
                "deliverables": ["PCB prototype", "Firmware sampling loop"],
                "exit_criteria": "Sensor accuracy within 2% of revenue meter",
            }
        ],
    }

    # 1. Competitors Router Check
    comp_res = orchestrator.answer_followup(
        query="Who are the closest market competitors to this idea?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert comp_res["status"] == "ok"
    assert comp_res["agent_name"] == "Market Research Specialist"
    assert "Sense Energy Monitor" in comp_res["answer"]
    assert "Our Differentiator" in comp_res["answer"]

    # 2. Preconditions & Tradeoffs Router Check
    precon_res = orchestrator.answer_followup(
        query="What are the non-negotiable preconditions for success?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert precon_res["status"] == "ok"
    assert precon_res["agent_name"] == "Impartial Systems Arbiter"
    assert "GO_WITH_MITIGATIONS" in precon_res["answer"]
    assert "Pre-calibrate CT sensors" in precon_res["answer"]

    # 3. User Story Router Check (US-01)
    story_res = orchestrator.answer_followup(
        query="Explain User Story US-01 and its acceptance criteria in detail.",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert story_res["status"] == "ok"
    assert story_res["agent_name"] == "Lead Product Manager"
    assert "US-01" in story_res["answer"]
    assert "Facility Manager" in story_res["answer"]
    assert "Dashboard refreshes telemetry" in story_res["answer"]

    # 4. Bottlenecks & Kill Flaws Router Check
    kill_res = orchestrator.answer_followup(
        query="What are the top 3 architectural bottlenecks in this design?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert kill_res["status"] == "ok"
    assert kill_res["agent_name"] == "Adversarial Kill Agent"
    assert "Breaker Box Safety Regulations" in kill_res["answer"]
    assert "Smart meter rollouts" in kill_res["answer"]

    # 5. Scorecard Router Check
    score_res = orchestrator.answer_followup(
        query="What is the feasibility score and rubric breakdown?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert score_res["status"] == "ok"
    assert score_res["agent_name"] == "Deterministic Decision Scorer"
    assert "82/100" in score_res["answer"]
    assert "CONDITIONAL_PURSUIT" in score_res["answer"]

    # 6. Tech Stack Router Check
    stack_res = orchestrator.answer_followup(
        query="What is the recommended tech stack and database?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert stack_res["status"] == "ok"
    assert stack_res["agent_name"] == "Lead Systems Architect"
    assert "ESP-IDF / FreeRTOS" in stack_res["answer"]

    # 7. Roadmap Router Check
    road_res = orchestrator.answer_followup(
        query="What is the development roadmap and milestone timeline?",
        context=mock_context,
        session_id="test_sess_01",
    )
    assert road_res["status"] == "ok"
    assert road_res["agent_name"] == "Roadmap & Delivery Planner"
    assert "Hardware Prototype" in road_res["answer"]


def test_code_followup_deterministic_routers():
    """Verifies that Code track questions route directly to Code Review & AST Specialist."""
    mock_context = {
        "type": "codebase_analysis",
        "candidates": [
            {
                "rank": 1,
                "symbol_name": "verify_token",
                "file_path": "auth.py",
                "line_start": 8,
                "line_end": 24,
                "why_problematic": "Does not catch ExpiredSignatureError before verifying payload.",
                "wrong_code": "jwt.decode(token, SECRET, algorithms=['HS256'])",
                "recommended_pattern": "try:\n    jwt.decode(token, SECRET, algorithms=['HS256'])\nexcept jwt.ExpiredSignatureError:\n    return None",
                "explanation_of_change": "Handle ExpiredSignatureError explicitly without raising uncaught 500 error.",
                "suggested_fix": "Add try/except block around token decoding.",
            }
        ],
    }

    res = orchestrator.answer_followup(
        query="Where is customer auth verified and what is the educational pattern?",
        context=mock_context,
        session_id="test_sess_02",
    )
    assert res["status"] == "ok"
    assert res["agent_name"] == "Code Review & AST Specialist"
    assert "verify_token" in res["answer"]
    assert "auth.py:8-24" in res["answer"]
    assert "Recommended Pattern" in res["answer"]


def _idea_direct_ctx():
    return {
        "type": "idea_validation",
        "project_title": "IoT Energy Auditor",
        "problem_statement": "Residential energy waste from unmonitored power spikes.",
        "core_value_prop": "Real-time circuit-level spike detection with ESP32 sensors.",
        "mvp_features": ["Live spike alerts", "Weekly waste report"],
        "competitors": [{"name": "Sense", "summary": "ML energy monitor", "advantages": "Brand", "gaps": "Expensive"}],
        "key_differentiators": ["Open-source firmware"],
        "tech_stack": {"backend": {"choice": "FastAPI", "rationale": "High throughput", "tradeoffs": "None"}},
        "phases": [
            {
                "phase_number": 1,
                "phase_name": "Prototype",
                "duration_weeks": "4 weeks",
                "deliverables": ["PCB", "Firmware loop"],
                "exit_criteria": "Accuracy within 2%",
            }
        ],
        "risks": [{"risk": "Parts shortage", "mitigation": "Dual-source suppliers"}],
        "scorecard": {
            "total_score": 82,
            "verdict": "CONDITIONAL_PURSUIT",
            "categories": [{"category_name": "Market Demand", "score": 17, "max_score": 20, "rationale": "High interest"}],
            "key_strengths": ["Low BOM cost"],
            "key_risks": ["Regulatory hurdles"],
        },
    }


def _code_direct_ctx():
    return {
        "type": "codebase_analysis",
        "candidates": [
            {
                "rank": 1,
                "symbol_name": "verify_token",
                "file_path": "auth.py",
                "line_start": 8,
                "line_end": 24,
                "why_problematic": "Does not catch ExpiredSignatureError before verifying payload.",
            }
        ],
        "indexed_summary": {
            "total_files": 3,
            "total_chunks": 12,
            "total_symbols": 20,
            "files": ["auth.py", "main.py", "orders.py"],
        },
        "critic": {"is_valid": True, "grounding_score": 0.83, "total_verified": 1, "flags": []},
    }


def test_direct_agent_interrogation():
    """Only the 4 pipeline agents per track answer as specialists.

    The LLM is forced down so every answer comes from the deterministic
    evidence path (zero tokens, fully reproducible).
    """
    from unittest import mock
    from core.llm import llm_client

    with mock.patch.object(llm_client, "generate", side_effect=RuntimeError("simulated outage")):
        idea = _idea_direct_ctx()
        for key, needle in [
            ("idea", "Residential energy waste"),
            ("market", "Sense"),
            ("roadmap", "Prototype"),
            ("critic", "82/100"),
        ]:
            res = orchestrator.answer_followup(
                query=f"@{key} what did you find?",
                context=idea,
                session_id="test_direct_idea",
            )
            assert res["status"] == "ok", key
            assert res["direct_agent"] == key, key
            assert needle in res["answer"], key

        code = _code_direct_ctx()
        for key, needle in [
            ("planner", "Indexed 3 files"),
            ("navigate", "verify_token"),
            ("diagnose", "ExpiredSignatureError"),
            ("critic", "83%"),
        ]:
            res = orchestrator.answer_followup(
                query=f"@{key} what did you find?",
                context=code,
                session_id="test_direct_code",
            )
            assert res["status"] == "ok", key
            assert res["direct_agent"] == key, key
            assert needle in res["answer"], key


def test_out_of_scope_mentions_get_future_scope_notice():
    """@keys outside the 4-agent build never answer as specialists (no LLM spent)."""
    idea = _idea_direct_ctx()
    res = orchestrator.answer_followup(
        query="@kill why will this fail?",
        context=idea,
        session_id="test_scope_idea",
    )
    assert res["status"] == "ok"
    assert "future scope" in res["answer"].lower()
    assert "@idea" in res["answer"] and "@critic" in res["answer"]

    # Cross-pillar mentions are also out of scope.
    code = _code_direct_ctx()
    res = orchestrator.answer_followup(
        query="@market who are our rivals?",
        context=code,
        session_id="test_scope_code",
    )
    assert res["status"] == "ok"
    assert "future scope" in res["answer"].lower()
    assert "@diagnose" in res["answer"]

    # @tokens buried in pasted text (emails, decorators) are not mentions.
    res = orchestrator.answer_followup(
        query="the decorator @app.route handles login in main",
        context=code,
        session_id="test_scope_buried",
    )
    assert "future scope" not in res["answer"].lower()
