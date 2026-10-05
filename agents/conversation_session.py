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

        # D. General Conversational Specialist Pass with Bounded Context
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
