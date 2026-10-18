"""All LLM calls go through llm/adapter.py: no other backend module may import openai (CLAUDE.md, Stack)."""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ADAPTER = BACKEND / "app" / "llm" / "adapter.py"


def _imports_openai(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "openai" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and not node.level and (node.module or "").split(".")[0] == "openai":
            return True
    return False


def test_only_the_adapter_imports_openai():
    offenders = [
        str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
        if p != ADAPTER and _imports_openai(p)
    ]
    assert offenders == []
    assert _imports_openai(ADAPTER)
