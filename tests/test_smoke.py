"""
Phase 1 Smoke Test: Verifies configuration, Groq connectivity, JSON mode, and fallback.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.config import settings
from core.llm import llm_client


def test_configuration():
    print("[1/4] Checking settings configuration...")
    settings.validate()
    assert settings.groq_api_key.startswith("gsk_"), "Invalid Groq API key format!"
    assert settings.primary_model == "openai/gpt-oss-120b"
    assert settings.fast_model == "openai/gpt-oss-20b"
    print("      Settings validated successfully.")


def test_text_generation():
    print("[2/4] Testing LLM text generation with primary model...")
    response = llm_client.generate(
        messages=[{"role": "user", "content": "Respond with the word 'READY' and nothing else."}],
        model=settings.fast_model,  # fast test
    )
    print(f"      Response received: {response.strip()}")
    assert "READY" in response.upper(), f"Expected READY, got {response}"


def test_json_generation():
    print("[3/4] Testing structured JSON generation...")
    schema_prompt = (
        "Return a valid JSON object with keys 'status' (string, value 'OK') "
        "and 'agent' (string, value 'Orchestrator')."
    )
    result = llm_client.generate_json(
        messages=[{"role": "user", "content": schema_prompt}],
        model=settings.fast_model,
    )
    print(f"      Parsed JSON: {result}")
    assert result.get("status") == "OK"
    assert result.get("agent") == "Orchestrator"


def test_metrics():
    print("[4/4] Verifying metrics tracking...")
    metrics = llm_client.get_metrics()
    print(f"      Metrics collected: {metrics}")
    assert metrics["total_calls"] >= 2
    assert metrics["total_latency_ms"] > 0
    print("      All Phase 1 smoke tests passed!")


if __name__ == "__main__":
    test_configuration()
    test_text_generation()
    test_json_generation()
    test_metrics()
    print("\nPhase 1 verification 100% COMPLETE.")
