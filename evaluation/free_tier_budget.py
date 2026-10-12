"""
Groq Free-Tier Budget Check.

Runs one idea-validation and one code-analysis pipeline with the LLM stubbed
out, records every prompt the agents would send, and checks the token plan
against the free-tier limits in core/config.py (FREE_TIER_* env vars).
No API key and no quota are used.

What it reports:
- prompt tokens (estimated, ~4 chars/token) and max_tokens per call
- "reserved" tokens per run = prompt + max_tokens (what Groq checks against TPM)
- whether a run fits the pooled per-minute window of the model chain
- how many runs per day the daily token limit allows (using a realistic output size)

Run: python evaluation/free_tier_budget.py
"""

import logging
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
os.environ.setdefault("LLM_DISK_CACHE", "0")
os.environ.setdefault("LLM_USAGE_LEDGER", "0")
logging.disable(logging.CRITICAL)

from core.config import settings  # noqa: E402
from core.llm import llm_client, _estimate_messages_tokens  # noqa: E402

# With reasoning_effort=low, structured answers typically use about half their
# max_tokens. Used only for the per-day estimate; change it after measuring.
TYPICAL_OUTPUT_SHARE = 0.5

IDEA = ("A smart ultrasonic water meter for residential buildings using LoRaWAN to detect "
        "pipe leakages in real time and estimate daily household consumption.")
BUG = "ValueError: Token expired when verify_token validates customer credentials during checkout."


def measure(run) -> list:
    calls = []

    def spy(messages, model=None, temperature=None, json_mode=False, max_tokens=None):
        styled = llm_client._with_style_rules(messages)
        system = next((m["content"] for m in styled if m["role"] == "system"), "")
        calls.append({
            "agent": system.splitlines()[0][:48] if system else "?",
            "prompt": _estimate_messages_tokens(styled),
            "max_tokens": min(max_tokens or settings.max_tokens_per_req, settings.max_tokens_cap),
        })
        raise RuntimeError("budget check: LLM stubbed")

    original = llm_client.generate
    llm_client.generate = spy
    try:
        run()
    finally:
        llm_client.generate = original
    return calls


def report(title: str, calls: list, chain: int) -> None:
    reserved = sum(c["prompt"] + c["max_tokens"] for c in calls)
    typical = sum(c["prompt"] + int(c["max_tokens"] * TYPICAL_OUTPUT_SHARE) for c in calls)
    pooled_tpm = settings.free_tier_tpm * chain
    pooled_tpd = settings.free_tier_tpd * chain
    biggest = max((c["prompt"] + c["max_tokens"] for c in calls), default=0)
    print(f"\n{title}: {len(calls)} LLM calls")
    for c in calls:
        print(f"  {c['prompt']:>6} prompt + {c['max_tokens']:>5} max = {c['prompt'] + c['max_tokens']:>6}  {c['agent']}")
    print(f"  Reserved per run: {reserved} tokens (pooled TPM over {chain} models: {pooled_tpm})")
    print(f"  Largest single call: {biggest} tokens (per-model TPM: {settings.free_tier_tpm}) "
          f"-> {'fits' if biggest <= settings.free_tier_tpm - settings.budget_safety_margin else 'DOES NOT FIT'}")
    print(f"  One run inside one minute: {'yes' if reserved <= pooled_tpm else 'no, it will wait for windows to refill'}")
    print(f"  Typical tokens per run: ~{typical} -> about {pooled_tpd // max(1, typical)} runs/day "
          f"on {chain} x {settings.free_tier_tpd} TPD; requests/day allow {settings.free_tier_rpd * chain // max(1, len(calls))}")


def main() -> None:
    from agents.orchestrator import orchestrator

    chain = len(settings.model_chain)
    print("=" * 76)
    print(f"GROQ FREE-TIER BUDGET CHECK  (chain: {', '.join(settings.model_chain)})")
    print(f"Limits per model: {settings.free_tier_rpm} RPM, {settings.free_tier_rpd} RPD, "
          f"{settings.free_tier_tpm} TPM, {settings.free_tier_tpd} TPD")
    print("=" * 76)
    idea_calls = measure(lambda: orchestrator.process(IDEA, force_intent="idea_validation"))
    report("Idea validation run", idea_calls, chain)
    code_calls = measure(lambda: orchestrator.process(
        BUG, repo_path=str(ROOT_DIR / "sample_repo"), force_intent="codebase_analysis"))
    report("Code analysis run (sample_repo, no revision)", code_calls, chain)
    print("\nToken counts are estimates (~4 characters per token). Limits come from secondary")
    print("sources; confirm yours at console.groq.com/settings/limits and set FREE_TIER_* if different.")


if __name__ == "__main__":
    main()
