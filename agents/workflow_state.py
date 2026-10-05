"""
Workflow State Schema for the Multi-Agent Co-Pilot.
Maintains state transitions, agent handoffs, execution traces, and metrics.
Task 9.12: Standardized Agent Execution Trace Schema.

Guarantees:
- Captures component, role, action, status, duration, input/output summary, and evidence counts.
- Excludes internal private chain-of-thought dumps to maintain clean, readable transparency.
- Full backwards-compatibility with existing add_trace calls.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TraceStep:
    step_id: int
    agent_name: str
    action: str
    status: str  # 'running', 'completed', 'warning', 'revised', 'failed'
    elapsed_ms: int
    details: Dict[str, Any] = field(default_factory=dict)
    # Standardized Phase 9 Observability Fields
    agent_role: str = ""
    duration_ms: int = 0
    input_summary: str = ""
    output_summary: str = ""
    evidence_count: int = 0
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role or self.agent_name,
            "action": self.action,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "duration_ms": self.duration_ms or self.elapsed_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "evidence_count": self.evidence_count,
            "citations": self.citations,
            "details": self.details,
        }


@dataclass
class AgentWorkflowState:
    session_id: str
    user_query: str
    repo_path: Optional[str] = None
    intent: Optional[str] = None  # 'codebase_analysis' | 'idea_validation'
    intent_confidence: float = 0.0
    plan_steps: List[str] = field(default_factory=list)
    current_step_index: int = 0
    revision_count: int = 0
    max_revisions: int = 1

    # Track Outputs
    code_result: Optional[Dict[str, Any]] = None
    idea_result: Optional[Dict[str, Any]] = None
    final_output: Optional[Dict[str, Any]] = None

    # Observability
    execution_trace: List[TraceStep] = field(default_factory=list)
    total_latency_ms: int = 0
    start_time: float = field(default_factory=time.time)

    def add_trace(
        self,
        agent_name: str,
        action: str,
        status: str = "completed",
        details: Optional[Dict[str, Any]] = None,
        agent_role: str = "",
        input_summary: str = "",
        output_summary: str = "",
        evidence_count: int = 0,
        citations: Optional[List[str]] = None,
        duration_ms: int = 0,
    ) -> None:
        """
        Records a standardized execution trace step for an agent action.
        Maintains complete backward compatibility with older positional callers.
        """
        elapsed = int((time.time() - self.start_time) * 1000)
        step = TraceStep(
            step_id=len(self.execution_trace) + 1,
            agent_name=agent_name,
            action=action,
            status=status,
            elapsed_ms=elapsed,
            details=details or {},
            agent_role=agent_role or agent_name,
            duration_ms=duration_ms or (elapsed if not self.execution_trace else elapsed - self.execution_trace[-1].elapsed_ms),
            input_summary=input_summary,
            output_summary=output_summary,
            evidence_count=evidence_count,
            citations=citations or [],
        )
        self.execution_trace.append(step)

    def finalize(self) -> None:
        self.total_latency_ms = int((time.time() - self.start_time) * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_query": self.user_query,
            "repo_path": self.repo_path,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "plan_steps": self.plan_steps,
            "revision_count": self.revision_count,
            "final_output": self.final_output,
            "execution_trace": [t.to_dict() for t in self.execution_trace],
            "total_latency_ms": self.total_latency_ms,
        }
