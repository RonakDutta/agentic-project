"""
Phase 4 Test Suite: Verifies end-to-end Code Intelligence pipeline:
CodeNavigationAgent -> DiagnosisAgent -> DeterministicCriticAgent.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer
from indexer.hybrid_retriever import HybridRetriever
from agents.code_nav_agent import CodeNavigationAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.critic_agent import DeterministicCriticAgent
from tests.test_ast_parser import create_mock_repository


def test_code_agents_pipeline():
    temp_dir = tempfile.mkdtemp(prefix="agentic_code_pipeline_")
    try:
        create_mock_repository(temp_dir)

        print("[1/4] Indexing repository with AST & Hybrid Retriever...")
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        codebase_index = indexer.index()
        retriever = HybridRetriever(codebase_index=codebase_index, prefer_neural=True)

        nav_agent = CodeNavigationAgent(codebase_index=codebase_index, retriever=retriever)
        diag_agent = DiagnosisAgent()
        critic_agent = DeterministicCriticAgent(codebase_index=codebase_index)

        # 2. Run Navigation Agent
        query = "User authentication throws ValueError: Token expired when verify_token validates the session."
        print(f"[2/4] Running CodeNavigationAgent with query:\n      '{query}'...")
        nav_result = nav_agent.navigate(query, top_k=3)
        assert len(nav_result.candidate_chunks) > 0
        candidate_names = [c.name for c in nav_result.candidate_chunks]
        print(f"      Navigation identified candidates: {candidate_names}")
        assert "verify_token" in candidate_names or "JWTAuthService" in candidate_names

        # 3. Run Diagnosis Agent
        print("[3/4] Running DiagnosisAgent with Groq reasoning...")
        diag_result = diag_agent.diagnose(nav_result)
        assert len(diag_result.ranked_candidates) > 0
        top_cand = diag_result.ranked_candidates[0]
        print(f"      Rank 1 Fault Candidate: {top_cand.symbol_name} in {top_cand.file_path}:{top_cand.line_start}")
        print(f"      Confidence: {top_cand.confidence}")
        print(f"      Hypothesis: {top_cand.root_cause_hypothesis[:120]}...")
        assert top_cand.file_path != ""

        # 4. Run Deterministic Critic Agent
        print("[4/4] Running DeterministicCriticAgent verification pass...")
        critic_report = critic_agent.verify(diag_result)
        print(f"      Critic Verdict: {'PASSED' if critic_report.is_valid else 'FAILED'}")
        print(f"      Grounding Score: {int(critic_report.grounding_score * 100)}%")
        print(f"      Verified Candidates: {len(critic_report.verified_candidates)}")
        assert critic_report.is_valid is True
        assert critic_report.grounding_score >= 0.5
        assert len(critic_report.verified_candidates) > 0

        print("\nAll Phase 4 Code Agents tests passed successfully!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_code_agents_pipeline()
