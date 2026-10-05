"""
Repository Map Generator for Compact Codebase Overviews.
Inspired by Aider and CodeContextKit repository mapping principles.
Generates an ultra-compact, token-efficient structural map showing:
- File tree hierarchy
- Key modules and exported class/function symbols
- Primary entry points (CLI, FastAPI/Flask apps, main functions)
- Inter-module import dependencies
- Detected frameworks and libraries
"""

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Set
from indexer.ast_parser import CodebaseIndex, CodeChunk


@dataclass
class RepoMap:
    repo_name: str
    total_files: int
    total_symbols: int
    file_tree: List[str]
    modules: Dict[str, List[str]]
    entry_points: List[Dict[str, Any]]
    frameworks: List[str]
    dependencies: Dict[str, List[str]]
    compact_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "total_files": self.total_files,
            "total_symbols": self.total_symbols,
            "file_tree": self.file_tree,
            "entry_points": self.entry_points,
            "frameworks": self.frameworks,
            "dependencies": self.dependencies,
            "compact_text": self.compact_text,
        }


class RepoMapGenerator:
    """
    Constructs a concise repository map suitable for injecting into LLM reasoning context
    without blowing the token budget.
    """

    KNOWN_FRAMEWORKS = {
        "fastapi": "FastAPI",
        "flask": "Flask",
        "django": "Django",
        "pydantic": "Pydantic",
        "torch": "PyTorch",
        "tensorflow": "TensorFlow",
        "sqlalchemy": "SQLAlchemy",
        "celery": "Celery",
        "pytest": "PyTest",
        "requests": "Requests",
        "httpx": "HTTPX",
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "groq": "Groq",
    }

    def generate(self, codebase_index: CodebaseIndex) -> RepoMap:
        repo_name = os.path.basename(os.path.normpath(codebase_index.repo_path)) or "repository"
        file_list = sorted(codebase_index.file_list)

        modules_map: Dict[str, List[str]] = {}
        detected_frameworks: Set[str] = set()
        entry_points: List[Dict[str, Any]] = []

        # 1. Detect Frameworks from Import Graph
        for _, imports in codebase_index.import_graph.items():
            for imp in imports:
                root_pkg = imp.split(".")[0].lower()
                if root_pkg in self.KNOWN_FRAMEWORKS:
                    detected_frameworks.add(self.KNOWN_FRAMEWORKS[root_pkg])

        # 2. Extract Key Symbols per Module and Detect Entry Points
        for file_path in file_list:
            chunks = codebase_index.get_file_chunks(file_path)
            symbols_in_file: List[str] = []

            for chunk in chunks:
                if chunk.chunk_type in ("function", "class"):
                    sig = chunk.signature or f"{chunk.chunk_type} {chunk.name}"
                    symbols_in_file.append(sig)

                # Entry point heuristics
                is_entry = False
                entry_type = ""
                if "__main__" in chunk.code:
                    is_entry = True
                    entry_type = "main_block"
                elif "FastAPI(" in chunk.code or "Flask(" in chunk.code:
                    is_entry = True
                    entry_type = "web_app"
                elif chunk.name in ("main", "run", "cli", "start_app"):
                    is_entry = True
                    entry_type = "cli_or_runner"

                if is_entry:
                    entry_points.append({
                        "file": file_path,
                        "symbol": chunk.name,
                        "type": entry_type,
                        "line": chunk.start_line,
                    })

            modules_map[file_path] = symbols_in_file

        # 3. Build Formatted Compact Map Text
        compact_lines: List[str] = []
        frameworks_list = sorted(list(detected_frameworks))
        fw_badge = f" (Frameworks: {', '.join(frameworks_list)})" if frameworks_list else ""
        compact_lines.append(f"Repository: {repo_name}/{fw_badge}")
        compact_lines.append("=" * 60)

        for file_path in file_list:
            entry_tag = ""
            for ep in entry_points:
                if ep["file"] == file_path:
                    entry_tag = f" [ENTRYPOINT: {ep['type']}]"
                    break

            compact_lines.append(f"- {file_path}{entry_tag}")
            symbols = modules_map.get(file_path, [])
            for sym in symbols[:6]:  # Limit to 6 prominent symbols per file for compact budget
                compact_lines.append(f"    - {sym}")
            if len(symbols) > 6:
                compact_lines.append(f"    - ... (+{len(symbols) - 6} more symbols)")

        compact_text = "\n".join(compact_lines)

        return RepoMap(
            repo_name=repo_name,
            total_files=len(file_list),
            total_symbols=len(codebase_index.chunks),
            file_tree=file_list,
            modules=modules_map,
            entry_points=entry_points,
            frameworks=frameworks_list,
            dependencies=codebase_index.import_graph,
            compact_text=compact_text,
        )


# Global singleton instance
repo_map_generator = RepoMapGenerator()
