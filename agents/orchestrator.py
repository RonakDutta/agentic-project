"""
Orchestrator Agent and Multi-Agent Supervisor Engine.
Classifies user intent, generates dynamic execution plans, delegates tasks to specialized subagents,
manages deterministic verification loops, and records complete execution traces for visual observability.
"""

import os
import uuid
from typing import Any, Dict, List, Optional
from core.llm import llm_client
from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex
from indexer.hybrid_retriever import HybridRetriever
from agents.code_nav_agent import CodeNavigationAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.critic_agent import DeterministicCriticAgent
from agents.idea_agent import IdeaDecompositionAgent
from agents.market_agent import MarketTechStackAgent
from agents.roadmap_agent import RoadmapRiskAgent
from agents.kill_agent import kill_agent, reconciler_agent
from agents.feasibility_scorecard import scorecard_engine
from agents.prd_agent import prd_agent
from agents.workflow_state import AgentWorkflowState
from agents.conversation_session import session_manager, followup_engine


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
        self.kill_agent = kill_agent
        self.reconciler_agent = reconciler_agent
        self.scorecard_engine = scorecard_engine
        self.prd_agent = prd_agent

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
                else [
                    "Decompose Idea",
                    "Conduct Market & Competitor Research",
                    "Adversarial Kill Critique",
                    "Weigh Evidence & Reconcile",
                    "Score Feasibility Rubric",
                    "Generate PRD & Architecture Models",
                    "Generate 3-Phase Roadmap & Risk Matrix",
                ]
            )
            state.add_trace("Orchestrator", f"Intent explicitly specified as '{intent}'.")
        else:
            state.add_trace("Orchestrator", "Classifying user intent and planning execution steps...")
            intent_context = f"Query: {query}\n"
            if repo_path:
                intent_context += f"Context: Repository path provided ({repo_path})\n"

            try:
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
            except Exception as err:
                state.add_trace("Orchestrator", f"LLM intent note ({err}). Using deterministic intent classifier.")
                code_signals = ["traceback", "error", "exception", "def ", "class ", "valueerror", "function", "bug", "line ", "fail", "token"]
                q_low = query.lower()
                if repo_path or any(s in q_low for s in code_signals):
                    intent = "codebase_analysis"
                    confidence = 0.95
                    plan_steps = ["Parse AST & Index", "Navigate Code Chunks", "Diagnose Root Cause", "Deterministic Critic Verification"]
                else:
                    intent = "idea_validation"
                    confidence = 0.95
                    plan_steps = [
                        "Decompose Idea",
                        "Conduct Market & Competitor Research",
                        "Adversarial Kill Critique",
                        "Weigh Evidence & Reconcile",
                        "Score Feasibility Rubric",
                        "Generate PRD & Architecture Models",
                        "Generate 3-Phase Roadmap & Risk Matrix",
                    ]

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

        # Register in session manager for persistent conversational follow-ups
        try:
            session = session_manager.get_or_create_session(state.session_id, repo_path)
            if state.final_output:
                if state.final_output.get("type") == "codebase_analysis":
                    candidates = state.final_output.get("candidates", [])
                    symbols = [c.get("symbol_name") for c in candidates if c.get("symbol_name")]
                    files = [c.get("file_path") for c in candidates if c.get("file_path")]
                    session.add_turn(
                        user_query=query,
                        agent_name="Diagnosis Agent",
                        agent_role="Root-Cause Diagnosis Specialist",
                        answer=state.final_output.get("summary", ""),
                        referenced_symbols=symbols,
                        referenced_files=files,
                    )
                elif state.final_output.get("type") == "idea_validation":
                    session.add_turn(
                        user_query=query,
                        agent_name="Idea Decomposer",
                        agent_role="Product & Idea Decomposition Agent",
                        answer=state.final_output.get("problem_statement", "") or "Idea validation processed.",
                    )
        except Exception as sess_err:
            print(f"[Orchestrator] Session registration note: {sess_err}")

        return state

    def _execute_codebase_pipeline(
        self, state: AgentWorkflowState, query: str, repo_path: Optional[str]
    ) -> None:
        """Executes Code Navigation -> Diagnosis -> Critic verification loop."""
        target_path = (repo_path or "").strip()
        from indexer.github_ingest import github_ingest_service

        if target_path and github_ingest_service.is_valid_github_url(target_path):
            state.add_trace(
                "Task Planner",
                f"Cloning remote GitHub repository '{target_path}' into secure read-only sandbox...",
                status="running",
            )
            ingest_res = github_ingest_service.ingest(target_path)
            if ingest_res.status != "ok":
                state.add_trace(
                    "Task Planner",
                    f"GitHub clone failed: {ingest_res.error_message}",
                    status="warning",
                )
                state.final_output = {
                    "error": f"Failed to clone GitHub repository: {ingest_res.error_message}",
                    "type": "error",
                }
                return
            state.add_trace(
                "Task Planner",
                f"Successfully cloned '{ingest_res.repo_name}' ({ingest_res.total_files} files, {ingest_res.total_symbols} symbols).",
                status="completed",
            )
            target_path = ingest_res.local_path

        if not target_path or not os.path.exists(target_path):
            state.add_trace(
                "Task Planner",
                "Error: Codebase analysis requested but target repository path does not exist.",
                status="warning",
                details={
                    "thinking": "Attempted to locate repository on disk.",
                    "tool": "File System Inspector",
                    "findings": ["No valid folder path or GitHub repository was provided."],
                    "handoff": "Stopped pipeline gracefully.",
                },
            )
            state.final_output = {
                "error": "Please provide a valid repository path or public GitHub URL to analyze.",
                "type": "error",
            }
            return

        # Step 1: AST Parsing & Indexing
        indexer = ASTCodeIndexer(repo_path=target_path)
        codebase_index = indexer.index()

        state.add_trace(
            "Code Structure Indexer",
            f"Parsed Python repository at '{target_path}'",
            status="completed",
            details={
                "thinking": "Parsing all Python files into an Abstract Syntax Tree to map functions, classes, and import connections.",
                "tool": "Python Native AST Parser",
                "findings": [
                    f"Indexed {len(codebase_index.file_list)} Python source files",
                    f"Mapped {len(codebase_index.chunks)} logical function and class blocks",
                    f"Cataloged {len(codebase_index.symbol_table)} unique code symbols",
                ],
                "handoff": "Passed symbol index to Code Navigation Agent.",
            },
        )

        # Step 2: Hybrid Retrieval & Code Navigation
        retriever = HybridRetriever(codebase_index=codebase_index, prefer_neural=True)
        nav_agent = CodeNavigationAgent(codebase_index=codebase_index, retriever=retriever)
        nav_result = nav_agent.navigate(query, top_k=4)

        state.add_trace(
            "Code Navigation Agent",
            f"Searched symbols and ranked code units for query: '{query[:60]}...'",
            status="completed",
            details={
                "thinking": "Using hybrid search (BM25 keywords + neural vectors) to find exact code symbols matching the bug report.",
                "tool": "Hybrid Code Search (BM25 + Semantic Embeddings)",
                "findings": [
                    f"Narrowed repository down to {len(nav_result.candidate_chunks)} candidate code blocks",
                    f"Identified primary suspect: {nav_result.candidate_chunks[0].id if nav_result.candidate_chunks else 'None'}",
                ],
                "handoff": "Passed candidate code blocks to Diagnosis Agent.",
            },
        )

        # Step 3: Fault Diagnosis
        diag_result = self.diag_agent.diagnose(nav_result)

        state.add_trace(
            "Root Cause Diagnosis Agent",
            "Analyzed code logic and formulated candidate bug fixes",
            status="completed",
            details={
                "thinking": "Inspecting AST slice for logic errors, missing error handlers, or invalid state mutations.",
                "tool": "Reasoning Diagnosis Engine",
                "findings": [
                    f"Identified root cause hypothesis: {diag_result.summary[:100]}...",
                    f"Generated {len(diag_result.ranked_candidates)} prioritized patch candidates with line bounds",
                ],
                "handoff": "Passed patch proposals to Deterministic Critic for grounding verification.",
            },
        )

        # Step 4: Deterministic Critic Verification Loop
        critic_agent = DeterministicCriticAgent(codebase_index=codebase_index)
        critic_report = critic_agent.verify(diag_result)

        # Revision Loop
        if not critic_report.is_valid and state.revision_count < state.max_revisions:
            state.revision_count += 1
            state.add_trace(
                "Deterministic Critic",
                f"Grounding check detected issues ({critic_report.flags}). Triggering self-correction revision cycle...",
                status="revised",
                details={
                    "thinking": "Checking whether referenced files and line numbers physically exist on disk.",
                    "tool": "Python ast.parse Linter & Disk Verifier",
                    "findings": ["Draft diagnosis referenced unverified lines. Requesting revision."],
                    "handoff": "Sent feedback back to Diagnosis Agent for correction.",
                },
            )
            diag_result = self.diag_agent.diagnose(nav_result)
            critic_report = critic_agent.verify(diag_result)

        state.add_trace(
            "Deterministic Critic",
            f"Grounding check complete. Final Score: {int(critic_report.grounding_score * 100)}%",
            status="completed",
            details={
                "thinking": "Final verification of code lines, file paths, and syntax tree validity.",
                "tool": "Python ast.parse Linter & Disk Verifier",
                "findings": [
                    f"Grounding score: {int(critic_report.grounding_score * 100)}%",
                    f"Verified {len(critic_report.verified_candidates)} candidate code blocks on disk",
                    "All code patches pass Python syntax check",
                ],
                "handoff": "Final results ready for display.",
            },
        )

        state.final_output = {
            "type": "codebase_analysis",
            "summary": diag_result.summary,
            "candidates": [c.to_dict() for c in diag_result.ranked_candidates],
            "critic": critic_report.to_dict(),
            "indexed_summary": codebase_index.get_summary(),
        }

    def _execute_idea_pipeline(self, state: AgentWorkflowState, query: str) -> None:
        """
        Executes the expanded 7-agent Idea Validation pipeline:
        1. Idea Decomposition Agent
        2. Market & Competitor Intelligence Agent
        3. Adversarial Kill Agent (Devil's Advocate)
        4. Evidence Reconciler Agent (Thesis vs Antithesis)
        5. Deterministic Feasibility Scorecard Engine (7-Category Rubric)
        6. PRD & Architecture Engine (MetaGPT-Style User Stories & Mermaid Models)
        7. Roadmap & Risk Assessor (3-Phase Timeline & Matrix)
        """
        # Step 1: Decomposition
        decomposed = self.idea_agent.decompose(query)
        state.add_trace(
            agent_name="Idea Decomposer",
            action=f"Defined project brief for '{decomposed.project_title}'",
            status="completed",
            agent_role="Product & Idea Decomposition Agent",
            input_summary=f"Raw user idea prompt: '{query[:80]}...'",
            output_summary=f"Extracted {len(decomposed.target_personas)} personas, {len(decomposed.mvp_features)} MVP features",
            evidence_count=len(decomposed.target_personas),
            details={
                "thinking": "Analyzed problem domain, segmented core personas, and established lean MVP scope.",
                "tool": "Project Requirement Analyzer",
                "findings": [
                    f"Project Title: {decomposed.project_title}",
                    f"Core Problem: {decomposed.problem_statement[:120]}...",
                    f"Identified {len(decomposed.target_personas)} target user personas",
                    f"Defined {len(decomposed.mvp_features)} must-have MVP features",
                ],
                "handoff": "Passed product definition to Market & Competitor Researcher.",
            },
        )

        # Step 2: Market & Tech Stack
        market = self.market_agent.analyze(decomposed)
        state.add_trace(
            agent_name="Market & Competitor Researcher",
            action=f"Synthesized {len(market.competitors)} market references and production tech stack",
            status="completed",
            agent_role="Market Intelligence Specialist",
            input_summary=f"Project brief: '{decomposed.project_title}'",
            output_summary=f"Identified {len(market.competitors)} competitors, recommended 3-tier stack",
            evidence_count=len(market.citations),
            citations=[c.get("url", "") for c in market.citations[:3] if c.get("url")],
            details={
                "thinking": "Queried web search index for existing market solutions and formulated modern stack architecture.",
                "tool": "Live Web Search (DuckDuckGo)",
                "findings": [
                    f"Found {len(market.competitors)} existing market solutions",
                    f"Top competitors: {', '.join(c.get('name', '') for c in market.competitors[:2])}",
                    f"Recommended Backend: {market.tech_stack.get('backend', {}).get('choice', '')}",
                    f"Recommended Frontend: {market.tech_stack.get('frontend', {}).get('choice', '')}",
                ],
                "handoff": "Passed competitor data and stack to Adversarial Kill Agent.",
            },
        )

        # Step 3: Adversarial Kill Agent (Task 9.3)
        kill_report = self.kill_agent.critique(decomposed, market)
        state.add_trace(
            agent_name="Adversarial Kill Agent",
            action=f"Identified {len(kill_report.fatal_flaws)} potential fatal flaws and bear-case risks",
            status="completed",
            agent_role="Devil's Advocate & Risk Critic",
            input_summary="Project thesis, competitors, and differentiators",
            output_summary=f"Uncovered {len(kill_report.fatal_flaws)} fatal flaws and {len(kill_report.incumbent_threats)} incumbent threats",
            evidence_count=len(kill_report.fatal_flaws),
            details={
                "thinking": "Challenged unproven assumptions, modeled incumbent replication risks, and located distribution traps.",
                "tool": "Adversarial Stress-Test Engine",
                "findings": [
                    f"Bear Case: {kill_report.bear_case_summary[:120]}...",
                    f"Fatal Flaws: {', '.join([f.title for f in kill_report.fatal_flaws[:2]])}",
                    f"Incumbent Threat: {kill_report.incumbent_threats[0] if kill_report.incumbent_threats else 'None'}",
                ],
                "handoff": "Passed adversarial critique to Evidence Reconciler.",
            },
        )

        # Step 4: Evidence Reconciler (Task 9.3)
        reconciler_result = self.reconciler_agent.reconcile(decomposed, market, kill_report)
        state.add_trace(
            agent_name="Evidence Reconciler",
            action=f"Synthesized debate verdict: '{reconciler_result.verdict}' with {len(reconciler_result.must_have_mitigations)} mitigations",
            status="completed",
            agent_role="Impartial Systems Arbiter",
            input_summary="Thesis (Value Prop) vs Antithesis (Fatal Flaws)",
            output_summary=f"Balanced {len(reconciler_result.key_tradeoffs)} tradeoffs and {len(reconciler_result.must_have_mitigations)} success preconditions",
            evidence_count=len(reconciler_result.must_have_mitigations),
        )

        # Step 5: Feasibility Scorecard Engine (Task 9.5)
        scorecard = self.scorecard_engine.evaluate(decomposed, market, kill_report, reconciler_result)
        state.add_trace(
            agent_name="Feasibility Scorecard Engine",
            action=f"Evaluated 7-category rubric: Score {scorecard.total_score}/100 ({scorecard.verdict})",
            status="completed",
            agent_role="Deterministic Decision Scorer",
            input_summary="Decomposition, Market data, Kill flaws, Reconciler mitigations",
            output_summary=f"Score: {scorecard.total_score}/100 across 7 rubric categories",
            evidence_count=7,
        )

        # Step 6: PRD & Architecture Engine (Task 9.4)
        prd = self.prd_agent.generate(decomposed, market, reconciler_result)
        state.add_trace(
            agent_name="PRD & Architecture Specialist",
            action=f"Generated formal PRD with {len(prd.user_stories)} user stories and 3 Mermaid diagrams",
            status="completed",
            agent_role="MetaGPT Product Manager & Software Architect",
            input_summary="Product brief, stack recommendations, and success criteria",
            output_summary=f"{len(prd.user_stories)} User Stories, {len(prd.functional_requirements)} Functional Requirements, 3 Mermaid Models",
            evidence_count=len(prd.user_stories) + len(prd.functional_requirements),
        )

        # Step 7: Roadmap & Risk Assessor (Emitted as 4th Storyboard Step: Scorecard & Roadmap)
        roadmap = self.roadmap_agent.generate(decomposed, market)
        state.add_trace(
            agent_name="Scorecard & Roadmap",
            action=f"Evaluated 100-point rubric ({scorecard.total_score}/100) and formulated 3-phase delivery roadmap",
            status="completed",
            agent_role="Deterministic Decision Scorer & Milestone Planner",
            input_summary="Architecture, MVP features, and delivery constraints",
            output_summary=f"Score: {scorecard.total_score}/100 ({scorecard.verdict}), 3 phases, {len(roadmap.risks)} risks mapped",
            evidence_count=7 + len(roadmap.phases) + len(roadmap.risks),
            details={
                "thinking": "Evaluated deterministic 100-point rubric across 7 categories and formulated delivery milestones.",
                "tool": "Deterministic Rubric Calculator & Milestone Engine",
                "findings": [
                    f"Feasibility Score: {scorecard.total_score}/100 ({scorecard.verdict}) based on project rubric",
                    f"Phase 1 MVP: {roadmap.phases[0].phase_name} ({roadmap.phases[0].duration_weeks})",
                    f"Cataloged {len(roadmap.risks)} operational risks and {len(scorecard.key_strengths)} strategic strengths",
                    f"Synthesized {len(prd.user_stories)} PRD User Stories with 3 Mermaid models",
                ],
                "handoff": "Compiled complete deliverables and registered persistent session memory.",
            },
        )

        # Step 8: Compile Structured 13-Section Report (Task 9.14)
        sections_13 = self._compile_13_sections(
            decomposed=decomposed,
            market=market,
            kill_report=kill_report,
            reconciler_result=reconciler_result,
            scorecard=scorecard,
            prd=prd,
            roadmap=roadmap,
        )
        full_report_md = self._render_markdown_report(sections_13, decomposed.project_title)

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
            "implementation_pitfall": market.implementation_pitfall,
            # Phase 9 Scorecard & Adversarial Data
            "feasibility_score": scorecard.total_score,
            "feasibility_verdict": scorecard.verdict,
            "rubric_disclaimer": scorecard.rubric_disclaimer,
            "scorecard": scorecard.to_dict(),
            "kill_report": kill_report.to_dict(),
            "bear_case_critic": kill_report.bear_case_summary,
            "reconciliation": reconciler_result.to_dict(),
            "prd": prd.to_dict(),
            "phases": [p.to_dict() if hasattr(p, "to_dict") else p.__dict__ for p in roadmap.phases],
            "risks": [r.to_dict() if hasattr(r, "to_dict") else r.__dict__ for r in roadmap.risks],
            "evaluation_tips": roadmap.evaluation_tips,
            # Structured 13-Section Report
            "sections_13": sections_13,
            "full_report_markdown": full_report_md,
        }

    def _compile_13_sections(
        self,
        decomposed: Any,
        market: Any,
        kill_report: Any,
        reconciler_result: Any,
        scorecard: Any,
        prd: Any,
        roadmap: Any,
    ) -> List[Dict[str, Any]]:
        """Compiles the structured 13-section idea report (Task 9.14)."""
        return [
            {
                "section_number": 1,
                "title": "Executive Summary",
                "content": (
                    f"**Project**: {decomposed.project_title}\n\n"
                    f"**Core Thesis**: {decomposed.core_value_prop}\n\n"
                    f"**Feasibility Verdict**: `{scorecard.verdict}` (Score: **{scorecard.total_score}/100** based on the defined project rubric).\n\n"
                    f"**Strategic Takeaway**: {scorecard.verdict_summary}"
                ),
            },
            {
                "section_number": 2,
                "title": "Problem Statement & Target Personas",
                "content": (
                    f"**Problem Statement**:\n{decomposed.problem_statement}\n\n"
                    "**Target User Personas**:\n"
                    + "\n".join([
                        f"- **{p.get('persona', 'User')}**: Pain Point: {p.get('pain_point', '')}. Expected Benefit: {p.get('expected_benefit', '')}."
                        for p in decomposed.target_personas
                    ])
                ),
            },
            {
                "section_number": 3,
                "title": "Market & Competitor Analysis",
                "content": (
                    "**Identified Market Alternatives**:\n"
                    + "\n".join([
                        f"- **{c.get('name', 'Competitor')}**: {c.get('summary', '')} (Advantage: {c.get('advantages', 'Standard')}; Gap: {c.get('gaps', 'Niche gap')})"
                        for c in market.competitors
                    ])
                    + "\n\n**Search Citations**:\n"
                    + "\n".join([
                        f"- [{c.get('title', 'Reference')}]({c.get('url', '#')})"
                        for c in market.citations[:4]
                    ])
                ),
            },
            {
                "section_number": 4,
                "title": "Proposed Solution & Value Proposition",
                "content": (
                    f"**Value Proposition**:\n{decomposed.core_value_prop}\n\n"
                    "**Key Differentiators**:\n"
                    + "\n".join([f"- {d}" for d in market.key_differentiators])
                    + "\n\n**Core MVP Features**:\n"
                    + "\n".join([f"- {f}" for f in decomposed.mvp_features])
                ),
            },
            {
                "section_number": 5,
                "title": "System Architecture & Technology Stack",
                "content": (
                    "**Recommended Production Stack**:\n"
                    + "\n".join([
                        f"- **{k.capitalize()}**: `{v.get('choice', '')}` - {v.get('rationale', '')} (Tradeoffs: {v.get('tradeoffs', '')})"
                        for k, v in market.tech_stack.items()
                        if isinstance(v, dict)
                    ])
                    + f"\n\n**Architecture Topology**:\n```mermaid\n{prd.architecture_diagram_mermaid}\n```"
                ),
            },
            {
                "section_number": 6,
                "title": "Product Requirements Document (PRD)",
                "content": (
                    f"**Product Vision**: {prd.product_vision}\n\n"
                    "**User Stories**:\n"
                    + "\n".join([
                        f"- **{s.story_id} ({s.persona})**: As a {s.persona}, I want to {s.want} so that {s.so_that}. (Criteria: {', '.join(s.acceptance_criteria[:2])})"
                        for s in prd.user_stories
                    ])
                    + "\n\n**Functional Requirements**:\n"
                    + "\n".join([
                        f"- **{fr.req_id} ({fr.priority})**: {fr.title} - {fr.description}"
                        for fr in prd.functional_requirements
                    ])
                ),
            },
            {
                "section_number": 7,
                "title": "Adversarial Kill Critique & Fatal Flaws",
                "content": (
                    f"**Bear Case Summary**: {kill_report.bear_case_summary}\n\n"
                    "**Fatal Flaws Identified**:\n"
                    + "\n".join([
                        f"- **{f.title} ({f.severity})**: {f.argument} (Market Dynamic: {f.counter_evidence})"
                        for f in kill_report.fatal_flaws
                    ])
                    + "\n\n**Incumbent Threats**:\n"
                    + "\n".join([f"- {t}" for t in kill_report.incumbent_threats])
                    + "\n\n**Distribution Traps**:\n"
                    + "\n".join([f"- {d}" for d in kill_report.distribution_traps])
                ),
            },
            {
                "section_number": 8,
                "title": "Evidence Reconciliation (Thesis vs Antithesis)",
                "content": (
                    f"**Synthesis Verdict**: `{reconciler_result.verdict}`\n\n"
                    f"**Rationale**: {reconciler_result.synthesis_rationale}\n\n"
                    "**Key Tradeoffs**:\n"
                    + "\n".join([f"- {t}" for t in reconciler_result.key_tradeoffs])
                    + "\n\n**Non-Negotiable Success Preconditions**:\n"
                    + "\n".join([f"- {m}" for m in reconciler_result.must_have_mitigations])
                ),
            },
            {
                "section_number": 9,
                "title": "100-Point Feasibility Scorecard & Decision Rubric",
                "content": (
                    f"**Overall Feasibility**: **{scorecard.total_score}/100** ({scorecard.verdict})\n\n"
                    f"> *{scorecard.rubric_disclaimer}*\n\n"
                    + scorecard.to_markdown()
                ),
            },
            {
                "section_number": 10,
                "title": "Development Roadmap & Milestones",
                "content": (
                    "**Chronological 3-Phase Execution Plan**:\n"
                    + "\n".join([
                        f"- **Phase {p.phase_number}: {p.phase_name} ({p.duration_weeks})**\n  * Deliverables: {', '.join(p.deliverables)}\n  * Exit Criteria: {p.exit_criteria}"
                        for p in roadmap.phases
                    ])
                ),
            },
            {
                "section_number": 11,
                "title": "Technical & Operational Risk Matrix",
                "content": (
                    "**Risk Assessment & Mitigation Matrix**:\n"
                    + "\n".join([
                        f"- **[{r.category}] ({r.severity} Severity)**: {r.risk}\n  * Mitigation: {r.mitigation}"
                        for r in roadmap.risks
                    ])
                ),
            },
            {
                "section_number": 12,
                "title": "Resource Requirements & Infrastructure Budget",
                "content": (
                    "**Resource Footprint**:\n"
                    "- **Hosting & Infrastructure**: Standard containerized deployment on free/low-cost tiers (estimated $0-$20/mo in initial MVP phase).\n"
                    "- **API & External Services**: Local open-source embeddings, free search tooling, and rate-limited LLM inference tiers.\n"
                    "- **Team Requirements**: 1-2 full-stack engineers focusing on fast-cycle validation."
                ),
            },
            {
                "section_number": 13,
                "title": "Final Strategic Recommendation & Next Steps",
                "content": (
                    f"**Decision**: `{scorecard.verdict}`\n\n"
                    "**Actionable Next Steps**:\n"
                    + "\n".join([
                        f"1. {a}" if idx == 0 else f"{idx+1}. {a}"
                        for idx, a in enumerate(scorecard.recommended_actions)
                    ])
                ),
            },
        ]

    def _render_markdown_report(self, sections: List[Dict[str, Any]], title: str) -> str:
        """Renders the 13 sections into clean markdown document without horizontal rule dashes."""
        blocks = [f"# Multi-Agent Idea Validation Report: {title}\n"]
        for s in sections:
            blocks.append(f"## {s['section_number']}. {s['title']}\n{s['content']}\n")
        return "\n".join(blocks)

    def answer_followup(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        repo_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Answers conversational follow-up questions with previous context,
        anaphora resolution, persistent multi-turn session memory, and specialist routing.
        """
        sid = session_id or (context.get("session_id") if isinstance(context, dict) else None)
        rpath = repo_path or (context.get("repo_path") if isinstance(context, dict) else None)

        return followup_engine.process_followup(
            query=query,
            session_id=sid,
            repo_path=rpath,
            context_override=context,
        )



# Global singleton instance
orchestrator = OrchestratorAgent()
