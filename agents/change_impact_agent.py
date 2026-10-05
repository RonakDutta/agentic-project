"""
Change Impact Analysis Agent.
Estimates the blast radius and downstream dependencies of modifying a function, class, or module.
Inspired by AutoCodeRover and PRISM.

Guarantees:
- Deterministic traversal of direct callers and transitive callers (2-3 levels deep).
- Import-level dependency graph scanning.
- Test coverage detection (identifies which test suites exercise the target).
- Explicit risk level (Low/Medium/High) and confidence scoring.
- Zero code editing or automated patching; strictly read-only impact estimation.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from indexer.ast_parser import CodebaseIndex


@dataclass
class AffectedCaller:
    file_path: str
    symbol_name: str
    line: int
    depth: int  # 1 for direct, 2+ for indirect/transitive
    confidence: str  # 'high', 'medium', 'unresolved'
    call_expr: str
    is_entrypoint: bool = False
    is_test: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeImpactResult:
    target_symbol: str
    target_file: str
    risk_level: str  # 'Low', 'Medium', 'High'
    confidence_score: float  # 0.0 to 1.0
    blast_radius_score: int  # 0 to 100
    direct_callers: List[AffectedCaller] = field(default_factory=list)
    indirect_callers: List[AffectedCaller] = field(default_factory=list)
    dependent_files: List[str] = field(default_factory=list)
    affected_tests: List[str] = field(default_factory=list)
    affected_entrypoints: List[str] = field(default_factory=list)
    mermaid_diagram: str = ""
    recommendations: List[str] = field(default_factory=list)
    summary: str = ""
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_symbol": self.target_symbol,
            "target_file": self.target_file,
            "risk_level": self.risk_level,
            "confidence_score": round(self.confidence_score, 2),
            "blast_radius_score": self.blast_radius_score,
            "direct_callers_count": len(self.direct_callers),
            "indirect_callers_count": len(self.indirect_callers),
            "direct_callers": [c.to_dict() for c in self.direct_callers],
            "indirect_callers": [c.to_dict() for c in self.indirect_callers],
            "dependent_files": self.dependent_files,
            "affected_tests": self.affected_tests,
            "affected_entrypoints": self.affected_entrypoints,
            "mermaid_diagram": self.mermaid_diagram,
            "recommendations": self.recommendations,
            "summary": self.summary,
            "trace": self.trace,
        }


class ChangeImpactAgent:
    """
    Analyzes blast radius and caller impact when a codebase symbol is modified.
    """

    ENTRYPOINT_FILE_HINTS = ("app.py", "main.py", "routes.py", "api.py", "server.py", "cli.py", "manage.py")
    ENTRYPOINT_FUNC_HINTS = ("handle_", "api_", "route_", "endpoint_", "get_", "post_", "put_", "delete_")

    def __init__(self, codebase_index: CodebaseIndex):
        self.codebase_index = codebase_index

    def _is_test_file(self, file_path: str) -> bool:
        norm = file_path.replace("\\", "/").lower()
        parts = norm.split("/")
        filename = parts[-1]
        return (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or "tests" in parts
            or "test" in parts
        )

    def _is_entrypoint(self, file_path: str, symbol_name: str) -> bool:
        norm = file_path.replace("\\", "/").lower()
        filename = norm.split("/")[-1]
        if filename in self.ENTRYPOINT_FILE_HINTS:
            return True
        for prefix in self.ENTRYPOINT_FUNC_HINTS:
            if symbol_name.lower().startswith(prefix):
                return True
        return False

    def analyze_impact(
        self,
        target_symbol: str,
        target_file: Optional[str] = None,
        max_depth: int = 3,
    ) -> ChangeImpactResult:
        trace_logs = [f"ChangeImpactAgent started for target: '{target_symbol}'"]

        # 1. Resolve Target Symbol and Target File
        resolved_file = target_file or ""
        short_target = target_symbol.split(".")[-1]
        sym_entries = self.codebase_index.lookup_symbol(short_target)
        if not sym_entries:
            sym_entries = self.codebase_index.lookup_symbol(target_symbol)

        if sym_entries and not resolved_file:
            resolved_file = sym_entries[0]["file"]
            trace_logs.append(f"Resolved symbol '{target_symbol}' to file: {resolved_file}")
        elif not resolved_file:
            # Check if target is a file in the index
            norm_target = target_symbol.replace("\\", "/")
            if norm_target in self.codebase_index.file_list:
                resolved_file = norm_target
                trace_logs.append(f"Target '{target_symbol}' identified as file directly.")

        # 2. Direct Callers (Depth 1)
        raw_direct = self.codebase_index.get_callers(target_symbol)
        if not raw_direct and short_target != target_symbol:
            raw_direct = self.codebase_index.get_callers(short_target)

        direct_callers: List[AffectedCaller] = []
        visited_callers: Set[str] = set()

        for c in raw_direct:
            key = f"{c['caller_file']}:{c['caller_symbol']}"
            if key in visited_callers:
                continue
            visited_callers.add(key)

            is_entry = self._is_entrypoint(c["caller_file"], c["caller_symbol"])
            is_tst = self._is_test_file(c["caller_file"])

            direct_callers.append(
                AffectedCaller(
                    file_path=c["caller_file"],
                    symbol_name=c["caller_symbol"],
                    line=c["line"],
                    depth=1,
                    confidence=c.get("confidence", "high"),
                    call_expr=c.get("raw_expr", f"{target_symbol}()"),
                    is_entrypoint=is_entry,
                    is_test=is_tst,
                )
            )

        trace_logs.append(f"Discovered {len(direct_callers)} direct callers at depth 1.")

        # 3. Transitive Callers (Depth 2 to max_depth)
        indirect_callers: List[AffectedCaller] = []
        current_layer = [c.symbol_name for c in direct_callers if not c.is_test]

        for current_depth in range(2, max_depth + 1):
            if not current_layer:
                break
            next_layer: List[str] = []
            for caller_name in current_layer:
                transitive_raw = self.codebase_index.get_callers(caller_name)
                for tr in transitive_raw:
                    key = f"{tr['caller_file']}:{tr['caller_symbol']}"
                    if key in visited_callers:
                        continue
                    visited_callers.add(key)

                    is_entry = self._is_entrypoint(tr["caller_file"], tr["caller_symbol"])
                    is_tst = self._is_test_file(tr["caller_file"])

                    indirect_caller = AffectedCaller(
                        file_path=tr["caller_file"],
                        symbol_name=tr["caller_symbol"],
                        line=tr["line"],
                        depth=current_depth,
                        confidence=tr.get("confidence", "high"),
                        call_expr=tr.get("raw_expr", f"{caller_name}()"),
                        is_entrypoint=is_entry,
                        is_test=is_tst,
                    )
                    indirect_callers.append(indirect_caller)
                    if not is_tst:
                        next_layer.append(tr["caller_symbol"])

            trace_logs.append(
                f"Depth {current_depth} discovered {len(next_layer)} transitive caller symbols."
            )
            current_layer = next_layer

        # 4. Dependent Files via Import Graph
        dependent_files_set: Set[str] = set()
        for caller in direct_callers + indirect_callers:
            dependent_files_set.add(caller.file_path)

        if resolved_file:
            mod_slug = resolved_file.replace("/", ".").replace("\\", ".")
            if mod_slug.endswith(".py"):
                mod_slug = mod_slug[:-3]
            short_mod = mod_slug.split(".")[-1]

            for file_path, imports in self.codebase_index.import_graph.items():
                for imp in imports:
                    if imp == mod_slug or imp.startswith(f"{mod_slug}.") or imp == short_mod:
                        dependent_files_set.add(file_path)

        # Remove the target file itself from dependent files
        if resolved_file in dependent_files_set:
            dependent_files_set.remove(resolved_file)

        dependent_files = sorted(list(dependent_files_set))
        trace_logs.append(f"Identified {len(dependent_files)} total dependent files.")

        # 5. Affected Test Files
        affected_tests_set: Set[str] = set()
        for f in dependent_files:
            if self._is_test_file(f):
                affected_tests_set.add(f)

        for caller in direct_callers + indirect_callers:
            if caller.is_test:
                affected_tests_set.add(caller.file_path)

        # Also scan test files in repo that import target module or mention symbol
        for f in self.codebase_index.file_list:
            if self._is_test_file(f):
                f_chunks = self.codebase_index.get_file_chunks(f)
                for chunk in f_chunks:
                    if short_target in chunk.calls or short_target in chunk.code:
                        affected_tests_set.add(f)
                        break

        affected_tests = sorted(list(affected_tests_set))
        trace_logs.append(f"Identified {len(affected_tests)} affected test suites.")

        # 6. Affected Entrypoints
        affected_entrypoints_set: Set[str] = set()
        for caller in direct_callers + indirect_callers:
            if caller.is_entrypoint:
                affected_entrypoints_set.add(f"{caller.file_path}:{caller.symbol_name}")

        affected_entrypoints = sorted(list(affected_entrypoints_set))

        # 7. Calculate Blast Radius Score and Risk Level
        # Base score starts with counts
        score = 0
        score += len(direct_callers) * 18
        score += len(indirect_callers) * 8
        score += len(affected_entrypoints) * 20

        # Test coverage adjustment
        if not affected_tests and (direct_callers or indirect_callers):
            score += 25  # High risk due to missing tests
        elif affected_tests:
            score = max(5, score - 10)  # Tests provide a safety net

        blast_radius_score = min(100, max(5, score))

        if blast_radius_score >= 65:
            risk_level = "High"
        elif blast_radius_score >= 30:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        # 8. Calculate Confidence Score
        confidence = 0.92
        all_callers = direct_callers + indirect_callers
        unresolved_callers = [c for c in all_callers if c.confidence == "unresolved"]
        if unresolved_callers:
            confidence -= min(0.40, len(unresolved_callers) * 0.12)

        if not all_callers and dependent_files:
            confidence = 0.75  # Inferred solely through module imports
        elif not all_callers and not dependent_files:
            confidence = 0.50  # Isolated symbol or dynamic caller unknown

        confidence_score = max(0.20, min(1.0, confidence))

        # 9. Generate Mermaid Diagram
        mermaid_lines = ["graph TD"]
        target_node_id = "Target"
        target_display = f"{short_target}" if not resolved_file else f"{short_target}\\n({resolved_file})"
        mermaid_lines.append(f'    {target_node_id}["Target: {target_display}"]:::targetStyle')

        caller_node_map: Dict[str, str] = {}
        for idx, dc in enumerate(direct_callers, 1):
            dc_id = f"DC{idx}"
            caller_node_map[f"{dc.file_path}:{dc.symbol_name}"] = dc_id
            style_cls = "testStyle" if dc.is_test else ("entryStyle" if dc.is_entrypoint else "callerStyle")
            mermaid_lines.append(f'    {dc_id}["{dc.symbol_name}\\n{dc.file_path}:{dc.line}"]:::{style_cls}')
            mermaid_lines.append(f'    {dc_id} -->|calls| {target_node_id}')

        for idx, ic in enumerate(indirect_callers, 1):
            ic_id = f"IC{idx}"
            style_cls = "testStyle" if ic.is_test else ("entryStyle" if ic.is_entrypoint else "callerStyle")
            mermaid_lines.append(f'    {ic_id}["{ic.symbol_name}\\n{ic.file_path}:{ic.line}"]:::{style_cls}')
            # Connect to its parent caller if mapped
            parent_connected = False
            for parent_key, parent_id in caller_node_map.items():
                if ic.call_expr and parent_key.split(":")[-1] in ic.call_expr:
                    mermaid_lines.append(f'    {ic_id} -->|indirect| {parent_id}')
                    parent_connected = True
                    break
            if not parent_connected and direct_callers:
                mermaid_lines.append(f'    {ic_id} -.->|depth {ic.depth}| DC1')

        mermaid_lines.append("    classDef targetStyle fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1;")
        mermaid_lines.append("    classDef callerStyle fill:#f1f5f9,stroke:#64748b,stroke-width:1px,color:#334155;")
        mermaid_lines.append("    classDef entryStyle fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;")
        mermaid_lines.append("    classDef testStyle fill:#dcfce7,stroke:#16a34a,stroke-width:1px,color:#15803d;")
        mermaid_diagram = "\n".join(mermaid_lines)

        # 10. Generate Safe Change Recommendations
        recommendations: List[str] = []
        if affected_tests:
            recommendations.append(
                f"Execute existing test suites before and after modifying '{short_target}': "
                + ", ".join([f"`{t}`" for t in affected_tests[:4]])
            )
        else:
            recommendations.append(
                f"Caution: No automated test files currently cover '{short_target}'. "
                "Write unit tests verifying its contract before refactoring."
            )

        if affected_entrypoints:
            recommendations.append(
                f"Verify outward API response models for exposed entrypoints: "
                + ", ".join([f"`{e}`" for e in affected_entrypoints[:3]])
            )

        if direct_callers:
            direct_names = [f"`{c.symbol_name}` ({c.file_path})" for c in direct_callers[:4]]
            recommendations.append(
                f"Preserve parameter signature backwards-compatibility; {len(direct_callers)} "
                f"direct callers depend on it: {', '.join(direct_names)}."
            )

        # 11. Summary
        summary = (
            f"Change Impact Analysis for `{short_target}`: Risk level is {risk_level} "
            f"(Blast Radius Score: {blast_radius_score}/100, Confidence: {int(confidence_score * 100)}%). "
            f"Modifying this symbol directly impacts {len(direct_callers)} caller(s) "
            f"and indirectly impacts {len(indirect_callers)} transitive caller(s) across {len(dependent_files)} file(s). "
            f"{len(affected_tests)} test suite(s) and {len(affected_entrypoints)} public entrypoint(s) are in scope."
        )

        trace_logs.append("ChangeImpactAgent analysis complete.")

        return ChangeImpactResult(
            target_symbol=target_symbol,
            target_file=resolved_file,
            risk_level=risk_level,
            confidence_score=confidence_score,
            blast_radius_score=blast_radius_score,
            direct_callers=direct_callers,
            indirect_callers=indirect_callers,
            dependent_files=dependent_files,
            affected_tests=affected_tests,
            affected_entrypoints=affected_entrypoints,
            mermaid_diagram=mermaid_diagram,
            recommendations=recommendations,
            summary=summary,
            trace=trace_logs,
        )
