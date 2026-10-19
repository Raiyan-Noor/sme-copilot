"""`make validate-skill FILE=path/to/my.skill.md`: check a skill the way the app does on upload, offline.

Prints the badge, the sha256 and what the skill asks and watches, or every error found. Exit code 0 if valid.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv: list[str]) -> int:
    from app.packs.loader import builtin_skills
    from app.packs.skill import SkillError, parse_skill

    if len(argv) != 1:
        print("usage: make validate-skill FILE=path/to/my.skill.md")
        return 2
    path = Path(argv[0])
    try:
        skill = parse_skill(path.read_bytes())
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 2
    except SkillError as e:
        print(f"INVALID  {path.name}: {len(e.errors)} problem(s)")
        for m in e.errors:
            print(f"  - {m}")
        return 1
    builtin = {s.sha256 for s in builtin_skills().values()}
    if skill.pack.id in builtin_skills() and skill.sha256 not in builtin:
        print(f"INVALID  {path.name}: id {skill.pack.id!r} belongs to a built-in skill; give your skill its own id")
        return 1
    p = skill.authored
    badge = "Verified (signed by the library key)" if skill.verified else "Community, unverified"
    print(f"VALID    {path.name}\n  id {p.id} v{p.version}: {p.display_name}\n  badge   {badge}\n  sha256  {skill.sha256}")
    print(f"  asks    {len(p.data_needs)} uploads: {', '.join(n.id for n in p.data_needs) or '-'}")
    print(f"          {len(p.advisor_questions)} questions: {', '.join(q.id for q in p.advisor_questions) or '-'}")
    print(f"  watches {len(p.leak_detectors)} detectors: {', '.join(d.detector for d in p.leak_detectors)}")
    print(f"          {len(p.kpis)} KPIs: {', '.join(k.id for k in p.kpis)}")
    for n in skill.notices:
        print(f"  notice  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
