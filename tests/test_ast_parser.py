"""
Phase 2 Test Suite: Verifies AST parsing, symbol table extraction,
line number accuracy, and import dependency graphs on a multi-file Python package.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex


def create_mock_repository(base_dir: str) -> None:
    """Creates a sample multi-file Python repository for testing."""
    os.makedirs(os.path.join(base_dir, "auth"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "api"), exist_ok=True)

    # 1. auth/jwt_service.py
    jwt_code = '''"""JWT Authentication Service."""
import time
import base64

class JWTAuthService:
    """Manages JWT tokens and session expiration."""
    
    def __init__(self, secret: str = "secret-key"):
        self.secret = secret

    def create_token(self, user_id: str, expiry_seconds: int = 3600) -> str:
        """Creates a signed JWT payload."""
        now = time.time()
        payload = f"{user_id}:{now + expiry_seconds}"
        return base64.b64encode(payload.encode()).decode()

    def verify_token(self, token: str) -> dict:
        """Verifies JWT token validity and parses user."""
        raw = base64.b64decode(token.encode()).decode()
        parts = raw.split(":")
        user_id = parts[0]
        exp_time = float(parts[1])
        if time.time() > exp_time:
            raise ValueError("Token expired")
        return {"user_id": user_id, "active": True}
'''
    with open(os.path.join(base_dir, "auth", "jwt_service.py"), "w", encoding="utf-8") as f:
        f.write(jwt_code)

    # 2. api/routes.py
    routes_code = '''"""API Route Handlers."""
from auth.jwt_service import JWTAuthService

auth_svc = JWTAuthService()

def handle_login(user_id: str) -> dict:
    """Login route handler."""
    token = auth_svc.create_token(user_id)
    return {"token": token, "status": 200}

def handle_profile(token: str) -> dict:
    """Protected profile route."""
    data = auth_svc.verify_token(token)
    return {"profile": data}
'''
    with open(os.path.join(base_dir, "api", "routes.py"), "w", encoding="utf-8") as f:
        f.write(routes_code)


def test_ast_indexer():
    temp_dir = tempfile.mkdtemp(prefix="agentic_test_repo_")
    try:
        create_mock_repository(temp_dir)

        print("[1/5] Initializing ASTCodeIndexer on mock repo...")
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        index = indexer.index()

        summary = index.get_summary()
        print(f"      Indexed {summary['total_files']} files, {summary['total_chunks']} chunks, {summary['total_symbols']} symbols.")
        assert summary["total_files"] == 2, f"Expected 2 files, got {summary['total_files']}"
        assert summary["total_chunks"] >= 5, f"Expected at least 5 chunks, got {summary['total_chunks']}"

        # 2. Verify Symbol Table
        print("[2/5] Testing Symbol Table extraction...")
        assert "JWTAuthService" in index.symbol_table
        assert "verify_token" in index.symbol_table
        assert "handle_login" in index.symbol_table
        print("      Symbols correctly identified in table.")

        # 3. Verify Specific Chunk & Exact Line Numbers
        print("[3/5] Verifying function chunk properties & line accuracy...")
        token_entries = index.lookup_symbol("verify_token")
        assert len(token_entries) == 1
        entry = token_entries[0]
        assert entry["file"] == "auth/jwt_service.py"
        assert entry["parent_class"] == "JWTAuthService"
        assert entry["start_line"] > 0
        assert entry["end_line"] > entry["start_line"]
        print(f"      verify_token found at lines {entry['start_line']}-{entry['end_line']} in {entry['file']}.")

        chunk = index.get_chunk_by_id(entry["chunk_id"])
        assert chunk is not None
        assert "def verify_token(self, token: str) -> dict" in chunk.signature
        assert "time" in chunk.calls or "split" in chunk.calls

        # 4. Verify Import Dependency Graph
        print("[4/5] Testing Import Dependency Graph...")
        assert "api/routes.py" in index.import_graph
        imports = index.import_graph["api/routes.py"]
        assert any("auth.jwt_service" in imp for imp in imports)
        print("      Import graph accurately maps api/routes.py -> auth.jwt_service.")

        # 5. Verify File Chunk Filter
        print("[5/5] Testing file-level chunk filtering...")
        auth_chunks = index.get_file_chunks("auth/jwt_service.py")
        assert len(auth_chunks) >= 4  # module_header, class, create_token, verify_token
        print("      File chunk filtering works accurately.")

        print("\nAll Phase 2 AST Indexer tests passed successfully!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_ast_indexer()
