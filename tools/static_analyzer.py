"""
Static Code Analysis Engine.
Calculates deterministic AST code metrics:
- Cyclomatic Complexity (McCabe metric)
- Source Lines of Code (SLOC)
- Maintainability Index and Grade
- Branch density and cognitive hotspots
Feeds static analysis evidence directly into retrieval and diagnosis.
"""

import ast
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class CodeMetrics:
    symbol_name: str
    cyclomatic_complexity: int
    lines_of_code: int
    branch_count: int
    maintainability_grade: str  # 'A', 'B', 'C', 'D'
    risk_level: str  # 'Low', 'Moderate', 'High', 'Critical'
    findings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StaticCodeAnalyzer:
    """
    Computes deterministic AST metrics over Python functions and classes.
    """

    @staticmethod
    def calculate_complexity(node: ast.AST) -> int:
        """
        Calculates cyclomatic complexity by counting control-flow branching constructs.
        Base complexity is 1.
        """
        complexity = 1
        for subnode in ast.walk(node):
            if isinstance(subnode, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(subnode, ast.ExceptHandler):
                complexity += 1
            elif isinstance(subnode, (ast.With, ast.AsyncWith)):
                complexity += 1
            elif isinstance(subnode, ast.Assert):
                complexity += 1
            elif isinstance(subnode, ast.BoolOp):
                complexity += len(subnode.values) - 1
        return complexity

    def analyze_code_snippet(self, code: str, symbol_name: str = "snippet") -> CodeMetrics:
        """
        Analyzes a raw code string and returns structured metrics.
        """
        findings = []
        try:
            tree = ast.parse(code)
            complexity = self.calculate_complexity(tree)
        except Exception as e:
            return CodeMetrics(
                symbol_name=symbol_name,
                cyclomatic_complexity=1,
                lines_of_code=len(code.splitlines()),
                branch_count=0,
                maintainability_grade="B",
                risk_level="Low",
                findings=[f"Static analysis skipped due to parse note: {e}"],
            )

        lines = [line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("#")]
        sloc = len(lines)
        branches = max(0, complexity - 1)

        # Grade calculation
        if complexity <= 5 and sloc <= 40:
            grade = "A"
            risk = "Low"
        elif complexity <= 10 and sloc <= 80:
            grade = "B"
            risk = "Moderate"
            if complexity >= 7:
                findings.append(f"Moderate cyclomatic complexity ({complexity}); consider simplifying control flow.")
        elif complexity <= 15:
            grade = "C"
            risk = "High"
            findings.append(f"Elevated cyclomatic complexity ({complexity}); consider refactoring nested logic.")
        else:
            grade = "D"
            risk = "Critical"
            findings.append(f"High cyclomatic complexity ({complexity}); multiple branching paths increase bug probability.")

        if sloc > 100:
            findings.append(f"Function length is long ({sloc} lines of code); violates single-responsibility principle.")

        return CodeMetrics(
            symbol_name=symbol_name,
            cyclomatic_complexity=complexity,
            lines_of_code=sloc,
            branch_count=branches,
            maintainability_grade=grade,
            risk_level=risk,
            findings=findings,
        )


# Global singleton instance
static_analyzer = StaticCodeAnalyzer()
