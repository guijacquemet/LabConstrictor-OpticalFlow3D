"""Run every check of the OpticalFlow3D Profiler code: Ruff, code-size rules and pytest.

Usage: ``python tools/check_profiler.py [--rules]`` from the repository root. ``--rules``
runs only Ruff and the code-size rules (no tests).

The size rules follow the MorphoBricks code standards (spec §9) that Ruff does not check:
at most 600 lines per module and 60 executable lines (docstring excluded) per function.
Ruff (src/ruff.toml) checks complexity <= 15, <= 8 parameters, annotations and docstrings.
The unchanged upstream copy in ``_upstream/calc_flow.py`` is exempt.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "opticalflow3d_profiler"
TESTS = ROOT / "tests" / "profiler"
EXEMPT = {PACKAGE / "_upstream" / "calc_flow.py"}
MAX_FILE_LINES = 600
MAX_FUNCTION_LINES = 60


def executable_lines(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> int:
    """Count non-blank, non-comment lines of a function body after its docstring."""
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return 0
    end = max(stmt.end_lineno or stmt.lineno for stmt in body)
    code = (line.strip() for line in lines[body[0].lineno - 1 : end])
    return sum(1 for line in code if line and not line.startswith("#"))


def size_violations() -> list[str]:
    """Return every module and function over the size limits."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) > MAX_FILE_LINES:
            found.append(f"{path.relative_to(ROOT)}: {len(lines)} lines > {MAX_FILE_LINES}")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                count = executable_lines(node, lines)
                if count > MAX_FUNCTION_LINES:
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.name}: {count} executable lines > {MAX_FUNCTION_LINES}")
    return found


def main() -> int:
    """Run the checks and return the process exit code."""
    targets = [str(PACKAGE.parent), str(TESTS), str(Path(__file__))]
    steps = [[sys.executable, "-m", "ruff", "check", *targets], [sys.executable, "-m", "ruff", "format", "--check", *targets]]
    failed = False
    for step in steps:
        failed |= subprocess.run(step, cwd=ROOT, check=False).returncode != 0
    violations = size_violations()
    for line in violations:
        print(line)
    failed |= bool(violations)
    if "--rules" not in sys.argv:
        tests = [sys.executable, "-m", "pytest", str(TESTS), "-q"]
        failed |= subprocess.run(tests, cwd=ROOT, check=False).returncode != 0
    print("FAILED" if failed else "All checks passed.")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
