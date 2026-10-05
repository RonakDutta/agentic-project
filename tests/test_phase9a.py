"""
Test Suite for Phase 9A Foundation:
- ContextBudgetManager (Task 9.11)
- RepoMapGenerator (Task 9.13)
- DeterministicCriticAgent Citation Validator (Task 9.10)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer, CodeChunk
from indexer.context_budget import ContextBudgetManager, EvidenceItem
from indexer.repo_map import RepoMapGenerator
from agents.critic_agent import DeterministicCriticAgent, validate_code_citation
from agents.diagnosis_agent import DiagnosisResult, FaultCandidate
from tests.test_ast_parser import create_mock_repository


def test_context_budget_manager():
    print("\n--- Testing ContextBudgetManager (Task 9.11) ---")
    cbm = ContextBudgetManager(default_budget=200)

    # 1. Test token estimation
    sample_text = "def calculate_sum(a: int, b: int) -> int:\n    return a + b\n"
    tokens = cbm.estimate_tokens(sample_text)
    assert tokens > 0
    print(f"Token estimation for short function: {tokens} tokens")

    # 2. Test packing candidates with priority
    items = [
        EvidenceItem(
            id="item1",
            file_path="auth/jwt.py",
            name="verify_token",
            chunk_type="function",
            code="def verify_token(t): return validate(t)",
            start_line=10,
            end_line=15,
            relevance_score=0.95,
            priority=1,  # Highest
        ),
        EvidenceItem(
            id="item2",
            file_path="orders/processor.py",
            name="process_order",
            chunk_type="function",
            code="def process_order(o):\n    auth = verify_token(o.token)\n    return db.save(o)",
            start_line=20,
            end_line=30,
            relevance_score=0.85,
            priority=2,  # Medium
        ),
        EvidenceItem(
            id="item3",
            file_path="utils/helpers.py",
            name="log_event",
            chunk_type="function",
            code="def log_event(e):\n" + "    print('Logging event:', e)\n" * 30,  # Long chunk to trigger budget exceed
            start_line=1,
            end_line=50,
            relevance_score=0.30,
            priority=4,  # Lowest
        ),
    ]

    packed = cbm.pack_context(items, budget=120)
    print(f"Packed {len(packed.selected_items)} items, discarded {len(packed.discarded_items)} items.")
    print(f"Total tokens: {packed.total_tokens} / Budget: {packed.token_budget}")

    assert len(packed.selected_items) >= 1
    # Priority 1 must be selected first
    assert packed.selected_items[0].name == "verify_token"
    # Long low priority item should be discarded due to budget
    assert any(it.name == "log_event" for it in packed.discarded_items)
    assert "Retrieved Codebase Evidence" in packed.formatted_prompt_text
    print("✓ ContextBudgetManager passed all checks.")


def test_repo_map_generator():
    print("\n--- Testing RepoMapGenerator (Task 9.13) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_repomap_test_")
    try:
        create_mock_repository(temp_dir)
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        codebase_index = indexer.index()

        generator = RepoMapGenerator()
        repo_map = generator.generate(codebase_index)

        print(f"Repo Map Name: {repo_map.repo_name}")
        print(f"Total files: {repo_map.total_files}, Total symbols: {repo_map.total_symbols}")
        print(f"Detected Frameworks: {repo_map.frameworks}")
        print(f"Entry points found: {len(repo_map.entry_points)}")
        print("\nCompact Map Preview:\n" + repo_map.compact_text[:400] + "...\n")

        assert repo_map.total_files >= 2
        assert repo_map.total_symbols >= 4
        assert len(repo_map.compact_text) > 50
        assert "auth/jwt_service.py" in repo_map.compact_text or "api/routes.py" in repo_map.compact_text
        print("✓ RepoMapGenerator passed all checks.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_deterministic_critic_citations():
    print("\n--- Testing DeterministicCriticAgent Citation Validator (Task 9.10) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_critic_test_")
    try:
        create_mock_repository(temp_dir)
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        codebase_index = indexer.index()

        critic = DeterministicCriticAgent(codebase_index)

        # 1. Test valid citation
        res_valid = validate_code_citation(
            file_path="auth/jwt_service.py",
            symbol_name="verify_token",
            line_start=1,
            line_end=50,
            codebase_index=codebase_index,
        )
        assert res_valid["is_valid"] is True
        assert res_valid["file_exists"] is True
        assert res_valid["symbol_exists"] is True
        print("✓ Valid citation verified successfully.")

        # 2. Test hallucinated file citation
        res_fake_file = validate_code_citation(
            file_path="non_existent/fake_module.py",
            symbol_name="verify_token",
            line_start=1,
            line_end=10,
            codebase_index=codebase_index,
        )
        assert res_fake_file["is_valid"] is False
        assert res_fake_file["file_exists"] is False
        print("✓ Hallucinated file correctly rejected.")

        # 3. Test verification against retrieved evidence
        retrieved_chunk = CodeChunk(
            id="auth/jwt_service.py:verify_token",
            file_path="auth/jwt_service.py",
            chunk_type="function",
            name="verify_token",
            signature="def verify_token(token)",
            start_line=1,
            end_line=50,
            code="def verify_token(): pass",
        )

        diag_result = DiagnosisResult(
            query="Test query",
            ranked_candidates=[
                FaultCandidate(
                    rank=1,
                    file_path="auth/jwt_service.py",
                    symbol_name="verify_token",
                    line_start=5,
                    line_end=45,
                    confidence="high",
                    root_cause_hypothesis="Token expired",
                    suggested_fix="Catch ValueError",
                ),
                FaultCandidate(
                    rank=2,
                    file_path="non_existent/service.py",
                    symbol_name="ghost_function",
                    line_start=1,
                    line_end=10,
                    confidence="low",
                    root_cause_hypothesis="Hallucinated",
                    suggested_fix="None",
                ),
            ],
            summary="Test diagnosis",
            trace=[],
        )

        report = critic.verify(diag_result, retrieved_chunks=[retrieved_chunk])
        print(f"Critic report valid candidates: {len(report.verified_candidates)}")
        print(f"Grounding score: {report.grounding_score}")
        print(f"Flags raised: {report.flags}")
        print(f"Repair hints: {report.repair_hints}")

        assert len(report.verified_candidates) == 1
        assert report.verified_candidates[0].symbol_name == "verify_token"
        assert any("non_existent" in flag for flag in report.flags)
        assert len(report.repair_hints) > 0
        print("✓ DeterministicCriticAgent citation validation passed all checks.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_context_budget_manager()
    test_repo_map_generator()
    test_deterministic_critic_citations()
