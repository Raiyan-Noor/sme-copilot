"""Render docs/results/redteam.json as Markdown tables for docs/security-self-assessment.md (between the
`<!-- REDTEAM -->` and `<!-- /REDTEAM -->` markers). Every figure is read from the file; nothing is typed by hand
(invariant 8). Run after `make redteam`: `python scripts/redteam_tables.py`.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "results" / "redteam.json"
DOC = ROOT / "docs" / "security-self-assessment.md"
LABELS = {"openai": "OpenAI, dev profile (Terra); what CI replays",
          "openai-demo": "OpenAI, demo profile (Sol planner, Terra extractor)",
          "gemini": "Gemini (the fallback), subset"}


def short(test: str) -> str:
    return test.split("::", 1)[-1]


def render(doc: dict) -> str:
    providers = {k: v for k, v in doc["providers"].items() if v.get("status") == "ran"}
    out = [f"Source: `docs/results/redteam.json`, mode `{doc['mode']}`, commit `{doc['commit']}`.", "",
           "| Recordings | Scope | Attacks blocked | Variants blocked | Live-planner variants | Benign tasks completed |",
           "|---|---|---|---|---|---|"]
    for name, p in providers.items():
        scope = "all red-team and benign suites" if p.get("scope", "full") == "full" else \
            ", ".join(f"`{s.split('/')[-1]}`" for s in p["scope"])
        out.append(f"| {LABELS.get(name, name)} | {scope} | {p['attacks_blocked']}/{p['attacks_run']} | "
                   f"{p['attack_variants_blocked']}/{p['attack_variants_run']} | {p['live_llm_variants']} | "
                   f"{p['tasks_succeeded']}/{p['tasks_run']} |")
    for name, p in doc["providers"].items():
        if p.get("status") != "ran":
            out.append(f"| {LABELS.get(name, name)} | not run: {p.get('reason')} | | | | |")

    main = providers.get("openai")
    if main:
        out += ["", f"### Attacks and the defences that caught them ({LABELS['openai']})", "",
                "Defence layer and rule are what each blocked variant's test reported (`caught_by` in the file).", "",
                "| Attack | Variants blocked | Driven by | Caught by (layer: rule × variants) |", "|---|---|---|---|"]
        for a in main["attacks"]:
            caught = "; ".join(f"{c['layer']}: `{c['rule']}` ×{c['variants']}" for c in a["caught_by"]) or "—"
            blocked = sum(v["blocked"] for v in a["variants"])
            out.append(f"| {a['name']} (`{a['id']}`) | {blocked}/{len(a['variants'])} | "
                       f"{', '.join(a['drivers'])} | {caught} |")

    for name, p in providers.items():
        missed = [(a, v) for a in p["attacks"] for v in a["variants"] if not v["blocked"]]
        failed_tasks = [t for t in p["tasks"] if not t["succeeded"]]
        if not missed and not failed_tasks:
            continue
        out += ["", f"### Failing cases: {LABELS.get(name, name)}", "",
                "A failing test counts as the attack getting through, whatever the cause.", ""]
        for a, v in missed:
            out.append(f"- `{a['id']}`: `{short(v['test'])}`: {v.get('failure', 'failed')}")
        for t in failed_tasks:
            out.append(f"- benign task `{t['task']}`: `{short(t['test'])}`: {t.get('failure', 'failed')}")
    return "\n".join(out)


def main() -> int:
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    text = DOC.read_text(encoding="utf-8")
    block = "<!-- REDTEAM -->\n" + render(doc) + "\n<!-- /REDTEAM -->"
    if "<!-- REDTEAM -->" not in text:
        print("redteam_tables: no <!-- REDTEAM --> marker in the doc")
        return 1
    if "<!-- /REDTEAM -->" in text:
        new = re.sub(r"<!-- REDTEAM -->.*?<!-- /REDTEAM -->", lambda m: block, text, count=1, flags=re.S)
    else:
        new = text.replace("<!-- REDTEAM -->", block, 1)
    DOC.write_text(new, encoding="utf-8", newline="\n")
    print(f"redteam_tables: updated {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
