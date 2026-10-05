"""
Workflow State Schema for the Multi-Agent Co-Pilot.
Maintains state transitions, agent handoffs, execution traces, and metrics.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TraceStep:
    step_id: int
    agent_name: str
    action: str
    status: str  # 'running', 'completed', 'warning', 'revised'
    elapsed_ms: int
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
        self, agent_name: str, action: str, status: str = "completed", details: Optional[Dict[str, Any]] = None
    ) -> None:
        elapsed = int((time.time() - self.start_time) * 1000)
        step = TraceStep(
            step_id=len(self.execution_trace) + 1,
            agent_name=agent_name,
            action=action,
            status=status,
            elapsed_ms=elapsed,
            details=details or {},
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
