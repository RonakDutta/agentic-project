"""
AST-based Codebase Indexer for Python Repositories.
Implements the program-structure indexing approach inspired by AutoCodeRover (ISSTA 2024).
Parses source files at semantic function, class, and module boundaries rather than arbitrary character splits.
Builds exact Symbol Tables, Line Ranges, Import Dependency Graphs, and Alias-Aware Call Graphs.
"""

import ast
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class CodeChunk:
    id: str
    file_path: str
    chunk_type: str  # 'function', 'class', 'module_header'
    name: str
    signature: str
    start_line: int
    end_line: int
    code: str
    docstring: str = ""
    calls: List[str] = field(default_factory=list)
    call_details: List[Dict[str, Any]] = field(default_factory=list)
    parent_class: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CodebaseIndex:
    repo_path: str
    chunks: List[CodeChunk] = field(default_factory=list)
    symbol_table: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    import_graph: Dict[str, List[str]] = field(default_factory=dict)
    file_list: List[str] = field(default_factory=list)
    callers_map: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    call_graph: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def lookup_symbol(self, name: str) -> List[Dict[str, Any]]:
        """Finds definition locations for a given symbol name."""
        return self.symbol_table.get(name, [])

    def get_file_chunks(self, file_path: str) -> List[CodeChunk]:
        """Returns all chunks belonging to a specific file."""
        norm_path = file_path.replace("\\", "/")
        return [c for c in self.chunks if c.file_path == norm_path]

    def get_chunk_by_id(self, chunk_id: str) -> Optional[CodeChunk]:
        """Finds a chunk by its unique ID."""
        for c in self.chunks:
            if c.id == chunk_id:
                return c
        return None

    def get_callers(self, symbol_name: str) -> List[Dict[str, Any]]:
        """
        Returns all known callers of a given symbol name across the repository.
        Matches qualified name, short name, or class method.
        """
        short_name = symbol_name.split(".")[-1]
        callers = list(self.callers_map.get(symbol_name, []))
        if not callers and short_name != symbol_name:
            callers = list(self.callers_map.get(short_name, []))
        return callers

    def get_callees(self, symbol_name: str) -> List[Dict[str, Any]]:
        """
        Returns all outgoing function calls made by a given symbol.
        """
        callees = []
        for chunk in self.chunks:
            if chunk.name == symbol_name or chunk.id.endswith(f":{symbol_name}"):
                callees.extend(chunk.call_details)
        return callees

    def get_summary(self) -> Dict[str, Any]:
        """Returns an overview summary of the indexed repository."""
        return {
            "repo_path": self.repo_path,
            "total_files": len(self.file_list),
            "total_chunks": len(self.chunks),
            "total_symbols": len(self.symbol_table),
            "files": self.file_list,
        }


class ASTCodeIndexer:
    def __init__(self, repo_path: str, max_files: int = 300):
        self.repo_path = os.path.abspath(repo_path)
        self.max_files = max_files
        self.ignore_dirs: Set[str] = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "node_modules",
            ".pytest_cache",
            ".idea",
            ".vscode",
            "dist",
            "build",
            "site-packages",
            ".chroma",
        }
        # If indexing a parent repository, ignore embedded sample_repo test fixture
        if os.path.basename(self.repo_path) != "sample_repo":
            self.ignore_dirs.add("sample_repo")

    def index(self) -> CodebaseIndex:
        """
        Walks the repository, parses all Python files into an AST,
        and constructs semantic chunks, symbol tables, import graphs,
        and alias-aware caller/callee graphs.
        """
        codebase_index = CodebaseIndex(repo_path=self.repo_path)
        py_files = self._collect_python_files()
        codebase_index.file_list = [
            os.path.relpath(f, self.repo_path).replace("\\", "/") for f in py_files
        ]

        for file_abs in py_files:
            rel_path = os.path.relpath(file_abs, self.repo_path).replace("\\", "/")
            try:
                with open(file_abs, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                lines = content.splitlines(keepends=True)
                tree = ast.parse(content, filename=rel_path)

                file_chunks, imports = self._parse_ast_tree(tree, rel_path, lines)
                codebase_index.chunks.extend(file_chunks)
                codebase_index.import_graph[rel_path] = imports

                # Populate Symbol Table
                for chunk in file_chunks:
                    if chunk.chunk_type in ("function", "class"):
                        entry = {
                            "name": chunk.name,
                            "type": chunk.chunk_type,
                            "file": chunk.file_path,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "signature": chunk.signature,
                            "parent_class": chunk.parent_class,
                            "chunk_id": chunk.id,
                        }
                        codebase_index.symbol_table.setdefault(chunk.name, []).append(entry)

            except Exception as e:
                # Malformed syntax or non-python file fallback
                print(f"[AST Indexer] Notice: Skipped '{rel_path}' due to parse error: {e}")

        # Populate Bi-directional Callers Map & Call Graph
        for chunk in codebase_index.chunks:
            if chunk.chunk_type == "function" and chunk.call_details:
                codebase_index.call_graph[chunk.id] = chunk.call_details
                for call_info in chunk.call_details:
                    target = call_info["target"]
                    short_target = target.split(".")[-1]
                    caller_entry = {
                        "caller_file": chunk.file_path,
                        "caller_symbol": chunk.name,
                        "caller_chunk_id": chunk.id,
                        "line": call_info["line"],
                        "raw_expr": call_info["raw_expr"],
                        "confidence": call_info["confidence"],
                    }
                    codebase_index.callers_map.setdefault(target, []).append(caller_entry)
                    if short_target != target:
                        codebase_index.callers_map.setdefault(short_target, []).append(caller_entry)

        return codebase_index

    def _collect_python_files(self) -> List[str]:
        collected = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [
                d for d in dirs if d not in self.ignore_dirs and not d.startswith(".")
            ]
            for file in files:
                if file.endswith(".py"):
                    collected.append(os.path.join(root, file))
                    if len(collected) >= self.max_files:
                        return collected
        return collected

    def _parse_ast_tree(
        self, tree: ast.AST, rel_path: str, lines: List[str]
    ) -> tuple[List[CodeChunk], List[str]]:
        chunks: List[CodeChunk] = []
        imports: List[str] = []
        import_aliases: Dict[str, str] = {}

        # Extract module-level docstring and imports with alias resolution
        module_doc = ast.get_docstring(tree) or ""
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    alias_name = alias.asname or alias.name
                    import_aliases[alias_name] = alias.name
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    full_target = f"{mod}.{alias.name}" if mod else alias.name
                    alias_name = alias.asname or alias.name
                    import_aliases[alias_name] = full_target
                    imports.append(full_target)

        # Module Header / Overview Chunk
        if lines:
            header_line_count = min(25, len(lines))
            header_code = "".join(lines[:header_line_count])
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}:module_header",
                    file_path=rel_path,
                    chunk_type="module_header",
                    name=os.path.basename(rel_path),
                    signature=f"module {rel_path}",
                    start_line=1,
                    end_line=header_line_count,
                    code=header_code,
                    docstring=module_doc,
                    calls=[],
                )
            )

        # Classes and standalone functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                chunks.extend(self._process_class_node(node, rel_path, lines, import_aliases))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(
                    self._process_func_node(node, rel_path, lines, parent_class=None, import_aliases=import_aliases)
                )

        return chunks, imports

    def _process_class_node(
        self, node: ast.ClassDef, rel_path: str, lines: List[str], import_aliases: Dict[str, str]
    ) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        start = node.lineno
        end = getattr(node, "end_lineno", start + 5)
        class_code = "".join(lines[start - 1 : end])
        doc = ast.get_docstring(node) or ""

        # Construct class signature
        bases = [ast.unparse(b) for b in node.bases]
        bases_str = f"({', '.join(bases)})" if bases else ""
        class_sig = f"class {node.name}{bases_str}"

        chunks.append(
            CodeChunk(
                id=f"{rel_path}:{node.name}",
                file_path=rel_path,
                chunk_type="class",
                name=node.name,
                signature=class_sig,
                start_line=start,
                end_line=end,
                code=class_code[:2000],  # Concise class definition overview
                docstring=doc,
                calls=[],
                parent_class=None,
            )
        )

        # Process methods inside the class as individual chunks
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(
                    self._process_func_node(item, rel_path, lines, parent_class=node.name, import_aliases=import_aliases)
                )

        return chunks

    def _process_func_node(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        rel_path: str,
        lines: List[str],
        parent_class: Optional[str] = None,
        import_aliases: Optional[Dict[str, str]] = None,
    ) -> CodeChunk:
        aliases = import_aliases or {}
        start = node.lineno
        end = getattr(node, "end_lineno", start + 5)
        func_code = "".join(lines[start - 1 : end])
        doc = ast.get_docstring(node) or ""

        calls_set: Set[str] = set()
        call_details: List[Dict[str, Any]] = []

        # Alias-aware call extraction and target resolution
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                call_line = getattr(subnode, "lineno", start)
                if isinstance(subnode.func, ast.Name):
                    name_id = subnode.func.id
                    calls_set.add(name_id)
                    if name_id in aliases:
                        target = aliases[name_id]
                        conf = "high"
                    else:
                        target = name_id
                        conf = "high" if name_id in ("print", "len", "range", "dict", "list", "set", "int", "str") else "medium"

                    call_details.append({
                        "target": target,
                        "raw_expr": name_id,
                        "line": call_line,
                        "confidence": conf,
                    })

                elif isinstance(subnode.func, ast.Attribute):
                    attr_name = subnode.func.attr
                    calls_set.add(attr_name)
                    raw_expr = ast.unparse(subnode.func) if hasattr(ast, "unparse") else attr_name

                    if isinstance(subnode.func.value, ast.Name):
                        val_id = subnode.func.value.id
                        if val_id in aliases:
                            target = f"{aliases[val_id]}.{attr_name}"
                            conf = "high"
                        elif val_id == "self" and parent_class:
                            target = f"{parent_class}.{attr_name}"
                            conf = "high"
                        else:
                            target = f"{val_id}.{attr_name}"
                            conf = "unresolved"
                    else:
                        target = f"<dynamic>.{attr_name}"
                        conf = "unresolved"

                    call_details.append({
                        "target": target,
                        "raw_expr": raw_expr,
                        "line": call_line,
                        "confidence": conf,
                    })

        # Build clean signature
        args_list = []
        for a in node.args.args:
            arg_str = a.arg
            if a.annotation:
                arg_str += f": {ast.unparse(a.annotation)}"
            args_list.append(arg_str)

        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        ret_ann = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        sig = f"{prefix}{node.name}({', '.join(args_list)}){ret_ann}"

        qual_name = f"{parent_class}.{node.name}" if parent_class else node.name
        chunk_id = f"{rel_path}:{qual_name}"

        return CodeChunk(
            id=chunk_id,
            file_path=rel_path,
            chunk_type="function",
            name=node.name,
            signature=sig,
            start_line=start,
            end_line=end,
            code=func_code,
            docstring=doc,
            calls=sorted(list(calls_set)),
            call_details=call_details,
            parent_class=parent_class,
        )
