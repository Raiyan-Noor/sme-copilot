"""The branding check (scripts/check_branding.py) catches what it claims to, and nothing the skeleton legitimately uses."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_branding.py"
_spec = importlib.util.spec_from_file_location("check_branding", SCRIPT)
check_branding = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_branding)


def _hits(line: str) -> list[str]:
    return [name for name, rx in check_branding.RULES if rx.search(line)]


@pytest.mark.parametrize("line", [
    'style={{ color: "#1a7f37" }}',
    "background: #fff;",
    "fill: rgb(10, 20, 30)",
    "color: rgba(0,0,0,0.5)",
    "border-color: hsl(210 40% 50%)",
    "--x: oklch(0.5 0.1 150);",
    'className="bg-red-500 p-2"',
    'className="text-white"',
    'className="hover:border-emerald-600"',
    'className="ring-black/20"',
])
def test_color_literals_fail(line):
    assert any("color" in hit for hit in _hits(line))


@pytest.mark.parametrize("line", [
    "<title>sme-copilot</title>",
    "Welcome to SME Copilot",
    "sme_copilot dashboard",
])
def test_codename_in_ui_fails(line):
    assert "codename in UI" in _hits(line)


def test_logo_asset_outside_logo_component_fails():
    assert _hits('<img src="/logo-mark.svg" />') == ["logo asset outside <Logo />"]


@pytest.mark.parametrize("line", [
    'className="bg-brand-primary text-text-muted border-border"',
    'className="text-danger bg-surface-muted ring-ring/50"',
    'className="bg-sidebar-primary text-sidebar-primary-foreground"',
    "color: var(--chart-1);",
    '<a href="#main">',
    "rounded-[min(var(--radius-md),10px)]",
    'className="text-sm text-text"',
])
def test_semantic_classes_pass(line):
    assert _hits(line) == []


def test_repo_frontend_passes():
    assert check_branding.check() == []
