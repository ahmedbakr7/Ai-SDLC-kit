"""Example lint and 'typecheck' (stdlib-only stand-ins for ruff and mypy).

    python tools/lint.py          syntax errors, print() in app code
    python tools/lint.py --types  every non-test function in app/ has a return annotation
"""
import ast
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
types = "--types" in sys.argv
problems = []
for f in sorted((root / "app").rglob("*.py")):
    rel = f.relative_to(root).as_posix()
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"), rel)
    except SyntaxError as e:
        problems.append(f"{rel}:{e.lineno}: {e.msg}")
        continue
    for node in ast.walk(tree):
        if types and isinstance(node, ast.FunctionDef) and not f.name.startswith("test_"):
            if node.returns is None:
                problems.append(f"{rel}:{node.lineno}: {node.name}() has no return annotation")
        if not types and isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print":
            problems.append(f"{rel}:{node.lineno}: print() in app code")
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
