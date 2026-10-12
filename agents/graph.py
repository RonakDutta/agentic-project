"""Explicit LangGraph state graph over the orchestrator (synopsis Sec 9, Fig 1).

The graph's nodes are the orchestrator's real steps, so running the graph runs
the actual agents:

    classify --(intent)--> codebase_pipeline --> finalize
             \\-----------> idea_pipeline -----/

- classify:           Orchestrator intent classification and plan.
- codebase_pipeline:  AST index -> hybrid retrieval -> diagnosis -> deterministic
                      critic (with one critic-driven revision inside the node).
- idea_pipeline:      decomposition -> market search -> kill agent -> reconciler ->
                      scorecard -> PRD, with the roadmap running in parallel.
- finalize:           closes the trace and registers the follow-up session.

If `langgraph` is not installed, the same four steps run in sequence through
`orchestrator.process()`. `GET /api/graph` reports which backend is active, so
the demo diagram always matches what actually ran.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

GRAPH_NODES = ["classify", "codebase_pipeline", "idea_pipeline", "finalize"]

GRAPH_EDGES = [
    ("classify", "codebase_pipeline", "intent == codebase_analysis"),
    ("classify", "idea_pipeline", "intent == idea_validation"),
    ("codebase_pipeline", "finalize", ""),
    ("idea_pipeline", "finalize", ""),
]

# Agents each node runs, for the architecture view in the UI.
NODE_AGENTS = {
    "classify": ["Orchestrator Agent"],
    "codebase_pipeline": ["Code Structure Indexer", "Code Navigation Agent", "Diagnosis Agent", "Deterministic Critic"],
    "idea_pipeline": [
        "Idea Decomposer", "Market & Competitor Researcher", "Adversarial Kill Agent", "Evidence Reconciler",
        "Feasibility Scorecard Engine", "PRD & Architecture Specialist", "Roadmap & Risk Assessor",
    ],
    "finalize": ["Orchestrator Agent"],
}


def _langgraph_version() -> Optional[str]:
    try:
        import langgraph  # type: ignore  # noqa: F401
    except Exception:
        return None
    try:
        from importlib.metadata import version
        return version("langgraph")
    except Exception:
        return "installed"


def _build_graph():
    """Compiles the StateGraph, or returns None when langgraph is unavailable."""
    try:
        from typing import TypedDict
        from langgraph.graph import StateGraph, END  # type: ignore
    except Exception as err:
        logger.info(f"[graph] langgraph unavailable, using sequential fallback ({err})")
        return None

    from agents.orchestrator import orchestrator

    class GraphState(TypedDict, total=False):
        workflow: Any          # AgentWorkflowState, mutated by each node
        force_intent: Optional[str]
        visited: list          # node names in the order they ran

    def _visit(state: GraphState, name: str) -> list:
        return list(state.get("visited") or []) + [name]

    def classify(state: GraphState) -> GraphState:
        orchestrator.classify(state["workflow"], state.get("force_intent"))
        return {"visited": _visit(state, "classify")}

    def codebase_pipeline(state: GraphState) -> GraphState:
        orchestrator.execute_track(state["workflow"])
        return {"visited": _visit(state, "codebase_pipeline")}

    def idea_pipeline(state: GraphState) -> GraphState:
        orchestrator.execute_track(state["workflow"])
        return {"visited": _visit(state, "idea_pipeline")}

    def finalize(state: GraphState) -> GraphState:
        orchestrator.finalize(state["workflow"])
        return {"visited": _visit(state, "finalize")}

    def route(state: GraphState) -> str:
        return "codebase_pipeline" if state["workflow"].intent == "codebase_analysis" else "idea_pipeline"

    builder = StateGraph(GraphState)
    builder.add_node("classify", classify)
    builder.add_node("codebase_pipeline", codebase_pipeline)
    builder.add_node("idea_pipeline", idea_pipeline)
    builder.add_node("finalize", finalize)
    builder.set_entry_point("classify")
    builder.add_conditional_edges(
        "classify", route, {"codebase_pipeline": "codebase_pipeline", "idea_pipeline": "idea_pipeline"}
    )
    builder.add_edge("codebase_pipeline", "finalize")
    builder.add_edge("idea_pipeline", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


_COMPILED = None
_COMPILE_TRIED = False


def _compiled():
    global _COMPILED, _COMPILE_TRIED
    if not _COMPILE_TRIED:
        _COMPILE_TRIED = True
        try:
            _COMPILED = _build_graph()
        except Exception as err:
            logger.warning(f"[graph] could not compile graph, using sequential fallback ({err})")
            _COMPILED = None
    return _COMPILED


def graph_spec() -> Dict[str, Any]:
    version = _langgraph_version()
    backend = f"langgraph-{version}" if version and _compiled() is not None else "sequential-fallback (langgraph not installed)"
    return {
        "backend": backend,
        "nodes": GRAPH_NODES,
        "edges": [list(e[:2]) for e in GRAPH_EDGES],
        "edge_conditions": {f"{a}->{b}": cond for a, b, cond in GRAPH_EDGES if cond},
        "node_agents": NODE_AGENTS,
    }


def run(query: str, repo_path: Optional[str] = None,
        force_intent: Optional[str] = None) -> Dict[str, Any]:
    """Executes the full pipeline through the graph (or the sequential fallback)."""
    from agents.orchestrator import orchestrator

    graph = _compiled()
    if graph is not None:
        workflow = orchestrator.new_state(query, repo_path)
        result = graph.invoke({"workflow": workflow, "force_intent": force_intent, "visited": []})
        payload = workflow.to_dict()
        visited = result.get("visited", [])
    else:
        workflow = orchestrator.process(query=query, repo_path=repo_path, force_intent=force_intent)
        payload = workflow.to_dict()
        visited = ["classify", "codebase_pipeline" if workflow.intent == "codebase_analysis" else "idea_pipeline", "finalize"]

    payload["graph"] = dict(graph_spec(), visited=visited)
    return payload
