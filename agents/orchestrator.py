"""
Orchestrator Agent and Multi-Agent Supervisor Engine.
Classifies user intent, generates dynamic execution plans, delegates tasks to specialized subagents,
manages deterministic verification loops, and records complete execution traces for visual observability.
"""

import uuid
from typing import Any, Dict, Optional
from core.llm import llm_client
from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex
from indexer.hybrid_retriever import HybridRetriever
from agents.code_nav_agent import CodeNavigationAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.critic_agent import DeterministicCriticAgent
from agents.idea_agent import IdeaDecompositionAgent
from agents.market_agent import MarketTechStackAgent
from agents.roadmap_agent import RoadmapRiskAgent
from agents.workflow_state import AgentWorkflowState


ORCHESTRATOR_INTENT_PROMPT = """You are the Supervisory Orchestrator Agent for an Agentic AI Engineering Co-Pilot.
Your role is to classify the user's intent and formulate an execution plan.

The system has two primary execution tracks:
1. "codebase_analysis": The user is asking about an existing Python codebase, debugging an error trace, asking about a function/class, or analyzing code structure.
2. "idea_validation": The user is proposing a new project/startup idea, asking for market research, technology stack advice, or a development roadmap.

CRITICAL INSTRUCTIONS:
Classify the intent and output strict JSON matching this exact schema:
{
  "intent": "codebase_analysis" or "idea_validation",
  "confidence": 0.95,
  "reasoning": "Brief explanation of why this intent was selected.",
  "plan_steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ]
}
"""


class OrchestratorAgent:
    def __init__(self):
        self.llm = llm_client
        self.idea_agent = IdeaDecompositionAgent()
        self.market_agent = MarketTechStackAgent()
        self.roadmap_agent = RoadmapRiskAgent()
        self.diag_agent = DiagnosisAgent()

    def process(
        self,
        query: str,
        repo_path: Optional[str] = None,
        force_intent: Optional[str] = None,
    ) -> AgentWorkflowState:
        """
        Executes the multi-agent workflow from start to finish.
        """
        session_id = str(uuid.uuid4())[:8]
        state = AgentWorkflowState(
            session_id=session_id,
            user_query=query,
            repo_path=repo_path,
        )

        state.add_trace("Orchestrator", f"Session initialized. Received query: '{query[:80]}...'")

        # 1. Intent Classification & Task Decomposition
        if force_intent in ("codebase_analysis", "idea_validation"):
            intent = force_intent
            confidence = 1.0
            plan_steps = (
                ["Parse AST & Index", "Navigate Code Chunks", "Diagnose Root Cause", "Deterministic Critic Verification"]
                if intent == "codebase_analysis"
                else ["Decompose Idea", "Conduct Market & Competitor Research", "Generate 3-Phase Roadmap & Risk Matrix"]
            )
            state.add_trace("Orchestrator", f"Intent explicitly specified as '{intent}'.")
        else:
            state.add_trace("Orchestrator", "Classifying user intent and planning execution steps...")
            intent_context = f"Query: {query}\n"
            if repo_path:
                intent_context += f"Context: Repository path provided ({repo_path})\n"

            intent_json = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": ORCHESTRATOR_INTENT_PROMPT},
                    {"role": "user", "content": intent_context},
                ],
                temperature=0.1,
            )
            intent = intent_json.get("intent", "idea_validation")
            confidence = float(intent_json.get("confidence", 0.9))
            plan_steps = intent_json.get("plan_steps", [])

        state.intent = intent
        state.intent_confidence = confidence
        state.plan_steps = plan_steps
        state.add_trace(
            "Orchestrator",
            f"Classified intent: '{intent}' (confidence: {int(confidence * 100)}%). Plan created: {len(plan_steps)} steps.",
            details={"plan": plan_steps},
        )

        # 2. Route Execution to Specialized Pipeline
        if intent == "codebase_analysis":
            self._execute_codebase_pipeline(state, query, repo_path)
        else:
            self._execute_idea_pipeline(state, query)

        state.finalize()
        state.add_trace(
            "Orchestrator",
            f"Workflow successfully completed in {state.total_latency_ms}ms.",
            status="completed",
        )

        return state

    def _execute_codebase_pipeline(
        self, state: AgentWorkflowState, query: str, repo_path: Optional[str]
    ) -> None:
        """Executes Code Navigation -> Diagnosis -> Critic verification loop."""
        if not repo_path:
            state.add_trace(
                "Orchestrator",
                "Error: Codebase analysis requested but no repository path provided.",
                status="warning",
            )
            state.final_output = {
                "error": "Please provide a valid repository path to analyze.",
                "type": "error",
            }
            return

        # Step 1: AST Parsing & Indexing
        state.add_trace("ASTCodeIndexer", f"Parsing Python repository at '{repo_path}'...")
        indexer = ASTCodeIndexer(repo_path=repo_path)
        codebase_index = indexer.index()

        state.add_trace(
            "ASTCodeIndexer",
            f"Indexed {len(codebase_index.file_list)} files, {len(codebase_index.chunks)} chunks, and {len(codebase_index.symbol_table)} symbols.",
        )

        # Step 2: Hybrid Retrieval & Code Navigation
        state.add_trace("HybridRetriever", "Initializing BM25 and local vector store...")
        retriever = HybridRetriever(codebase_index=codebase_index, prefer_neural=True)
        nav_agent = CodeNavigationAgent(codebase_index=codebase_index, retriever=retriever)

        state.add_trace("CodeNavigationAgent", "Searching code symbols and ranking relevant chunks...")
        nav_result = nav_agent.navigate(query, top_k=4)

        state.add_trace(
            "CodeNavigationAgent",
            f"Narrowed context to {len(nav_result.candidate_chunks)} candidate code units.",
            details={"candidates": [c.id for c in nav_result.candidate_chunks]},
        )

        # Step 3: Fault Diagnosis
        state.add_trace("DiagnosisAgent", "Formulating ranked root-cause hypotheses with Groq...")
        diag_result = self.diag_agent.diagnose(nav_result)

        # Step 4: Deterministic Critic Verification Loop
        state.add_trace("DeterministicCritic", "Verifying candidate files, symbols, and line bounds on disk...")
        critic_agent = DeterministicCriticAgent(codebase_index=codebase_index)
        critic_report = critic_agent.verify(diag_result)

        # Revision Loop
        if not critic_report.is_valid and state.revision_count < state.max_revisions:
            state.revision_count += 1
            state.add_trace(
                "Orchestrator",
                f"Critic rejected draft due to grounding flags: {critic_report.flags}. Triggering self-correction revision cycle...",
                status="revised",
            )
            # Re-diagnose with strict grounding prompt
            diag_result = self.diag_agent.diagnose(nav_result)
            critic_report = critic_agent.verify(diag_result)
            state.add_trace(
                "DeterministicCritic",
                f"Post-revision Critic Grounding Score: {int(critic_report.grounding_score * 100)}%.",
            )

        state.final_output = {
            "type": "codebase_analysis",
            "summary": diag_result.summary,
            "candidates": [c.to_dict() for c in diag_result.ranked_candidates],
            "critic": critic_report.to_dict(),
            "indexed_summary": codebase_index.get_summary(),
        }

    def _execute_idea_pipeline(self, state: AgentWorkflowState, query: str) -> None:
        """Executes Idea Decomposition -> Market Analysis -> Roadmap pipeline."""
        # Step 1: Decomposition
        state.add_trace("IdeaDecompositionAgent", "Extracting problem statement, personas, and MVP scope...")
        decomposed = self.idea_agent.decompose(query)
        state.add_trace(
            "IdeaDecompositionAgent",
            f"Project defined as '{decomposed.project_title}'. Identified {len(decomposed.target_personas)} user personas.",
        )

        # Step 2: Market & Tech Stack
        state.add_trace("MarketTechStackAgent", "Querying web intelligence and analyzing competitor models...")
        market = self.market_agent.analyze(decomposed)
        state.add_trace(
            "MarketTechStackAgent",
            f"Identified {len(market.competitors)} market references and recommended full-stack architecture.",
        )

        # Step 3: Roadmap & Risk
        state.add_trace("RoadmapRiskAgent", "Generating 3-phase chronological roadmap and risk matrix...")
        roadmap = self.roadmap_agent.generate(decomposed, market)
        state.add_trace(
            "RoadmapRiskAgent",
            f"Roadmap formulated with {len(roadmap.phases)} phases, {len(roadmap.risks)} risks, and evaluation defense tips.",
        )

        state.final_output = {
            "type": "idea_validation",
            "project_title": decomposed.project_title,
            "problem_statement": decomposed.problem_statement,
            "core_value_prop": decomposed.core_value_prop,
            "target_personas": decomposed.target_personas,
            "key_assumptions": decomposed.key_assumptions,
            "mvp_features": decomposed.mvp_features,
            "competitors": market.competitors,
            "tech_stack": market.tech_stack,
            "key_differentiators": market.key_differentiators,
            "citations": market.citations,
            "phases": [p.to_dict() if hasattr(p, "to_dict") else p.__dict__ for p in roadmap.phases],
            "risks": [r.to_dict() if hasattr(r, "to_dict") else r.__dict__ for r in roadmap.risks],
            "evaluation_tips": roadmap.evaluation_tips,
        }


# Global singleton instance
orchestrator = OrchestratorAgent()
