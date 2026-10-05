"""
Flow Trace Agent for Codebase Execution Pathway Investigation.
Inspired by PRISM (Agentic RAG for Codebase Intelligence).

Traces how a request or transaction traverses across files, functions, and services
from an entrypoint to destination (e.g. API endpoint -> service -> helper -> DB sink).

Guarantees:
- Every hop contains exact file, symbol, physical line range, and relationship type.
- Unproven dynamic calls are explicitly marked as UNRESOLVED (never fabricated).
- Produces clean Mermaid sequence/flow diagrams.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from indexer.ast_parser import CodebaseIndex, CodeChunk


@dataclass
class FlowHop:
    step_number: int
    file_path: str
    symbol_name: str
    signature: str
    line_start: int
    line_end: int
    relationship: str  # 'entrypoint', 'direct_call', 'method_call', 'unresolved_dispatch'
    confidence: str  # 'high', 'medium', 'unresolved'
    evidence_snippet: str
    status: str = "resolved"  # 'resolved', 'unresolved'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FlowTraceResult:
    query: str
    starting_symbol: str
    hops: List[FlowHop]
    total_hops: int
    unresolved_count: int
    mermaid_diagram: str
    summary: str
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "starting_symbol": self.starting_symbol,
            "total_hops": self.total_hops,
            "unresolved_count": self.unresolved_count,
            "hops": [h.to_dict() for h in self.hops],
            "mermaid_diagram": self.mermaid_diagram,
            "summary": self.summary,
            "trace": self.trace,
        }


class FlowTraceAgent:
    """
    Traces execution flow through static call graphs and marks ambiguous dispatches as UNRESOLVED.
    """

    def __init__(self, codebase_index: CodebaseIndex):
        self.codebase_index = codebase_index

    def trace_flow(
        self,
        query: str,
        starting_symbol: Optional[str] = None,
        max_depth: int = 6,
    ) -> FlowTraceResult:
        trace_logs = [f"FlowTraceAgent initialized for query: '{query}'"]

        # 1. Resolve starting symbol
        start_sym = starting_symbol
        if not start_sym:
            # Heuristic match from query words against symbol table
            for word in query.replace("(", " ").replace(")", " ").split():
                clean_word = word.strip(".,;:\"'")
                if clean_word in self.codebase_index.symbol_table:
                    start_sym = clean_word
                    break

        if not start_sym:
            # Fallback to first available entrypoint or top symbol
            for chunk in self.codebase_index.chunks:
                if chunk.chunk_type == "function" and chunk.name in ("handle_login", "main", "process_order"):
                    start_sym = chunk.name
                    break

        if not start_sym and self.codebase_index.chunks:
            # Default to first non-module function
            for chunk in self.codebase_index.chunks:
                if chunk.chunk_type == "function":
                    start_sym = chunk.name
                    break

        if not start_sym:
            return FlowTraceResult(
                query=query,
                starting_symbol="none",
                hops=[],
                total_hops=0,
                unresolved_count=0,
                mermaid_diagram="flowchart TD\n    None[\"No entrypoint identified\"]",
                summary="Could not identify starting symbol in codebase index.",
                trace=trace_logs,
            )

        trace_logs.append(f"Identified starting entrypoint symbol: '{start_sym}'")

        # 2. Step 1: Initial Entrypoint Hop
        start_defs = self.codebase_index.lookup_symbol(start_sym)
        first_chunk: Optional[CodeChunk] = None
        for chunk in self.codebase_index.chunks:
            if chunk.name == start_sym or chunk.id.endswith(f":{start_sym}"):
                first_chunk = chunk
                break

        hops: List[FlowHop] = []
        visited_symbols: Set[str] = set()
        unresolved_count = 0

        if first_chunk:
            hops.append(
                FlowHop(
                    step_number=1,
                    file_path=first_chunk.file_path,
                    symbol_name=first_chunk.name,
                    signature=first_chunk.signature,
                    line_start=first_chunk.start_line,
                    line_end=first_chunk.end_line,
                    relationship="entrypoint",
                    confidence="high",
                    evidence_snippet=first_chunk.signature,
                    status="resolved",
                )
            )
            visited_symbols.add(first_chunk.name)

        # 3. Breadth / Depth call traversal
        curr_chunk = first_chunk
        depth = 1

        while curr_chunk and depth < max_depth:
            depth += 1
            callees = curr_chunk.call_details
            if not callees:
                trace_logs.append(f"Reached leaf function '{curr_chunk.name}'; no further internal outgoing calls.")
                break

            # Find next unresolved or internal callee
            next_hop_found = False
            for callee in callees:
                target = callee["target"]
                short_target = target.split(".")[-1]

                if short_target in visited_symbols or short_target in ("print", "len", "range", "dict", "str", "int"):
                    continue

                visited_symbols.add(short_target)

                # Look up callee definition in repository chunks
                callee_chunk = None
                for c in self.codebase_index.chunks:
                    if c.name == short_target or c.name == target or c.id.endswith(f":{short_target}"):
                        callee_chunk = c
                        break

                if callee_chunk:
                    hops.append(
                        FlowHop(
                            step_number=len(hops) + 1,
                            file_path=callee_chunk.file_path,
                            symbol_name=callee_chunk.name,
                            signature=callee_chunk.signature,
                            line_start=callee_chunk.start_line,
                            line_end=callee_chunk.end_line,
                            relationship="direct_call" if callee["confidence"] == "high" else "method_call",
                            confidence=callee["confidence"],
                            evidence_snippet=f"line {callee['line']}: {callee['raw_expr']}",
                            status="resolved",
                        )
                    )
                    curr_chunk = callee_chunk
                    next_hop_found = True
                    break
                else:
                    # Unresolved dynamic or external call
                    unresolved_count += 1
                    hops.append(
                        FlowHop(
                            step_number=len(hops) + 1,
                            file_path=curr_chunk.file_path,
                            symbol_name=target,
                            signature=f"call {target}()",
                            line_start=callee["line"],
                            line_end=callee["line"],
                            relationship="unresolved_dispatch",
                            confidence="unresolved",
                            evidence_snippet=f"line {callee['line']}: {callee['raw_expr']} (external / dynamic dispatch)",
                            status="unresolved",
                        )
                    )
                    curr_chunk = None
                    next_hop_found = True
                    break

            if not next_hop_found:
                break

        # 4. Generate Mermaid diagram
        mermaid_lines = ["flowchart TD"]
        for i, hop in enumerate(hops):
            node_id = f"Step{hop.step_number}"
            clean_name = hop.symbol_name.replace('"', '')
            if hop.status == "unresolved":
                label = f"{hop.step_number}. {clean_name} [UNRESOLVED]"
            else:
                label = f"{hop.step_number}. {hop.file_path}:{clean_name}()"
            mermaid_lines.append(f'    {node_id}["{label}"]')
            if i > 0:
                prev_id = f"Step{hops[i-1].step_number}"
                rel_label = hops[i].relationship.replace("_", " ")
                mermaid_lines.append(f"    {prev_id} -->|{rel_label}| {node_id}")

        mermaid_code = "\n".join(mermaid_lines)

        # 5. Plain English Summary
        summary_lines = [f"Flow Trace executed across {len(hops)} hops starting from `{start_sym}`:"]
        for hop in hops:
            if hop.status == "unresolved":
                summary_lines.append(f"- Step {hop.step_number}: `{hop.symbol_name}` [UNRESOLVED dynamic dispatch at {hop.file_path}:{hop.line_start}]")
            else:
                summary_lines.append(f"- Step {hop.step_number}: `{hop.file_path}` -> `{hop.symbol_name}()` (lines {hop.line_start}-{hop.line_end})")

        return FlowTraceResult(
            query=query,
            starting_symbol=start_sym,
            hops=hops,
            total_hops=len(hops),
            unresolved_count=unresolved_count,
            mermaid_diagram=mermaid_code,
            summary="\n".join(summary_lines),
            trace=trace_logs,
        )
