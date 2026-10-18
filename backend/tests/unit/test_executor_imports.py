"""Invariant 1: nothing outside app/gateway (and app/executor itself) may import app.executor.

Scans every Python file in the backend, including tests, for `import app.executor...`, `from app.executor ...`,
`from app import executor`, relative imports that reach it, and dynamic imports by string. Tests reach the
sandbox only through a Gateway instance.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
ALLOWED_DIRS = (APP / "gateway", APP / "executor")
DYNAMIC = re.compile(r"""["']app\.executor""")


def _module_of(path: Path) -> list[str]:
    return list(path.relative_to(BACKEND).with_suffix("").parts)


def _imports_executor(path: Path, as_module: list[str] | None = None) -> list[str]:
    source = path.read_text(encoding="utf-8")
    hits = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if a.name == "app.executor" or a.name.startswith("app.executor.")]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # resolve relative imports against this file's package
                base = (as_module or _module_of(path))[: -node.level]
                module = ".".join(base + ([module] if module else []))
            names = [a.name for a in node.names]
            if module == "app.executor" or module.startswith("app.executor."):
                hits.append(module)
            elif module == "app" and "executor" in names:
                hits.append("app.executor")
    if DYNAMIC.search(source) and path != Path(__file__).resolve():
        hits.append("dynamic string reference to app.executor")
    return hits


def test_only_gateway_imports_executor():
    offenders = {}
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or any(path.is_relative_to(d) for d in ALLOWED_DIRS):
            continue
        hits = _imports_executor(path)
        if hits:
            offenders[str(path.relative_to(BACKEND))] = hits
    assert offenders == {}, f"invariant 1: only app.gateway may import app.executor: {offenders}"


def test_the_guard_catches_a_violation(tmp_path):
    probe = tmp_path / "probe.py"
    cases = {
        "from app.executor.sandbox_bank import SandboxBank\n": ["app.executor.sandbox_bank"],
        "import app.executor.sandbox_bank\n": ["app.executor.sandbox_bank"],
        "from app import executor\n": ["app.executor"],
        "from .executor import sandbox_bank\n": ["app.executor"],
        "import importlib\nimportlib.import_module('app.executor.sandbox_bank')\n": [
            "dynamic string reference to app.executor"
        ],
    }
    for source, expected in cases.items():
        probe.write_text(source, encoding="utf-8")
        assert _imports_executor(probe, ["app", "probe"]) == expected, source


def test_gateway_dispatch_is_the_importer():
    assert _imports_executor(APP / "gateway" / "dispatch.py")
