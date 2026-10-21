"""
Orchestrator Agent and Multi-Agent Supervisor Engine.
Classifies user intent, generates dynamic execution plans, delegates tasks to specialized subagents,
manages deterministic verification loops, and records complete execution traces for visual observability.
"""

import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from core.llm import llm_client, AGENT_MAX_TOKENS
from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex
from indexer.hybrid_retriever import HybridRetriever
from indexer import index_cache
from agents.code_nav_agent import CodeNavigationAgent
from agents.diagnosis_agent import DiagnosisAgent
from agents.critic_agent import DeterministicCriticAgent
from agents.idea_agent import IdeaDecompositionAgent
from agents.market_agent import MarketTechStackAgent
from agents.roadmap_agent import RoadmapRiskAgent
from agents.kill_agent import kill_agent, reconciler_agent
from agents.feasibility_scorecard import scorecard_engine
from agents.prd_agent import prd_agent
from agents.prior_art_agent import prior_art_agent
from core.config import settings
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

logger = logging.getLogger(__name__)

CODE_PLAN = ("Parse AST & Index", "Navigate Code Chunks", "Diagnose Root Cause", "Deterministic Critic Verification")
IDEA_PLAN = (
    "Decompose Idea",
    "Conduct Market & Competitor Research",
    "Adversarial Kill Critique",
    "Weigh Evidence & Reconcile",
    "Score Feasibility Rubric",
    "Generate PRD & Architecture Models",
    "Generate 3-Phase Roadmap & Risk Matrix",
)

# Deterministic keyword signals for zero-cost intent classification.
_CODE_INTENT_SIGNALS = re.compile(
    r"traceback|exception|valueerror|typeerror|keyerror|attributeerror|indexerror|zerodivisionerror|"
    r"stack trace|\bdef \b|\bclass \b|\.py\b|line \d+|bug|debug|call graph|callers|callees|blast radius|"
    r"cyclomatic|\bast\b|refactor this function|code review|where is .*(defined|implemented)",
    re.IGNORECASE,
)
_IDEA_INTENT_SIGNALS = re.compile(
    r"startup|business idea|project idea|validate (my|this|an) idea|feasibility|market research|"
    r"competitor|roadmap|\bprd\b|product requirements|monetiz|go-to-market|pitch|mvp for|new (app|product|platform|service)",
    re.IGNORECASE,
)


def _classify_intent_deterministically(query: str, repo_path: Optional[str]) -> Optional[str]:
    """
    Zero-cost keyword classifier. Returns a confident intent or None when ambiguous,
    so the LLM classifier is only spent on genuinely ambiguous queries.
    """
    code_hits = bool(_CODE_INTENT_SIGNALS.search(query))
    idea_hits = bool(_IDEA_INTENT_SIGNALS.search(query))
    if repo_path and not idea_hits:
        return "codebase_analysis"
    if code_hits and not idea_hits:
        return "codebase_analysis"
    if idea_hits and not code_hits:
        return "idea_validation"
    return None


# What kind of code question was asked. Bug reports get a fault diagnosis;
# impact and "where/how" questions get the same pipeline plus call-graph facts.
_IMPACT_Q = re.compile(r"blast radius|impact|what (?:breaks|would break|could break)|if i (?:change|modify|remove|rename)|who calls|callers? of|depends on", re.IGNORECASE)
_EXPLAIN_Q = re.compile(r"^\s*(?:where|how|which|what does|explain|trace|show)\b|\bflow\b", re.IGNORECASE)
_BUG_Q = re.compile(r"error|exception|traceback|crash|bug|fail|wrong|broken|twice|duplicate|leak|hang|slow|raises?|none ?type|keyerror|valueerror|typeerror", re.IGNORECASE)


def classify_code_question(query: str) -> str:
    """'impact', 'explain' or 'bug' (deterministic, no LLM)."""
    if _IMPACT_Q.search(query or ""):
        return "impact"
    if _BUG_Q.search(query or ""):
        return "bug"
    if _EXPLAIN_Q.search(query or ""):
        return "explain"
    return "bug"


def _phase_weeks(duration: Any) -> int:
    """
    Length of one roadmap phase in weeks.
    "Weeks 5 - 8" is a calendar range (4 weeks); "3-4 weeks" is an estimate (take 4).
    """
    text = str(duration or "").strip().lower()
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return 0
    if text.startswith("week") and len(nums) >= 2:
        return max(nums) - min(nums) + 1
    return max(nums)


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
        self.prior_art_agent = prior_art_agent

    def process(
        self,
        query: str,
        repo_path: Optional[str] = None,
        force_intent: Optional[str] = None,
        on_trace=None,
    ) -> AgentWorkflowState:
        """
        Executes the multi-agent workflow from start to finish.
        The same four steps are the nodes of the LangGraph graph (agents/graph.py).
        `on_trace` receives every trace step as it happens (live progress stream).
        """
        state = self.new_state(query, repo_path, on_trace=on_trace)
        self.classify(state, force_intent)
        self.execute_track(state)
        self.finalize(state)
        return state

    def new_state(self, query: str, repo_path: Optional[str] = None, on_trace=None) -> AgentWorkflowState:
        state = AgentWorkflowState(
            session_id=str(uuid.uuid4())[:8],
            user_query=query,
            repo_path=repo_path,
            listener=on_trace,
        )
        state.add_trace("Orchestrator", f"Session initialized. Received query: '{query[:80]}...'")
        return state

    def classify(self, state: AgentWorkflowState, force_intent: Optional[str] = None) -> None:
        """Graph node 1: intent classification and plan."""
        # 1. Intent Classification & Task Decomposition
        if force_intent in ("codebase_analysis", "idea_validation"):
            intent = force_intent
            confidence = 1.0
            plan_steps = (
                list(CODE_PLAN)
                if intent == "codebase_analysis"
                else list(IDEA_PLAN)
            )
            state.add_trace("Orchestrator", f"Intent explicitly specified as '{intent}'.")
        else:
            state.add_trace("Orchestrator", "Classifying user intent and planning execution steps...")
            deterministic_intent = _classify_intent_deterministically(state.user_query, state.repo_path)

            if deterministic_intent:
                # Zero-cost path: skip the LLM entirely for confident classifications.
                intent = deterministic_intent
                confidence = 0.92
                plan_steps = (
                    list(CODE_PLAN)
                    if intent == "codebase_analysis"
                    else list(IDEA_PLAN)
                )
            else:
                try:
                    intent_context = f"Query: {state.user_query}\n"
                    if state.repo_path:
                        intent_context += f"Context: Repository path provided ({state.repo_path})\n"
                    intent_json = self.llm.generate_json(
                        messages=[
                            {"role": "system", "content": ORCHESTRATOR_INTENT_PROMPT},
                            {"role": "user", "content": intent_context},
                        ],
                        temperature=0.1,
                        max_tokens=AGENT_MAX_TOKENS["intent"],
                    )
                    intent = intent_json.get("intent")
                    if intent not in ("codebase_analysis", "idea_validation"):
                        intent = "codebase_analysis" if state.repo_path else "idea_validation"
                    try:
                        confidence = max(0.0, min(1.0, float(intent_json.get("confidence", 0.9))))
                    except (TypeError, ValueError):
                        confidence = 0.9
                    plan_steps = intent_json.get("plan_steps")
                    if not isinstance(plan_steps, list) or not plan_steps:
                        plan_steps = list(CODE_PLAN if intent == "codebase_analysis" else IDEA_PLAN)
                    plan_steps = [str(step) for step in plan_steps]
                except Exception as err:
                    state.add_trace("Orchestrator", f"LLM intent note ({err}). Using deterministic intent classifier.")
                    fallback_intent = _classify_intent_deterministically(state.user_query, state.repo_path)
                    if fallback_intent == "codebase_analysis" or state.repo_path:
                        intent = "codebase_analysis"
                        confidence = 0.95
                        plan_steps = list(CODE_PLAN)
                    else:
                        intent = "idea_validation"
                        confidence = 0.95
                        plan_steps = list(IDEA_PLAN)

        state.intent = intent
        state.intent_confidence = confidence
        state.plan_steps = plan_steps
        state.add_trace(
            "Orchestrator",
            f"Classified intent: '{intent}' (confidence: {int(confidence * 100)}%). Plan created: {len(plan_steps)} steps.",
            details={"plan": plan_steps},
        )


    def execute_track(self, state: AgentWorkflowState) -> None:
        """Graph node 2: runs the code or idea pipeline chosen by classify()."""
        intent = state.intent
        # 2. Route Execution to Specialized Pipeline
        if intent == "codebase_analysis":
            self._execute_codebase_pipeline(state, state.user_query, state.repo_path)
        else:
            self._execute_idea_pipeline(state, state.user_query)


    def finalize(self, state: AgentWorkflowState) -> None:
        """Graph node 3: closes the trace and registers the session for follow-ups."""
        state.finalize()
        state.add_trace(
            "Orchestrator",
            f"Workflow successfully completed in {state.total_latency_ms}ms.",
            status="completed",
        )

        # Register in session manager for persistent conversational follow-ups
        try:
            # state.repo_path is the local clone for GitHub URLs, so follow-ups can open it.
            session = session_manager.get_or_create_session(state.session_id, state.repo_path)
            if state.final_output:
                session.active_entities["final_output"] = state.final_output
                session.active_entities["project_title"] = state.final_output.get("project_title", "")
                if state.final_output.get("type") == "codebase_analysis":
                    candidates = state.final_output.get("candidates", [])
                    symbols = [c.get("symbol_name") for c in candidates if c.get("symbol_name")]
                    files = [c.get("file_path") for c in candidates if c.get("file_path")]
                    session.add_turn(
                        user_query=state.user_query,
                        agent_name="Diagnosis Agent",
                        agent_role="Root-Cause Diagnosis Specialist",
                        answer=state.final_output.get("summary", ""),
                        referenced_symbols=symbols,
                        referenced_files=files,
                    )
                elif state.final_output.get("type") == "idea_validation":
                    session.add_turn(
                        user_query=state.user_query,
                        agent_name="Idea Decomposer",
                        agent_role="Product & Idea Decomposition Agent",
                        answer=state.final_output.get("problem_statement", "") or "Idea validation processed.",
                    )
        except Exception as sess_err:
            logger.warning(f"[Orchestrator] Session registration note: {sess_err}")


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

        # Step 1: AST Parsing & Indexing (cached per repo until a .py file changes)
        codebase_index = index_cache.get_index(target_path)
        state.repo_path = target_path

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
        retriever = index_cache.get_retriever(codebase_index, prefer_neural=True)
        nav_agent = CodeNavigationAgent(codebase_index=codebase_index, retriever=retriever)
        nav_result = nav_agent.navigate(query, top_k=4)
        vector_backend = getattr(retriever.vector_index, "backend", "unknown")

        # Call-graph facts for the primary suspect (deterministic, zero LLM quota):
        # blast radius of a change and the static call flow through it.
        question_mode = classify_code_question(query)
        structure = self._structural_analysis(codebase_index, nav_result)
        impact = structure.get("impact") or {}
        impact_line = (
            f"Blast radius of '{impact.get('target_symbol')}': {impact.get('direct_callers_count', 0)} direct and "
            f"{impact.get('indirect_callers_count', 0)} indirect callers, {impact.get('risk_level', '?')} risk"
            if impact else "Call graph: no resolvable target symbol"
        )

        state.add_trace(
            "Code Navigation Agent",
            f"Searched symbols and ranked code units for query: '{query[:60]}...'",
            status="completed",
            details={
                "thinking": "Using hybrid search (BM25 keywords + vectors) to find exact code symbols matching the bug report.",
                "tool": f"Hybrid Code Search (BM25 + {'MiniLM embeddings' if vector_backend == 'sentence-transformers' else 'TF-IDF vectors'})",
                "findings": [
                    f"Narrowed repository down to {len(nav_result.candidate_chunks)} candidate code blocks",
                    f"Explicit symbols in query: {', '.join(nav_result.identified_symbols) or 'none'}",
                    f"Identified primary suspect: {nav_result.candidate_chunks[0].id if nav_result.candidate_chunks else 'None'}",
                    impact_line,
                ],
                "handoff": "Passed candidate code blocks to Diagnosis Agent.",
            },
        )

        # Static analysis + git history for each candidate go into the diagnosis prompt.
        static_notes = self._static_notes(codebase_index, nav_result.candidate_chunks)

        # Step 3: Fault Diagnosis
        diag_result = self._run_step(
            state, "Root Cause Diagnosis Agent",
            lambda: self.diag_agent.diagnose(
                nav_result,
                feedback={"static_notes": static_notes, "question_mode": question_mode, "call_graph": structure.get("prompt_facts", "")},
            ),
        )

        state.add_trace(
            "Root Cause Diagnosis Agent",
            "Analyzed code logic and formulated candidate bug fixes",
            status="completed" if diag_result.generation_source == "llm" else "warning",
            details={
                "thinking": "Inspecting AST slice for logic errors, missing error handlers, or invalid state mutations.",
                "tool": "Groq LLM with line-numbered code + static analysis" if diag_result.generation_source == "llm" else "Retrieval + static analysis only (LLM unavailable)",
                "findings": [
                    f"Identified root cause hypothesis: {diag_result.summary[:100]}...",
                    f"Generated {len(diag_result.ranked_candidates)} prioritized candidates with line bounds",
                ],
                "handoff": "Passed patch proposals to Deterministic Critic for grounding verification.",
                "source": diag_result.generation_source,
            },
        )

        # Step 4: Deterministic Critic Verification Loop
        critic_agent = DeterministicCriticAgent(codebase_index=codebase_index)
        critic_report = critic_agent.verify(diag_result, retrieved_chunks=nav_result.candidate_chunks)
        first_score = critic_report.grounding_score

        # Revision Loop: the critic's flags go back into the prompt, so the retry
        # is a genuinely different request (not a cache hit on the first answer).
        broken_fix = critic_report.fixes_checked > critic_report.fixes_compiling
        needs_revision = (not critic_report.is_valid or broken_fix) and diag_result.generation_source == "llm"
        if needs_revision and state.revision_count < state.max_revisions:
            state.revision_count += 1
            state.add_trace(
                "Deterministic Critic",
                f"Grounding check found {len(critic_report.flags)} issue(s). Sending them back for one revision...",
                status="revised",
                details={
                    "thinking": "Checking whether referenced files, symbols, lines and quoted code match the repository.",
                    "tool": "Python ast.parse + disk verifier",
                    "findings": critic_report.flags[:4],
                    "handoff": "Sent flags and repair hints back to Diagnosis Agent.",
                },
            )
            revised = self.diag_agent.diagnose(
                nav_result,
                feedback={
                    "static_notes": static_notes,
                    "question_mode": question_mode,
                    "call_graph": structure.get("prompt_facts", ""),
                    "flags": critic_report.flags,
                    "repair_hints": critic_report.repair_hints,
                },
            )
            revised_report = critic_agent.verify(revised, retrieved_chunks=nav_result.candidate_chunks)
            # Keep whichever answer is better grounded.
            if revised_report.grounding_score >= critic_report.grounding_score:
                diag_result, critic_report = revised, revised_report

        fix_line = (
            f"{critic_report.fixes_compiling}/{critic_report.fixes_checked} recommended fixes compile as Python"
            if critic_report.fixes_checked else "No code fixes to compile-check"
        )
        state.add_trace(
            "Deterministic Critic",
            f"Grounding check complete. Final Score: {int(critic_report.grounding_score * 100)}%",
            status="completed" if critic_report.is_valid else "warning",
            details={
                "thinking": "Final verification of file paths, symbols, line ranges, quoted code and fix syntax.",
                "tool": "Python ast.parse + disk verifier",
                "findings": [
                    f"Grounding score: {int(critic_report.grounding_score * 100)}%"
                    + (f" (was {int(first_score * 100)}% before revision)" if state.revision_count else ""),
                    f"Verified {len(critic_report.verified_candidates)}/{critic_report.total_checked} candidate locations on disk",
                    f"{critic_report.code_quote_matches}/{critic_report.total_checked} quoted code blocks match the file",
                    fix_line,
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
            "local_repo_path": target_path,
            "retrieval_backend": vector_backend,
            "static_analysis": static_notes,
            "question_mode": question_mode,
            # Call-graph facts computed from the AST (no LLM): blast radius and call flow.
            "impact": structure.get("impact"),
            "flow": structure.get("flow"),
            # What retrieval found, shown when the diagnosis cites no location.
            "retrieved_locations": [
                {"file_path": c.file_path, "symbol_name": c.name, "line_start": c.start_line, "line_end": c.end_line}
                for c in nav_result.candidate_chunks
            ],
            "provenance": {
                "diagnosis": diag_result.generation_source, "critic": "deterministic",
                "impact": "deterministic", "flow": "deterministic",
            },
            "used_fallback": diag_result.generation_source == "fallback",
        }

    @staticmethod
    def _structural_analysis(codebase_index: CodebaseIndex, nav_result: Any) -> Dict[str, Any]:
        """Blast radius + call flow for the primary suspect symbol, from the AST call graph."""
        from agents.change_impact_agent import ChangeImpactAgent
        from agents.flow_trace_agent import FlowTraceAgent

        target = None
        for sym in nav_result.identified_symbols or []:
            if codebase_index.lookup_symbol(sym.split(".")[-1]):
                target = sym.split(".")[-1]
                break
        if target is None and nav_result.candidate_chunks:
            top = nav_result.candidate_chunks[0]
            target = top.name.split(".")[-1]
        if not target:
            return {}
        out: Dict[str, Any] = {}
        try:
            impact = ChangeImpactAgent(codebase_index=codebase_index).analyze_impact(target_symbol=target)
            out["impact"] = impact.to_dict()
        except Exception as err:
            logger.debug(f"[Orchestrator] impact analysis skipped: {err}")
        try:
            flow = FlowTraceAgent(codebase_index=codebase_index).trace_flow(query=nav_result.query, starting_symbol=target)
            out["flow"] = flow.to_dict()
        except Exception as err:
            logger.debug(f"[Orchestrator] flow trace skipped: {err}")
        impact = out.get("impact") or {}
        callers = [f"{c['symbol_name']} ({c['file_path']}:{c['line']})" for c in impact.get("direct_callers", [])[:6]]
        out["prompt_facts"] = (
            f"Call graph for {target}: risk {impact.get('risk_level', '?')}, "
            f"direct callers: {', '.join(callers) or 'none found'}; "
            f"entry points affected: {', '.join(impact.get('affected_entrypoints', [])[:4]) or 'none'}; "
            f"tests affected: {', '.join(impact.get('affected_tests', [])[:4]) or 'none'}."
        ) if impact else ""
        return out

    @staticmethod
    def _static_notes(codebase_index: CodebaseIndex, chunks: List[Any]) -> Dict[str, str]:
        """Complexity metrics and last-commit info per candidate chunk (no LLM)."""
        import textwrap
        from tools.static_analyzer import static_analyzer
        from tools import git_tools
        from tools.lint_metrics import radon_complexity

        notes: Dict[str, str] = {}
        is_repo = git_tools.is_repo(codebase_index.repo_path)
        for chunk in chunks:
            try:
                metrics = static_analyzer.analyze_code_snippet(textwrap.dedent(chunk.code or ""), chunk.name)
                parts = [
                    f"complexity {metrics.cyclomatic_complexity}, {metrics.lines_of_code} lines, grade {metrics.maintainability_grade}"
                ] + metrics.findings[:2]
                radon = radon_complexity(textwrap.dedent(chunk.code or ""), chunk.name)
                if radon.get("status") == "ok" and radon.get("blocks"):
                    top = max(radon["blocks"], key=lambda b: b["complexity"])
                    parts.append(f"radon rank {top['rank']} ({top['name']}: {top['complexity']})")
                if is_repo:
                    blame = git_tools.blame_file(codebase_index.repo_path, chunk.file_path, chunk.start_line)
                    if blame.get("status") == "ok":
                        parts.append(f"last changed in {blame.get('commit')} on {str(blame.get('date'))[:10]}")
                notes[chunk.id] = "; ".join(parts)
            except Exception as err:  # static notes are optional evidence
                logger.debug(f"[Orchestrator] static notes skipped for {chunk.id}: {err}")
        return notes

    def _run_step(self, state: AgentWorkflowState, step_name: str, fn):
        """
        Runs one agent step. Agents already fall back on LLM errors; this guard
        covers everything else (a bad field in a model reply, a bug), so one
        step can never fail the whole run. On a crash the step is re-run with
        the LLM switched off, which makes it use its own built-in fallback.
        """
        try:
            return fn()
        except Exception as err:
            logger.exception(f"[Orchestrator] {step_name} crashed; re-running on its built-in fallback.")
            state.add_trace(
                step_name,
                f"Step error ({type(err).__name__}: {err}). Re-running with built-in fallback.",
                status="warning",
            )
            with self.llm.force_offline():
                return fn()

    @staticmethod
    def _source_status(obj: Any) -> str:
        return "warning" if getattr(obj, "generation_source", "llm") == "fallback" else "completed"

    @staticmethod
    def _source_note(obj: Any) -> Dict[str, str]:
        source = getattr(obj, "generation_source", "llm")
        note = {"source": source}
        if source == "fallback":
            note["fallback_reason"] = getattr(obj, "fallback_reason", "") or "LLM output unavailable"
        return note

    def _execute_idea_pipeline(self, state: AgentWorkflowState, query: str) -> None:
        """
        Executes the 7-agent Idea Validation pipeline:
        1. Idea Decomposition Agent
        2. Market & Competitor Intelligence Agent
        3. Adversarial Kill Agent (Devil's Advocate)
        4. Evidence Reconciler Agent (Thesis vs Antithesis)
        5. Deterministic Feasibility Scorecard Engine (7-Category Rubric)
        6. PRD & Architecture Engine (MetaGPT-Style User Stories & Mermaid Models)
        7. Roadmap & Risk Assessor (3-Phase Timeline & Matrix)

        The roadmap only needs steps 1-2, so it runs on a worker thread while
        steps 3-6 run; the LLM client spreads the two streams over different
        models' rate-limit windows.
        """
        # Step 1: Decomposition
        decomposed = self._run_step(state, "Idea Decomposer", lambda: self.idea_agent.decompose(query))
        state.add_trace(
            agent_name="Idea Decomposer",
            action=f"Defined project brief for '{decomposed.project_title}'",
            status=self._source_status(decomposed),
            agent_role="Product & Idea Decomposition Agent",
            input_summary=f"Raw user idea prompt: '{query[:80]}...'",
            output_summary=f"Extracted {len(decomposed.target_personas)} personas, {len(decomposed.mvp_features)} MVP features",
            evidence_count=len(decomposed.target_personas),
            details={
                "thinking": "Analyzed problem domain, segmented core personas, and established lean MVP scope.",
                "tool": "Groq LLM (structured JSON)" if decomposed.generation_source == "llm" else "Built-in fallback brief",
                "findings": [
                    f"Project Title: {decomposed.project_title}",
                    f"Core Problem: {decomposed.problem_statement[:120]}...",
                    f"Identified {len(decomposed.target_personas)} target user personas",
                    f"Defined {len(decomposed.mvp_features)} must-have MVP features",
                ],
                "handoff": "Passed product definition to Market & Competitor Researcher.",
                **self._source_note(decomposed),
            },
        )

        # Prior-art research only needs the brief: it searches arXiv, Semantic Scholar
        # and OpenAlex on its own thread while the market and debate steps run.
        prior_art_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prior_art")
        prior_art_future = (
            prior_art_executor.submit(
                self._run_step, state, "Prior-Art Researcher",
                lambda: self.prior_art_agent.research(decomposed),
            )
            if settings.prior_art_enabled else None
        )

        # Step 2: Market & Tech Stack
        market = self._run_step(state, "Market & Competitor Researcher", lambda: self.market_agent.analyze(decomposed))
        live_urls = [c.get("url", "") for c in market.citations if c.get("is_live") and c.get("url")]
        state.add_trace(
            agent_name="Market & Competitor Researcher",
            action=f"Synthesized {len(market.competitors)} market references and production tech stack",
            status=self._source_status(market),
            agent_role="Market Intelligence Specialist",
            input_summary=f"Project brief: '{decomposed.project_title}'",
            output_summary=(
                f"Identified {len(market.competitors)} competitors from {market.live_citation_count} live search results"
            ),
            evidence_count=market.live_citation_count,
            citations=live_urls[:3],
            details={
                "thinking": "Searched the web for existing solutions and formulated a stack architecture.",
                "tool": f"Web search: {market.search_backend}",
                "findings": [
                    f"Live search results: {market.live_citation_count}",
                    f"Found {len(market.competitors)} existing market solutions",
                    f"Top competitors: {', '.join(c.get('name', '') for c in market.competitors[:2]) or 'None identified'}",
                    f"Recommended Backend: {market.tech_stack.get('backend', {}).get('choice', '')}",
                    f"Recommended Frontend: {market.tech_stack.get('frontend', {}).get('choice', '')}",
                ],
                "handoff": "Passed competitor data and stack to Adversarial Kill Agent.",
                **self._source_note(market),
            },
        )

        # Step 7 starts now on a worker thread: it only needs the brief and the stack.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roadmap")
        roadmap_future = executor.submit(
            self._run_step, state, "Roadmap & Risk Assessor",
            lambda: self.roadmap_agent.generate(decomposed, market),
        )

        try:
            # Step 3: Adversarial Kill Agent (Task 9.3)
            kill_report = self._run_step(state, "Adversarial Kill Agent", lambda: self.kill_agent.critique(decomposed, market))
            state.add_trace(
                agent_name="Adversarial Kill Agent",
                action=f"Identified {len(kill_report.fatal_flaws)} potential fatal flaws and bear-case risks",
                status=self._source_status(kill_report),
                agent_role="Devil's Advocate & Risk Critic",
                input_summary="Project thesis, competitors, and differentiators",
                output_summary=f"Uncovered {len(kill_report.fatal_flaws)} fatal flaws and {len(kill_report.incumbent_threats)} incumbent threats",
                evidence_count=len(kill_report.fatal_flaws),
                details={
                    "thinking": "Challenged unproven assumptions, modeled incumbent replication risks, and located distribution traps.",
                    "tool": "Groq LLM (adversarial persona)" if kill_report.generation_source == "llm" else "Built-in fallback critique",
                    "findings": [
                        f"Bear Case: {kill_report.bear_case_summary[:120]}...",
                        f"Fatal Flaws: {', '.join([f.title for f in kill_report.fatal_flaws[:2]])}",
                        f"Incumbent Threat: {kill_report.incumbent_threats[0] if kill_report.incumbent_threats else 'None'}",
                    ],
                    "handoff": "Passed adversarial critique to Evidence Reconciler.",
                    **self._source_note(kill_report),
                },
            )

            # Step 4: Evidence Reconciler (Task 9.3)
            reconciler_result = self._run_step(
                state, "Evidence Reconciler",
                lambda: self.reconciler_agent.reconcile(decomposed, market, kill_report),
            )
            state.add_trace(
                agent_name="Evidence Reconciler",
                action=f"Synthesized debate verdict: '{reconciler_result.verdict}' with {len(reconciler_result.must_have_mitigations)} mitigations",
                status=self._source_status(reconciler_result),
                agent_role="Impartial Systems Arbiter",
                input_summary="Thesis (Value Prop) vs Antithesis (Fatal Flaws)",
                output_summary=f"Balanced {len(reconciler_result.key_tradeoffs)} tradeoffs and {len(reconciler_result.must_have_mitigations)} success preconditions",
                evidence_count=len(reconciler_result.must_have_mitigations),
                details=self._source_note(reconciler_result),
            )

            # Research prior art (started after step 1) joins here, before the scorecard uses it.
            prior_art = self._collect_prior_art(state, prior_art_future)

            # Step 5: Feasibility Scorecard Engine (Task 9.5) - deterministic, no LLM.
            scorecard = self.scorecard_engine.evaluate(
                decomposed, market, kill_report, reconciler_result, prior_art=prior_art
            )
            state.add_trace(
                agent_name="Feasibility Scorecard Engine",
                action=f"Evaluated 7-category rubric: Score {scorecard.total_score}/100 ({scorecard.verdict})",
                status="completed",
                agent_role="Deterministic Decision Scorer",
                input_summary="Decomposition, Market data, Kill flaws, Reconciler mitigations",
                output_summary=(
                    f"Score: {scorecard.total_score}/100 across 7 rubric categories, "
                    f"evidence confidence {scorecard.evidence_confidence}"
                ),
                evidence_count=7,
                details={
                    # Kept out of "findings" so the current 4-step storyboard UI is unchanged;
                    # the roadmap step below carries the score into the storyboard.
                    "tool": "Deterministic rubric (no LLM)",
                    "rubric": [
                        f"{c.category_name}: {c.score}/{c.max_score}" for c in scorecard.categories
                    ],
                    "notes": scorecard.verdict_notes + scorecard.confidence_notes,
                },
            )

            # Step 6: PRD & Architecture Engine (Task 9.4)
            prd = self._run_step(
                state, "PRD & Architecture Specialist",
                lambda: self.prd_agent.generate(decomposed, market, reconciler_result),
            )
            state.add_trace(
                agent_name="PRD & Architecture Specialist",
                action=f"Generated formal PRD with {len(prd.user_stories)} user stories and 3 Mermaid diagrams",
                status=self._source_status(prd),
                agent_role="MetaGPT Product Manager & Software Architect",
                input_summary="Product brief, stack recommendations, and success criteria",
                output_summary=f"{len(prd.user_stories)} User Stories, {len(prd.functional_requirements)} Functional Requirements, 3 Mermaid Models",
                evidence_count=len(prd.user_stories) + len(prd.functional_requirements),
                details=self._source_note(prd),
            )

            # Step 7: Roadmap & Risk Assessor (ran in parallel since step 2)
            roadmap = roadmap_future.result()
        finally:
            executor.shutdown(wait=True)
            prior_art_executor.shutdown(wait=True)

        first_phase = roadmap.phases[0] if roadmap.phases else None
        state.add_trace(
            agent_name="Roadmap & Risk Assessor",
            action=f"Formulated {len(roadmap.phases)}-phase delivery roadmap and {len(roadmap.risks)}-item risk matrix",
            status=self._source_status(roadmap),
            agent_role="Milestone Planner & Risk Assessor",
            input_summary="Architecture, MVP features, and delivery constraints",
            output_summary=f"{len(roadmap.phases)} phases, {len(roadmap.risks)} risks mapped",
            evidence_count=len(roadmap.phases) + len(roadmap.risks),
            details={
                "thinking": "Formulated delivery milestones and a risk matrix (ran in parallel with the debate steps).",
                "tool": "Groq LLM (structured JSON)" if roadmap.generation_source == "llm" else "Built-in fallback roadmap",
                "findings": [
                    f"Phase 1 MVP: {first_phase.phase_name} ({first_phase.duration_weeks})" if first_phase else "No phases produced",
                    f"Cataloged {len(roadmap.risks)} operational risks",
                    f"Feasibility Score: {scorecard.total_score}/100 ({scorecard.verdict}) based on project rubric",
                ],
                "handoff": "Compiled complete deliverables and registered persistent session memory.",
                **self._source_note(roadmap),
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
        if prior_art is not None:
            sections_13.append({
                "section_number": 14,
                "title": "Research Prior Art & Novelty (Related Work)",
                "content": prior_art.to_markdown(),
            })
        full_report_md = self._render_markdown_report(sections_13, decomposed.project_title)

        provenance = {
            "idea": decomposed.generation_source,
            "market": market.generation_source,
            "kill_report": kill_report.generation_source,
            "reconciliation": reconciler_result.generation_source,
            "scorecard": "deterministic",
            "prd": prd.generation_source,
            "roadmap": roadmap.generation_source,
        }
        if prior_art is not None:
            provenance["prior_art"] = prior_art.generation_source

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
            "search_backend": market.search_backend,
            "live_citation_count": market.live_citation_count,
            "implementation_pitfall": market.implementation_pitfall,
            # Phase 9 Scorecard & Adversarial Data
            "feasibility_score": scorecard.total_score,
            "feasibility_verdict": scorecard.verdict,
            "rubric_disclaimer": scorecard.rubric_disclaimer,
            "evidence_confidence": scorecard.evidence_confidence,
            "scorecard": scorecard.to_dict(),
            "kill_report": kill_report.to_dict(),
            "bear_case_critic": kill_report.bear_case_summary,
            "reconciliation": reconciler_result.to_dict(),
            "prd": prd.to_dict(),
            "phases": [p.to_dict() if hasattr(p, "to_dict") else p.__dict__ for p in roadmap.phases],
            "risks": [r.to_dict() if hasattr(r, "to_dict") else r.__dict__ for r in roadmap.risks],
            "evaluation_tips": roadmap.evaluation_tips,
            # Which sections the LLM wrote and which used built-in fallbacks.
            "provenance": provenance,
            "used_fallback": any(v == "fallback" for v in provenance.values()),
            # Research papers retrieved for this idea, novelty index, comparison, references.
            "prior_art": prior_art.to_dict() if prior_art is not None else None,
            # Structured report: 13 sections, plus section 14 (prior art) when it ran.
            "sections_13": sections_13,
            "full_report_markdown": full_report_md,
        }

    def _collect_prior_art(self, state: AgentWorkflowState, future) -> Any:
        """Waits for the prior-art thread and records its trace step."""
        if future is None:
            return None
        try:
            report = future.result(timeout=90)
        except Exception as err:
            state.add_trace("Prior-Art Researcher", f"Prior-art research skipped ({err}).", status="warning")
            return None
        verification = report.verification
        state.add_trace(
            agent_name="Prior-Art Researcher",
            action=(
                f"Compared the idea with {len(report.papers)} research papers "
                f"(novelty index {report.novelty_index if report.novelty_index is not None else 'n/a'}/100)"
            ),
            status="completed" if report.generation_source == "llm" else "warning",
            agent_role="Research Literature Analyst",
            input_summary=f"Search queries: {'; '.join(report.queries)}",
            output_summary=f"{len(report.papers)} papers from {report.search_backend}; {report.novelty_band}",
            evidence_count=len(report.papers),
            citations=[p.url for p in report.papers[:3] if p.url],
            details={
                # The legacy UI shows this as the 5th storyboard card (IDEA_AGENTS node_3).
                "thinking": (
                    "Searched arXiv, Semantic Scholar and OpenAlex for papers on this idea, ranked them by "
                    "embedding similarity, and compared the closest ones using only their abstracts."
                ),
                "findings": (
                    [f"{p.ref_id}: {p.title} ({p.year or 'n.d.'}), similarity {p.similarity:.2f}" for p in report.papers[:3]]
                    + [
                        f"Novelty index: {report.novelty_index}/100 ({report.novelty_band})"
                        if report.novelty_index is not None else "Novelty index: not computed (no papers retrieved)",
                        f"Critic: {verification.get('comparisons_kept', 0)}/{verification.get('comparisons_returned', 0)} "
                        f"comparisons cite a retrieved paper, {verification.get('citations_removed', 0)} bad citations removed",
                    ]
                ),
                "handoff": "Passed the novelty evidence to the Feasibility Scorecard (Defensibility category).",
                "tool": f"Paper search: {report.search_backend}; similarity: {report.similarity_backend}",
                "papers": [f"{p.ref_id} ({p.similarity:.2f}) {p.title}" for p in report.papers[:5]],
                "notes": report.notes + [
                    f"{verification.get('comparisons_kept', 0)}/{verification.get('comparisons_returned', 0)} "
                    "LLM comparisons cite a retrieved paper",
                    f"Average abstract support: {verification.get('avg_abstract_support', 0)}",
                ],
                **self._source_note(report),
            },
        )
        return report

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
                "content": self._resource_section(decomposed, market, scorecard, roadmap),
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

    @staticmethod
    def _resource_section(decomposed: Any, market: Any, scorecard: Any, roadmap: Any) -> str:
        """Section 12, built from this idea's stack, features, roadmap and rubric findings."""
        stack_lines = [
            f"- **{k.replace('_', ' ').capitalize()}**: `{v.get('choice', '')}`"
            for k, v in (market.tech_stack or {}).items()
            if isinstance(v, dict) and v.get("choice")
        ]
        resource_cat = next(
            (c for c in scorecard.categories if c.category_name == "Resource Requirements"), None
        )
        cost_lines = [f"- {g}" for g in (resource_cat.gaps if resource_cat else [])] or [
            "- Software-only build on open-source components; hosting fits free or low-cost tiers during the MVP."
        ]
        features = len(decomposed.mvp_features)
        team = "1 developer" if features <= 2 else "2 developers" if features <= 4 else "3 developers"
        weeks = [w for w in (_phase_weeks(p.duration_weeks) for p in roadmap.phases) if w]
        timeline = f"about {sum(weeks)} weeks across {len(roadmap.phases)} phases" if weeks else f"{len(roadmap.phases)} phases"
        return (
            "**Technology Footprint**:\n" + ("\n".join(stack_lines) or "- Stack not specified") + "\n\n"
            "**Cost & Effort Drivers** (from the rubric's Resource Requirements check):\n" + "\n".join(cost_lines) + "\n\n"
            f"**Team & Timeline**: {team} for {features} MVP features, {timeline}.\n\n"
            f"**Resource Score**: {resource_cat.score if resource_cat else '?'}/10 on the project rubric."
        )

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
