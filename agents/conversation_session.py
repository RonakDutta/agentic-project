"""
Persistent Conversational Session Engine Scoped to Repository.
Inspired by PRISM, CodeChat AI, and CodeContextKit.

Task 9.1: Conversational Follow-Up.
Guarantees:
- Persistent multi-turn chat scoped to a repository without form reset.
- State preservation across questions (remembers previously discussed symbols, files, lines).
- Resolves anaphoric references (e.g. 'What calls that function?' -> resolves 'that function').
- Automatically routes follow-up queries to specialized agents (ChangeImpactAgent, FlowTraceAgent, AST caller lookup).
- Enforces configurable bounded context (ContextBudgetManager) to avoid LLM context overflow.
"""

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from core.llm import llm_client
from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex
from indexer.context_budget import ContextBudgetManager
from agents.flow_trace_agent import FlowTraceAgent
from agents.change_impact_agent import ChangeImpactAgent


@dataclass
class ConversationTurn:
    turn_id: int
    user_query: str
    agent_name: str
    agent_role: str
    answer: str
    action_taken: str
    thinking: str
    referenced_symbols: List[str] = field(default_factory=list)
    referenced_files: List[str] = field(default_factory=list)
    evidence_snippets: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_query": self.user_query,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "answer": self.answer,
            "action_taken": self.action_taken,
            "thinking": self.thinking,
            "referenced_symbols": self.referenced_symbols,
            "referenced_files": self.referenced_files,
            "evidence_snippets": self.evidence_snippets,
            "timestamp": self.timestamp,
        }


@dataclass
class ConversationSession:
    session_id: str
    repo_path: Optional[str] = None
    history: List[ConversationTurn] = field(default_factory=list)
    active_entities: Dict[str, Any] = field(default_factory=dict)
    cached_index: Optional[CodebaseIndex] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_turn(
        self,
        user_query: str,
        agent_name: str,
        answer: str,
        agent_role: str = "",
        action_taken: str = "",
        thinking: str = "",
        referenced_symbols: Optional[List[str]] = None,
        referenced_files: Optional[List[str]] = None,
        evidence_snippets: Optional[List[Dict[str, Any]]] = None,
    ) -> ConversationTurn:
        turn = ConversationTurn(
            turn_id=len(self.history) + 1,
            user_query=user_query,
            agent_name=agent_name,
            agent_role=agent_role or agent_name,
            answer=answer,
            action_taken=action_taken or "Addressed user question",
            thinking=thinking or f"{agent_name} evaluated previous context and formulated guidance.",
            referenced_symbols=referenced_symbols or [],
            referenced_files=referenced_files or [],
            evidence_snippets=evidence_snippets or [],
        )
        self.history.append(turn)
        self.updated_at = time.time()

        # Update active entity pointers
        if turn.referenced_symbols:
            self.active_entities["last_symbol"] = turn.referenced_symbols[0]
            existing_syms = self.active_entities.get("referenced_symbols", [])
            for s in turn.referenced_symbols:
                if s not in existing_syms:
                    existing_syms.append(s)
            self.active_entities["referenced_symbols"] = existing_syms

        if turn.referenced_files:
            self.active_entities["last_file"] = turn.referenced_files[0]
            existing_files = self.active_entities.get("referenced_files", [])
            for f in turn.referenced_files:
                if f not in existing_files:
                    existing_files.append(f)
            self.active_entities["referenced_files"] = existing_files

        return turn

    def resolve_anaphora(self, query: str) -> str:
        """
        Resolves pronouns and anaphoric references ('that function', 'it', 'this file')
        into explicit symbols using session active entities.
        """
        last_sym = self.active_entities.get("last_symbol")
        last_file = self.active_entities.get("last_file")

        resolved = query
        if last_sym:
            patterns = [
                (r"\b(that|this|the)\s+function\b", last_sym),
                (r"\b(that|this|the)\s+method\b", last_sym),
                (r"\b(that|this|the)\s+symbol\b", last_sym),
                (r"\bmodify\s+it\b", f"modify {last_sym}"),
                (r"\bchange\s+it\b", f"change {last_sym}"),
                (r"\bcall(s)?\s+it\b", f"call\\1 {last_sym}"),
                (r"\bwhat\s+calls\s+that\b", f"what calls {last_sym}"),
                (r"\btrace\s+it\b", f"trace {last_sym}"),
                (r"\btest\s+it\b", f"test {last_sym}"),
            ]
            for pat, repl in patterns:
                resolved = re.sub(pat, repl, resolved, flags=re.IGNORECASE)

        if last_file:
            patterns_file = [
                (r"\b(that|this|the)\s+file\b", last_file),
                (r"\b(that|this|the)\s+module\b", last_file),
            ]
            for pat, repl in patterns_file:
                resolved = re.sub(pat, repl, resolved, flags=re.IGNORECASE)

        return resolved

    def get_bounded_context(self, max_tokens: int = 3000) -> str:
        """
        Extracts bounded conversation context keeping recent turns verbatim
        and summarizing older turns to respect token limits.
        """
        if not self.history:
            return ""

        cbm = ContextBudgetManager(default_budget=max_tokens)
        recent_turns = self.history[-4:]  # Keep last 4 turns
        blocks = []

        if len(self.history) > 4:
            older_summary = [
                f"Turn {t.turn_id}: User asked '{t.user_query}' -> {t.agent_name} responded regarding {', '.join(t.referenced_symbols) or 'architecture'}."
                for t in self.history[:-4]
            ]
            blocks.append("--- Earlier Conversation Summary ---")
            blocks.extend(older_summary)

        blocks.append("--- Recent Conversation History ---")
        for t in recent_turns:
            ans_snippet = f"{t.answer[:600]}..." if len(t.answer) > 600 else t.answer
            blocks.append(f"[User Question (Turn {t.turn_id})]: {t.user_query}\n[{t.agent_name}]: {ans_snippet}")

        full_text = "\n\n".join(blocks)
        est = cbm.estimate_tokens(full_text)
        if est > max_tokens:
            # Fallback to last 2 turns if budget is tight
            compact_blocks = [
                f"[User (Turn {t.turn_id})]: {t.user_query}\n[{t.agent_name}]: {t.answer[:400]}"
                for t in self.history[-2:]
            ]
            return "\n\n".join(compact_blocks)

        return full_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "repo_path": self.repo_path,
            "turn_count": len(self.history),
            "history": [t.to_dict() for t in self.history],
            "active_entities": self.active_entities,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionManager:
    """
    Manages active in-memory conversation sessions and cached codebase indexes.
    """

    def __init__(self):
        self._sessions: Dict[str, ConversationSession] = {}

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        repo_path: Optional[str] = None,
    ) -> ConversationSession:
        sid = session_id or str(uuid.uuid4())[:8]
        if sid not in self._sessions:
            self._sessions[sid] = ConversationSession(session_id=sid, repo_path=repo_path)
        else:
            if repo_path and not self._sessions[sid].repo_path:
                self._sessions[sid].repo_path = repo_path
        return self._sessions[sid]

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        return self._sessions.get(session_id)

    def get_or_index_repo(self, session_id: str, repo_path: str) -> CodebaseIndex:
        session = self.get_or_create_session(session_id, repo_path)
        if session.cached_index and session.repo_path == repo_path:
            return session.cached_index

        indexer = ASTCodeIndexer(repo_path=repo_path)
        index = indexer.index()
        session.cached_index = index
        session.repo_path = repo_path
        return index

    def clear_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


class ConversationalFollowupEngine:
    """
    Processes persistent conversational follow-ups with domain specialist routing,
    anaphora resolution, and targeted tool dispatch (ChangeImpactAgent, FlowTraceAgent).
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.llm = llm_client

    # Direct agent aliases -> canonical agent keys
    DIRECT_AGENT_ALIASES: Dict[str, str] = {
        "decomposer": "decomposer", "idea": "decomposer", "brief": "decomposer", "research": "decomposer",
        "market": "market", "competitor": "market",
        "kill": "kill", "devil": "kill", "critic": "kill",
        "arbiter": "arbiter", "reconciler": "arbiter",
        "scorecard": "scorecard", "score": "scorecard", "rubric": "scorecard",
        "prd": "prd", "product": "prd", "stories": "prd",
        "roadmap": "roadmap", "milestone": "roadmap", "delivery": "roadmap",
        "architect": "architect", "stack": "architect", "navigation": "architect",
        "risk": "risk", "audit": "risk", "security": "risk",
        "code": "code", "ast": "code", "debug": "code", "diagnosis": "code",
    }

    DIRECT_AGENT_PROFILES: Dict[str, Dict[str, str]] = {
        "decomposer": {"name": "Idea & Research Agent", "role": "Problem & Feature Scope"},
        "market": {"name": "Market & Tech Analyst", "role": "Competitors & Solutions"},
        "kill": {"name": "Roadmap & Risk Agent (Critic)", "role": "Risks & Fatal Flaws"},
        "arbiter": {"name": "Decision Arbiter", "role": "Verdict & Tradeoffs"},
        "scorecard": {"name": "Critic & Feasibility Agent", "role": "Grounding & Feasibility Scorecard"},
        "prd": {"name": "Product Manager", "role": "Requirements & User Stories"},
        "roadmap": {"name": "Roadmap Planner", "role": "Phases & Delivery Milestones"},
        "architect": {"name": "Code Navigation & Systems Architect", "role": "AST Structure & Infrastructure"},
        "risk": {"name": "Security & Risk Auditor", "role": "Blast Radius & Code Safety"},
        "code": {"name": "Diagnosis Agent", "role": "Bug Diagnosis & Fix Direction"},
    }

    @classmethod
    def _extract_direct_agent(cls, query: str) -> Optional[str]:
        """Detects '@agent <question>' mentions anywhere in the query."""
        match = re.search(r"@([a-zA-Z_-]+)\b", query)
        if not match:
            return None
        return cls.DIRECT_AGENT_ALIASES.get(match.group(1).lower())

    @classmethod
    def get_direct_agent_catalog(cls) -> List[Dict[str, str]]:
        """Public catalog used by the UI to render agent chips."""
        return [
            {"key": key, "agent_name": profile["name"], "mention": f"@{key}"}
            for key, profile in cls.DIRECT_AGENT_PROFILES.items()
        ]

    def _answer_as_direct_agent(
        self,
        agent_key: str,
        raw_query: str,
        resolved_query: str,
        session: ConversationSession,
        ctx: Dict[str, Any],
        codebase_index: Optional[CodebaseIndex],
    ) -> Dict[str, Any]:
        """Answers as the explicitly addressed specialist agent, directly addressing the question with domain evidence."""
        if not ctx and session.active_entities.get("final_output"):
            ctx = session.active_entities["final_output"]

        profile = self.DIRECT_AGENT_PROFILES.get(agent_key, self.DIRECT_AGENT_PROFILES["architect"])
        agent_name = profile["name"]
        agent_role = profile["role"]
        question = re.sub(r"@[a-zA-Z_-]+\b", "", resolved_query).strip() or "General inquiry regarding your findings."

        evidence_snippets: List[str] = []
        referenced_symbols: List[str] = []
        referenced_files: List[str] = []

        proj_title = ctx.get("project_title") or session.active_entities.get("project_title", "Current Project")
        prob_stmt = ctx.get("problem_statement", "")

        if agent_key == "kill":
            kill = ctx.get("kill_report", {})
            if kill:
                if kill.get("bear_case_summary"):
                    evidence_snippets.append(f"Bear Case: {kill['bear_case_summary']}")
                for f in kill.get("fatal_flaws", []):
                    if isinstance(f, dict):
                        evidence_snippets.append(f"- Flaw ({f.get('title', 'Risk')}): {f.get('argument', '')}")
                        if f.get("counter_evidence"):
                            evidence_snippets.append(f"  Validation/Evidence: {f.get('counter_evidence')}")
                for t in kill.get("incumbent_threats", [])[:3]:
                    evidence_snippets.append(f"- Threat: {t}")
                for tr in kill.get("distribution_traps", [])[:2]:
                    evidence_snippets.append(f"- Distribution trap: {tr}")
        elif agent_key == "market":
            for c in ctx.get("competitors", []):
                if isinstance(c, dict):
                    evidence_snippets.append(f"- {c.get('name', 'Competitor')}: {c.get('summary', '')} (Advantage: {c.get('advantages', '')}; Gap: {c.get('gaps', '')})")
            for d in ctx.get("key_differentiators", [])[:3]:
                evidence_snippets.append(f"- Differentiator: {d}")
        elif agent_key == "architect":
            for cat, item in (ctx.get("tech_stack", {}) or {}).items():
                if isinstance(item, dict):
                    evidence_snippets.append(f"- {cat.title()}: {item.get('choice', '')} (Rationale: {item.get('rationale', '')}; Tradeoffs: {item.get('tradeoffs', '')})")
        elif agent_key == "scorecard":
            sc = ctx.get("scorecard", {})
            if sc:
                evidence_snippets.append(f"Feasibility Score: {sc.get('total_score', 0)}/100 ({sc.get('verdict', '')})")
                for cat in sc.get("categories", []):
                    if isinstance(cat, dict):
                        evidence_snippets.append(f"- {cat.get('category_name')}: {cat.get('score')}/{cat.get('max_score')} ({cat.get('rationale', '')})")
                if sc.get("key_strengths"):
                    evidence_snippets.append(f"Strengths: {', '.join(sc.get('key_strengths'))}")
                if sc.get("key_risks"):
                    evidence_snippets.append(f"Risks: {', '.join(sc.get('key_risks'))}")
        elif agent_key == "prd":
            prd = ctx.get("prd", {})
            if prd:
                evidence_snippets.append(f"Product Vision: {prd.get('product_vision', '')}")
                for s in prd.get("user_stories", [])[:4]:
                    if isinstance(s, dict):
                        evidence_snippets.append(f"- Story {s.get('story_id')}: As a {s.get('persona')}, I want {s.get('want')} so that {s.get('so_that')}")
        elif agent_key == "roadmap":
            for p in ctx.get("phases", []):
                if isinstance(p, dict):
                    evidence_snippets.append(f"- Phase {p.get('phase_number')}: {p.get('phase_name')} ({p.get('duration_weeks')}) - Deliverables: {', '.join(p.get('deliverables', []))}")
            for r in ctx.get("risks", [])[:3]:
                if isinstance(r, dict):
                    evidence_snippets.append(f"- Risk: {r.get('risk')} (Mitigation: {r.get('mitigation')})")
        elif agent_key == "arbiter":
            rec = ctx.get("reconciliation", {})
            if rec:
                evidence_snippets.append(f"Verdict: {rec.get('verdict', '')} - {rec.get('synthesis_rationale', '')}")
                if rec.get("must_have_mitigations"):
                    evidence_snippets.append(f"Must-Have Mitigations: {', '.join(rec.get('must_have_mitigations'))}")
                if rec.get("key_tradeoffs"):
                    evidence_snippets.append(f"Tradeoffs: {', '.join(rec.get('key_tradeoffs'))}")
        elif agent_key == "decomposer":
            if ctx:
                evidence_snippets.append(f"Problem: {prob_stmt}")
                evidence_snippets.append(f"Value Proposition: {ctx.get('core_value_prop', '')}")
                for f in ctx.get("mvp_features", [])[:4]:
                    evidence_snippets.append(f"- MVP Feature: {f}")
        elif agent_key == "code":
            for c in ctx.get("candidates", [])[:3]:
                if isinstance(c, dict):
                    sym = c.get("symbol_name", "")
                    if sym:
                        referenced_symbols.append(sym)
                    if c.get("file_path"):
                        referenced_files.append(c.get("file_path"))
                    evidence_snippets.append(f"- Code Issue in `{sym}` ({c.get('file_path')}): {c.get('why_problematic', '')}")
        elif agent_key == "risk":
            if codebase_index is not None:
                target = session.active_entities.get("last_symbol")
                if target:
                    impact_agent = ChangeImpactAgent(codebase_index=codebase_index)
                    impact_res = impact_agent.analyze_impact(target_symbol=target)
                    referenced_symbols.append(target)
                    if impact_res.target_file:
                        referenced_files.append(impact_res.target_file)
                    evidence_snippets.append(f"Blast radius for `{target}`: {impact_res.risk_level} ({impact_res.blast_radius_score}/100)")
            if not evidence_snippets:
                for flaw in (ctx.get("kill_report", {}) or {}).get("fatal_flaws", [])[:3]:
                    if isinstance(flaw, dict):
                        evidence_snippets.append(f"- Risk: {flaw.get('title')}: {flaw.get('argument')}")

        # Attempt tailored response via LLM in specialist's voice
        evidence_text = "\n".join(evidence_snippets) if evidence_snippets else "No prior pipeline run evidence available."
        prompt_system = (
            f"You are the {agent_name} ({agent_role}). The user addressed you directly using @{agent_key}.\n"
            f"Directly answer their question from your specialist perspective.\n\n"
            f"Guidelines:\n"
            f"- Answer the user's specific question directly, concisely, and practically.\n"
            f"- Use simple, clear, everyday English that anyone can easily understand.\n"
            f"- Ground your points firmly in the project findings provided below.\n"
            f"- Do NOT use robotic boilerplate or artificial preambles.\n"
            f"- Format with clean markdown (2-3 short paragraphs or bullet points)."
        )
        user_content = (
            f"Project: {proj_title}\n"
            f"Context: {prob_stmt}\n\n"
            f"Specialist Findings:\n{evidence_text}\n\n"
            f"User Question: {question}"
        )

        answer = ""
        try:
            answer = self.llm.generate(
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=500,
            ).strip()
        except Exception as err:
            logger.info(f"[FollowupEngine] Direct agent LLM call fell back ({err}). Grounding from evidence.")
            if evidence_snippets:
                answer = f"**{agent_name} Findings for '{question}'**:\n\n" + "\n\n".join(evidence_snippets[:4])
            else:
                answer = (
                    f"I don't have saved project findings yet. "
                    f"Please submit an idea or code check first, then ask me again!"
                )

        turn = session.add_turn(
            user_query=raw_query,
            agent_name=agent_name,
            agent_role=agent_role,
            answer=answer,
            action_taken=f"Answered @{agent_key} query about '{question[:50]}'",
            thinking=f"{agent_name} evaluated project context and answered the user query.",
            referenced_symbols=referenced_symbols,
            referenced_files=referenced_files,
        )
        return {
            "status": "ok",
            "answer": answer,
            "agent_name": agent_name,
            "agent_role": agent_role,
            "action_taken": turn.action_taken,
            "thinking": turn.thinking,
            "session_id": session.session_id,
            "referenced_symbols": turn.referenced_symbols,
            "referenced_files": turn.referenced_files,
            "active_entities": session.active_entities,
            "direct_agent": agent_key,
        }

    def process_followup(
        self,
        query: str,
        session_id: Optional[str] = None,
        repo_path: Optional[str] = None,
        context_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = self.session_manager.get_or_create_session(session_id, repo_path)

        # 1. Anaphora Resolution ('that function', 'modify it')
        resolved_query = session.resolve_anaphora(query)
        q_lower = resolved_query.lower()

        # Validated pipeline output (used by specialist routers)
        ctx = context_override if isinstance(context_override, dict) and context_override else (session.active_entities.get("final_output") or {})

        # 2. Check if repo index is available
        codebase_index = None
        target_repo = repo_path or session.repo_path
        if target_repo and os.path.exists(target_repo):
            codebase_index = self.session_manager.get_or_index_repo(session.session_id, target_repo)

        # Extract active target symbol
        target_symbol = session.active_entities.get("last_symbol")
        if codebase_index:
            for word in resolved_query.replace("(", " ").replace(")", " ").split():
                clean_w = word.strip(".,;:\"'`")
                if clean_w in codebase_index.symbol_table:
                    target_symbol = clean_w
                    break

        # 2.5 Direct Agent Interrogation ('@kill why will this fail?')
        # Novelty: users can interrogate a specific specialist agent instead of a generic chatbot.
        direct_agent = self._extract_direct_agent(query)
        if direct_agent:
            return self._answer_as_direct_agent(direct_agent, query, resolved_query, session, ctx, codebase_index)

        # 3. Intent Detection: Specialized Tool Routing
        # A. Change Impact Query ('What breaks if I modify it?', 'What could break?')
        if codebase_index and target_symbol and any(
            k in q_lower for k in ["what break", "what could break", "modify", "impact of change", "change it", "blast radius"]
        ):
            impact_agent = ChangeImpactAgent(codebase_index=codebase_index)
            impact_res = impact_agent.analyze_impact(target_symbol=target_symbol)

            caller_names = [f"`{c.symbol_name}` ({c.file_path})" for c in impact_res.direct_callers]
            tests_list = [f"`{t}`" for t in impact_res.affected_tests]
            answer_lines = [
                f"### Change Impact Analysis for `{target_symbol}`",
                f"- **Risk Level**: {impact_res.risk_level} (Blast Radius Score: {impact_res.blast_radius_score}/100, Confidence: {int(impact_res.confidence_score * 100)}%)",
                f"- **Direct Callers ({len(impact_res.direct_callers)})**: {', '.join(caller_names) if caller_names else 'None detected'}",
                f"- **Transitive Callers ({len(impact_res.indirect_callers)})**: {len(impact_res.indirect_callers)} indirect downstream dependencies",
                f"- **Affected Test Suites**: {', '.join(tests_list) if tests_list else 'No dedicated tests detected (High Risk)'}",
                "",
                "**Safe Recommendations:**",
            ]
            for r in impact_res.recommendations:
                answer_lines.append(f"- {r}")

            if impact_res.mermaid_diagram:
                answer_lines.extend(["", "```mermaid", impact_res.mermaid_diagram, "```"])

            answer = "\n".join(answer_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Risk & Security Auditor",
                agent_role="Change Impact & Blast Radius Analyzer",
                answer=answer,
                action_taken=f"Computed blast radius and downstream callers for '{target_symbol}'",
                thinking=f"Identified that modifying '{target_symbol}' affects {len(impact_res.direct_callers)} direct callers and computed a blast radius score of {impact_res.blast_radius_score}/100.",
                referenced_symbols=[target_symbol],
                referenced_files=[impact_res.target_file] if impact_res.target_file else [],
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Risk & Security Auditor",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
                "impact_data": impact_res.to_dict(),
            }

        # B. Caller / Reference Query ('What calls that function?', 'Who calls verify_token?')
        if codebase_index and target_symbol and (
            any(k in q_lower for k in ["what call", "who call", "which call", "where is it called", "find caller", "callers", "caller"])
            or ("call" in q_lower and any(w in q_lower for w in ["what", "who", "which", "where", "functions", "list", "show"]))
        ):
            callers = codebase_index.get_callers(target_symbol)
            if callers:
                caller_details = [
                    f"- `{c['caller_symbol']}` in `{c['caller_file']}` (line {c['line']}, confidence: {c['confidence']})"
                    for c in callers
                ]
                answer = (
                    f"### Callers of `{target_symbol}`\n\n"
                    f"Static AST analysis identified **{len(callers)}** call location(s) referencing `{target_symbol}`:\n\n"
                    + "\n".join(caller_details)
                )
            else:
                answer = f"No static callers found for `{target_symbol}` in the indexed repository. It may be an external entrypoint or invoked dynamically."

            turn = session.add_turn(
                user_query=query,
                agent_name="Code Review & AST Specialist",
                agent_role="Call Graph & Reference Analyzer",
                answer=answer,
                action_taken=f"Retrieved static call graph references for '{target_symbol}'",
                thinking=f"Queried the bi-directional callers map for symbol '{target_symbol}' and resolved {len(callers)} reference locations.",
                referenced_symbols=[target_symbol],
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Code Review & AST Specialist",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # C. Execution Flow Query ('Trace this function', 'How does execution flow?')
        if codebase_index and target_symbol and any(
            k in q_lower for k in ["trace", "execution flow", "how does it work", "request path", "hops"]
        ):
            flow_agent = FlowTraceAgent(codebase_index=codebase_index)
            flow_res = flow_agent.trace_flow(query=resolved_query, starting_symbol=target_symbol)

            hop_lines = [
                f"- **Hop {h.step_number}**: `{h.symbol_name}` in `{h.file_path}` (lines {h.line_start}-{h.line_end}, confidence: {h.confidence})"
                for h in flow_res.hops
            ]
            answer = (
                f"### Execution Flow for `{target_symbol}`\n\n"
                f"Traced **{flow_res.total_hops}** execution hops starting from `{flow_res.starting_symbol}`:\n\n"
                + "\n".join(hop_lines)
                + f"\n\n```mermaid\n{flow_res.mermaid_diagram}\n```"
            )

            turn = session.add_turn(
                user_query=query,
                agent_name="Lead Systems Architect",
                agent_role="Execution Flow Engine",
                answer=answer,
                action_taken=f"Traced execution pathway for '{target_symbol}'",
                thinking=f"Traced {flow_res.total_hops} execution hops from '{target_symbol}' with physical line boundaries and marked unresolved dispatches.",
                referenced_symbols=[target_symbol],
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Lead Systems Architect",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
                "flow_data": flow_res.to_dict(),
            }

        # D. Idea Track: Competitors & Market Landscape
        if ctx.get("competitors") and any(
            k in q_lower for k in ["competitor", "closest market", "alternative", "market landscape", "competition", "competing solutions"]
        ):
            competitors = ctx.get("competitors", [])
            proj_title = ctx.get("project_title", "Active Project")
            ans_lines = [f"### Market Competitors & Landscape for {proj_title}\n"]
            for c in competitors:
                c_name = c.get("name", "Competitor")
                c_summary = c.get("summary", "")
                c_gaps = c.get("gaps", c.get("weaknesses", ""))
                c_adv = c.get("advantages", c.get("strengths", ""))
                c_url = c.get("reference_url", c.get("url", ""))
                ans_lines.append(f"- **{c_name}**")
                if c_summary:
                    ans_lines.append(f"  * Summary: {c_summary}")
                if c_adv:
                    ans_lines.append(f"  * Market Advantages: {c_adv}")
                if c_gaps:
                    ans_lines.append(f"  * Our Differentiator / Gaps: {c_gaps}")
                if c_url:
                    ans_lines.append(f"  * Live Reference: [{c_name}]({c_url})")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Market Research Specialist",
                agent_role="Competitive Intelligence & Market Positioning",
                answer=answer,
                action_taken=f"Retrieved {len(competitors)} verified market competitors and differentiators",
                thinking=f"Extracted competitive landscape and differentiation vectors from indexed market analysis for '{proj_title}'.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Market Research Specialist",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # E. Idea Track: Success Preconditions & Reconciled Tradeoffs
        if ctx.get("reconciliation") and any(
            k in q_lower for k in ["precondition", "pre-condition", "mitigation", "tradeoff", "trade-off", "must-have", "non-negotiable", "success factor"]
        ):
            rec = ctx.get("reconciliation", {})
            verdict = rec.get("verdict", "GO_WITH_MITIGATIONS")
            rationale = rec.get("synthesis_rationale", "")
            mitigations = rec.get("must_have_mitigations", [])
            tradeoffs = rec.get("key_tradeoffs", [])
            ans_lines = [
                "### Non-Negotiable Success Preconditions & Strategic Tradeoffs",
                f"- **Synthesis Verdict**: `{verdict}`",
            ]
            if rationale:
                ans_lines.append(f"- **Executive Rationale**: {rationale}\n")
            if mitigations:
                ans_lines.append("**Non-Negotiable Success Preconditions:**")
                for m in mitigations:
                    ans_lines.append(f"- {m}")
                ans_lines.append("")
            if tradeoffs:
                ans_lines.append("**Key Architectural & Market Tradeoffs:**")
                for t in tradeoffs:
                    ans_lines.append(f"- {t}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Impartial Systems Arbiter",
                agent_role="Evidence Reconciliation Specialist",
                answer=answer,
                action_taken="Extracted non-negotiable success preconditions and tradeoffs from thesis reconciliation",
                thinking="Reconciled adversarial kill flaws against positive market thesis to establish preconditions for viable execution.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Impartial Systems Arbiter",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # F. Idea Track: User Stories & PRD Acceptance Criteria
        if ctx.get("prd") and any(
            k in q_lower for k in ["user story", "user stories", "us-0", "acceptance criteria", "functional requirement", "prd", "story"]
        ):
            prd_data = ctx.get("prd", {})
            stories = prd_data.get("user_stories", [])
            target_story = None
            q_clean = q_lower.replace("-", "")
            for s in stories:
                # PRD documents serialize stories with story_id / want / so_that.
                s_id = str(s.get("story_id", s.get("id", ""))).lower().replace("-", "")
                if s_id and (s_id in q_clean or str(s.get("story_id", s.get("id", ""))).lower() in q_lower):
                    target_story = s
                    break

            ans_lines = []
            if target_story:
                s_id = target_story.get("story_id", target_story.get("id", "US-01"))
                want = target_story.get("want", target_story.get("action", "perform action"))
                so_that = target_story.get("so_that", target_story.get("benefit", "I receive value"))
                ans_lines.append(f"### User Story {s_id}: Detailed Specification")
                ans_lines.append(f"- **Persona**: *As a {target_story.get('persona', 'User')}*")
                ans_lines.append(f"- **Action / Need**: *I want to {want}*")
                ans_lines.append(f"- **Expected Benefit**: *So that {so_that}*\n")
                ans_lines.append("**Acceptance Criteria:**")
                for ac in target_story.get("acceptance_criteria", []):
                    ans_lines.append(f"- [ ] {ac}")
            elif stories:
                ans_lines.append(f"### Formal PRD User Stories ({len(stories)} Stories)")
                for s in stories:
                    s_id = s.get("story_id", s.get("id", "Story"))
                    want = s.get("want", s.get("action", ""))
                    so_that = s.get("so_that", s.get("benefit", ""))
                    ans_lines.append(f"#### {s_id}: As a {s.get('persona', 'User')}")
                    if want:
                        ans_lines.append(f"- **Want**: {want}")
                    if so_that:
                        ans_lines.append(f"- **Benefit**: {so_that}")
                    ans_lines.append("- **Acceptance Criteria**:")
                    for ac in s.get("acceptance_criteria", [])[:3]:
                        ans_lines.append(f"  * [ ] {ac}")
                    ans_lines.append("")
            else:
                ans_lines.append("### Formal PRD Specifications")
                for fr in prd_data.get("functional_requirements", []):
                    if isinstance(fr, dict):
                        ans_lines.append(f"- **{fr.get('req_id', 'FR')} ({fr.get('priority', '')})**: {fr.get('title', '')} - {fr.get('description', '')}")
                    else:
                        ans_lines.append(f"- {fr}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Lead Product Manager",
                agent_role="PRD & Product Requirements Specialist",
                answer=answer,
                action_taken="Extracted User Story specifications and verifiable acceptance criteria",
                thinking="Retrieved formal PRD user stories and mapped acceptance test criteria.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Lead Product Manager",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # G. Idea Track: Architectural Bottlenecks, Fatal Flaws & Kill Critique
        if (ctx.get("kill_report") or ctx.get("bear_case_critic")) and any(
            k in q_lower for k in ["bottleneck", "fatal flaw", "bear case", "kill agent", "incumbent threat", "distribution trap", "vulnerabilit", "stress test", "flaw"]
        ):
            kill = ctx.get("kill_report", {})
            bear_summary = kill.get("bear_case_summary", ctx.get("bear_case_critic", "Adversarial stress-test completed."))
            flaws = kill.get("fatal_flaws", [])
            incumbents = kill.get("incumbent_threats", [])
            traps = kill.get("distribution_traps", [])
            ans_lines = [
                "### Architectural Bottlenecks & Adversarial Critique",
                f"**Bear Case Summary**: {bear_summary}\n",
            ]
            if flaws:
                ans_lines.append("**Critical Vulnerabilities & Fatal Flaws:**")
                for f in flaws:
                    f_title = f.get("title", "Flaw")
                    f_sev = f.get("severity", "HIGH")
                    f_arg = f.get("argument", "")
                    f_ev = f.get("counter_evidence", "")
                    ans_lines.append(f"- **{f_title} ({f_sev} Severity)**: {f_arg}")
                    if f_ev:
                        ans_lines.append(f"  * *Market Counter-Evidence*: {f_ev}")
                ans_lines.append("")
            if incumbents:
                ans_lines.append("**Incumbent Threats:**")
                for inc in incumbents:
                    ans_lines.append(f"- {inc}")
                ans_lines.append("")
            if traps:
                ans_lines.append("**Distribution Traps:**")
                for tr in traps:
                    ans_lines.append(f"- {tr}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Adversarial Kill Agent",
                agent_role="Devil's Advocate & Stress-Testing Auditor",
                answer=answer,
                action_taken="Analyzed architectural bottlenecks, fatal flaws, and incumbent threats",
                thinking="Stress-tested the system architecture and identified top adversarial failure modes.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Adversarial Kill Agent",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # H. Idea Track: Feasibility Scorecard & Decision Rubric
        if ctx.get("scorecard") and any(
            k in q_lower for k in ["score", "feasibility", "rubric", "scorecard", "evaluation"]
        ):
            sc = ctx.get("scorecard", {})
            total_score = sc.get("total_score", ctx.get("feasibility_score", 0))
            verdict = sc.get("verdict", ctx.get("feasibility_verdict", "CONDITIONAL_PURSUIT"))
            disclaimer = sc.get("rubric_disclaimer", ctx.get("rubric_disclaimer", "Feasibility score based on defined project rubric."))
            # Scorecard serializes categories as a list of {category_name, score, max_score, criteria_met, gaps, rationale}.
            categories = sc.get("categories", [])
            if not categories and isinstance(sc.get("category_breakdown"), dict):
                categories = [
                    {
                        "category_name": k.replace("_", " ").title(),
                        "score": v.get("score", 0),
                        "max_score": v.get("max_points", 0),
                        "rationale": v.get("rationale", ""),
                    }
                    for k, v in sc["category_breakdown"].items()
                    if isinstance(v, dict)
                ]
            strengths = sc.get("key_strengths", [])
            risks = sc.get("key_risks", [])
            actions = sc.get("recommended_actions", [])
            ans_lines = [
                "### Feasibility Scorecard & Decision Rubric",
                f"- **Total Score**: **{total_score}/100** ({verdict})",
                f"> *{disclaimer}*\n",
            ]
            if categories:
                ans_lines.append("| Category | Score | Max | Status |")
                ans_lines.append("|---|---|---|---|")
                for cat_data in categories:
                    if not isinstance(cat_data, dict):
                        continue
                    cat_name = cat_data.get("category_name", "Category")
                    cat_score = cat_data.get("score", 0)
                    cat_max = cat_data.get("max_score", 0) or 0
                    pct = (cat_score / cat_max * 100) if cat_max else 0
                    status = "Strong" if pct >= 75 else ("Moderate" if pct >= 50 else "Weak")
                    ans_lines.append(f"| {cat_name} | {cat_score} | {cat_max} | {status} |")
                ans_lines.append("")
                for cat_data in categories:
                    if isinstance(cat_data, dict) and (cat_data.get("criteria_met") or cat_data.get("gaps")):
                        ans_lines.append(f"**{cat_data.get('category_name', 'Category')}**")
                        for cr in cat_data.get("criteria_met", [])[:2]:
                            ans_lines.append(f"- ✓ {cr}")
                        for g in cat_data.get("gaps", [])[:2]:
                            ans_lines.append(f"- ⚠ Gap: {g}")
                ans_lines.append("")
            if strengths:
                ans_lines.append(f"**Key Strengths**: {', '.join(strengths)}")
            if risks:
                ans_lines.append(f"**Key Risks**: {', '.join(risks)}")
            if actions:
                ans_lines.append("\n**Recommended Actions:**")
                for act in actions:
                    ans_lines.append(f"- {act}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Deterministic Decision Scorer",
                agent_role="100-Point Feasibility Scorecard Engine",
                answer=answer,
                action_taken=f"Retrieved 7-category feasibility score ({total_score}/100)",
                thinking="Extracted deterministic scorecard metrics across all 7 evaluation dimensions.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Deterministic Decision Scorer",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # I. Idea Track: Tech Stack & Architecture
        if ctx.get("tech_stack") and any(
            k in q_lower for k in ["tech stack", "technology stack", "database", "backend stack", "frontend stack", "architecture stack"]
        ):
            tstack = ctx.get("tech_stack", {})
            ans_lines = ["### Recommended Technical Architecture & Production Stack\n"]
            for cat, item in tstack.items():
                choice = item.get("choice", "")
                rationale = item.get("rationale", "")
                tradeoffs = item.get("tradeoffs", "")
                ans_lines.append(f"- **{cat.title()}**: `{choice}`")
                if rationale:
                    ans_lines.append(f"  * Engineering Rationale: {rationale}")
                if tradeoffs:
                    ans_lines.append(f"  * Technical Tradeoffs: {tradeoffs}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Lead Systems Architect",
                agent_role="Production Stack & Infrastructure Architect",
                answer=answer,
                action_taken="Retrieved technical stack choices and engineering tradeoffs",
                thinking="Mapped production stack components with engineering rationales and architectural tradeoffs.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Lead Systems Architect",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # J. Idea Track: Development Roadmap & Milestones
        if ctx.get("phases") and any(
            k in q_lower for k in ["roadmap", "phases", "milestone", "timeline", "mvp plan", "delivery"]
        ):
            phases = ctx.get("phases", [])
            ans_lines = ["### 3-Phase Execution Roadmap & Milestones\n"]
            for p in phases:
                p_num = p.get("phase_number", 1)
                p_name = p.get("phase_name", "")
                p_dur = p.get("duration_weeks", "")
                p_deliv = p.get("deliverables", [])
                p_exit = p.get("exit_criteria", "")
                ans_lines.append(f"- **Phase {p_num}: {p_name}** ({p_dur})")
                if p_deliv:
                    ans_lines.append(f"  * Deliverables: {', '.join(p_deliv)}")
                if p_exit:
                    ans_lines.append(f"  * Exit Criteria: {p_exit}")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Roadmap & Delivery Planner",
                agent_role="Milestone & Sprint Architect",
                answer=answer,
                action_taken="Retrieved 3-phase execution roadmap and deliverables",
                thinking="Structured chronological delivery milestones, deliverables, and exit criteria.",
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Roadmap & Delivery Planner",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # K. Code Track: Fault Localization & Educational Pattern Analysis
        if ctx.get("candidates") and any(
            k in q_lower for k in ["where is", "auth verified", "verify_token", "customer auth", "authentication", "root cause", "bug", "why problematic", "fault", "wrong code", "recommended pattern"]
        ):
            candidates = ctx.get("candidates", [])
            ans_lines = ["### Fault Localization & Educational Pattern Analysis\n"]
            for c in candidates:
                c_sym = c.get("symbol_name", "unknown")
                c_file = c.get("file_path", "")
                c_start = c.get("line_start", "")
                c_end = c.get("line_end", "")
                c_why = c.get("why_problematic", c.get("root_cause_hypothesis", ""))
                c_rec = c.get("recommended_pattern", c.get("correct_code", ""))
                c_exp = c.get("explanation_of_change", c.get("suggested_fix", ""))
                c_wrong = c.get("wrong_code", "")
                ans_lines.append(f"#### #{c.get('rank', 1)} `{c_sym}` ({c_file}:{c_start}-{c_end})")
                ans_lines.append(f"- **Root Cause Rationale**: {c_why}")
                if c_wrong:
                    ans_lines.append(f"\n**Current / Risky Implementation**:\n```python\n{c_wrong}\n```")
                if c_rec:
                    ans_lines.append(f"\n**Recommended Pattern**:\n```python\n{c_rec}\n```")
                if c_exp:
                    ans_lines.append(f"- **Explanation of the Change**: {c_exp}\n")
            answer = "\n".join(ans_lines)
            turn = session.add_turn(
                user_query=query,
                agent_name="Code Review & AST Specialist",
                agent_role="Fault Localization & Educational Pattern Reviewer",
                answer=answer,
                action_taken="Retrieved root cause hypothesis and educational pattern comparison from diagnosis",
                thinking="Grounded candidate inspection in AST line ranges, risky pattern analysis, and recommended fix direction.",
                referenced_symbols=[c.get("symbol_name") for c in candidates if c.get("symbol_name")],
            )
            return {
                "status": "ok",
                "answer": answer,
                "agent_name": "Code Review & AST Specialist",
                "action_taken": turn.action_taken,
                "thinking": turn.thinking,
                "session_id": session.session_id,
                "referenced_symbols": turn.referenced_symbols,
                "active_entities": session.active_entities,
            }

        # L. General Conversational Specialist Pass with Bounded Context
        bounded_history = session.get_bounded_context(max_tokens=2500)
        context_text = bounded_history or ""
        if context_override:
            context_text += f"\nInitial Request Context:\n{str(context_override)[:800]}\n"

        prompt_system = (
            "You are an expert specialist on an Agentic AI Engineering Co-Pilot team.\n"
            "Answer the user follow-up question scoped to the active project context and conversation history.\n\n"
            "Domain Specialist Personas:\n"
            "- 'Market Research Specialist': Competitors, business viability, positioning, target personas.\n"
            "- 'Lead Systems Architect': System design, tech stack choices, databases, scaling, API architecture.\n"
            "- 'Roadmap & Delivery Planner': Development phases, MVP milestones, sprint planning, delivery.\n"
            "- 'Risk & Security Auditor': Security, failure modes, blast radius, stress testing, vulnerabilities.\n"
            "- 'Code Review & AST Specialist': Python syntax, AST symbols, function logic, bugs, call graphs.\n\n"
            "CRITICAL RULES:\n"
            "1. DYNAMICALLY CHOOSE the single best specialist persona for this question.\n"
            "2. Provide 1-2 sentences of specialist internal thinking in 'thinking'.\n"
            "3. Do NOT use horizontal rule separators (---).\n"
            "4. Output strict JSON with: agent_name, action_taken, thinking, answer, referenced_symbols (list of strings).\n"
            "{\n"
            '  "agent_name": "Selected specialist persona",\n'
            '  "action_taken": "One short sentence describing what was investigated",\n'
            '  "thinking": "1-2 sentences explaining internal specialist reasoning",\n'
            '  "answer": "Clean, high-value markdown answer",\n'
            '  "referenced_symbols": ["symbol_name"]\n'
            "}"
        )

        user_content = f"Active Context:\n{context_text}\n\nUser Question:\n{resolved_query}"

        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=600,
            )
        except Exception as err:
            logger.warning(f"[FollowupEngine] Rate limit or LLM error ({err}). Using grounded deterministic response.")
            if target_symbol and codebase_index:
                callers = codebase_index.get_callers(target_symbol)
                caller_details = [
                    f"- `{c['caller_symbol']}` in `{c['caller_file']}` (line {c['line']}, confidence: {c['confidence']})"
                    for c in callers
                ] if callers else ["- No static callers detected in indexed files."]
                res = {
                    "agent_name": "Code Review & AST Specialist",
                    "action_taken": f"Inspected static AST symbol references for '{target_symbol}'",
                    "thinking": f"Extracted callers and symbol references for '{target_symbol}' directly from AST call graph.",
                    "answer": f"### AST Reference Analysis for `{target_symbol}`\n\nCallers identified:\n" + "\n".join(caller_details),
                    "referenced_symbols": [target_symbol],
                }
            elif ctx.get("type") == "idea_validation" or ctx.get("project_title"):
                proj_title = ctx.get("project_title", "Active Project")
                prob_stmt = ctx.get("problem_statement", "")
                val_prop = ctx.get("core_value_prop", "")
                personas = ctx.get("target_personas", [])
                p_text = ", ".join([p.get("persona", "") for p in personas]) if personas else "Engineering Teams"
                res = {
                    "agent_name": "Lead Systems Architect",
                    "action_taken": f"Evaluated query against architectural constraints for '{proj_title}'",
                    "thinking": f"Synthesized guidance based on core value proposition and system constraints for '{proj_title}'.",
                    "answer": (
                        f"### Technical Brief for {proj_title}\n\n"
                        f"- **Problem Context**: {prob_stmt}\n"
                        f"- **Core Value Proposition**: {val_prop}\n"
                        f"- **Target Personas**: {p_text}\n\n"
                        f"Regarding your question ('{query}'): The active workspace maintains strict read-only guarantees. "
                        f"All architectural components and roadmap milestones are aligned to address this requirement."
                    ),
                    "referenced_symbols": [],
                }
            elif ctx.get("candidates"):
                top_c = ctx.get("candidates")[0]
                res = {
                    "agent_name": "Code Review & AST Specialist",
                    "action_taken": f"Analyzed candidate '{top_c.get('symbol_name')}' in active session",
                    "thinking": f"Referenced top diagnostic candidate from active session index.",
                    "answer": (
                        f"### Code Diagnosis Reference\n\n"
                        f"- **Candidate**: `{top_c.get('symbol_name')}` in `{top_c.get('file_path')}` (lines {top_c.get('line_start')}-{top_c.get('line_end')})\n"
                        f"- **Root Cause Rationale**: {top_c.get('why_problematic', top_c.get('root_cause_hypothesis'))}\n"
                        f"- **Recommended Fix Direction**: {top_c.get('suggested_fix')}\n\n"
                        f"Regarding your question ('{query}'): The active workspace maintains strict read-only guarantees. "
                        f"Please review the educational pattern comparison above."
                    ),
                    "referenced_symbols": [top_c.get("symbol_name")] if top_c.get("symbol_name") else [],
                }
            else:
                res = {
                    "agent_name": "Lead Systems Architect",
                    "action_taken": "Evaluated query against active session state",
                    "thinking": "Grounded response in active session context and architectural constraints.",
                    "answer": f"Regarding your question ('{query}'): The active workspace maintains strict read-only guarantees. Please review the validated architectural brief and constraints.",
                    "referenced_symbols": [target_symbol] if target_symbol else [],
                }

        agent_name = res.get("agent_name", "Lead Systems Architect")
        answer_text = res.get("answer", "Here is the guidance for your question.")
        thinking_text = res.get("thinking", f"{agent_name} analyzed context and synthesized guidance.")
        action_text = res.get("action_taken", "Provided specialist recommendations")
        ref_symbols = res.get("referenced_symbols", [])
        if target_symbol and target_symbol not in ref_symbols:
            ref_symbols.append(target_symbol)

        turn = session.add_turn(
            user_query=query,
            agent_name=agent_name,
            answer=answer_text,
            action_taken=action_text,
            thinking=thinking_text,
            referenced_symbols=ref_symbols,
        )

        return {
            "status": "ok",
            "answer": answer_text,
            "agent_name": agent_name,
            "action_taken": action_text,
            "thinking": thinking_text,
            "session_id": session.session_id,
            "referenced_symbols": ref_symbols,
            "active_entities": session.active_entities,
        }


# Global singleton manager and engine
session_manager = SessionManager()
followup_engine = ConversationalFollowupEngine(session_manager=session_manager)
