"""Branding check, run by `make test`. Branding lives in exactly three places (CLAUDE.md, Conventions):

  frontend/styles/theme.css     colors, radii, fonts as semantic CSS variables
  frontend/config/app.ts        APP_NAME, APP_TAGLINE
  frontend/components/brand/    <Logo /> and the logo asset only it renders

Everywhere else in the frontend this fails on: hex/rgb/hsl color literals, Tailwind's built-in palette classes
(e.g. `bg-red-500`, `text-white`: colors that bypass the theme), the codename in UI text, and direct references to a
logo asset. The backend must not reference the frontend's branding files at all.
Passes trivially until the frontend exists.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend" / "app"

ALLOWED = (FRONTEND / "styles" / "theme.css", FRONTEND / "config" / "app.ts")
ALLOWED_DIRS = (FRONTEND / "components" / "brand",)
SCANNED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".mdx", ".html"}
SKIP_DIRS = {"node_modules", ".next", "out", "build", "dist", "public"}
# Config files that legitimately carry the codename (package name) or no UI text.
SKIP_FILES = {"package.json", "package-lock.json", "next.config.ts", "next.config.js", "next.config.mjs",
              "tailwind.config.ts", "postcss.config.mjs", "next-env.d.ts"}

_PALETTE = ("slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|"
            "violet|purple|fuchsia|pink|rose")
_COLOR_UTILS = ("bg|text|border(?:-[trblxyse])?|ring|ring-offset|outline|fill|stroke|from|via|to|shadow|divide|"
                "accent|caret|decoration|placeholder")

RULES = [
    ("color literal", re.compile(r"#[0-9a-fA-F]{3,8}\b(?![-\w])|\b(?:rgba?|hsla?|oklch|oklab)\(\s*[\d.]")),
    ("Tailwind palette color", re.compile(
        rf"(?<![\w-])(?:{_COLOR_UTILS})-(?:(?:{_PALETTE})-\d{{2,3}}|white|black)(?![\w-])")),
    ("codename in UI", re.compile(r"sme[-_ ]?copilot", re.IGNORECASE)),
    ("logo asset outside <Logo />", re.compile(r"logo[\w-]*\.(?:svg|png|jpe?g|webp|gif)", re.IGNORECASE)),
]
BACKEND_RULE = re.compile(r"theme\.css|APP_NAME|APP_TAGLINE|components/brand")


def _frontend_files():
    if not FRONTEND.exists():
        return
    for path in FRONTEND.rglob("*"):
        rel_parts = set(path.relative_to(FRONTEND).parts)
        if (not path.is_file() or rel_parts & SKIP_DIRS or path.name in SKIP_FILES
                or path.suffix not in SCANNED_SUFFIXES or path in ALLOWED
                or any(d in path.parents for d in ALLOWED_DIRS)):
            continue
        yield path


def check() -> list[str]:
    problems = []
    for path in _frontend_files():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for name, rx in RULES:
                if rx.search(line):
                    problems.append(f"{path.relative_to(ROOT)}:{n}: {name}: {line.strip()[:100]}")
    for path in BACKEND.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BACKEND_RULE.search(line):
                problems.append(f"{path.relative_to(ROOT)}:{n}: backend refers to branding: {line.strip()[:100]}")
    return problems


def main() -> int:
    problems = check()
    for p in problems:
        print(p)
    if problems:
        print(f"Branding check FAILED: {len(problems)} problem(s). Move branding into the three allowed places.")
        return 1
    print("Branding check passed." + ("" if FRONTEND.exists() else " (no frontend yet)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
