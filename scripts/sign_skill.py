"""Sign skill files with the library key, so they get the "Verified" badge (maintainers only).

    python scripts/sign_skill.py skills/grocery.skill.md [more files ...]

Reads the Ed25519 seed from SKILL_LIBRARY_SIGNING_KEY (environment or the repo-root .env, never committed). Writes a
`signature: "ed25519:<base64>"` line as the last line of each file's frontmatter, replacing any old one. The
signature covers the skill's sha256 (the file without that line), so any later edit makes it unverified again.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _seed() -> str:
    seed = os.environ.get("SKILL_LIBRARY_SIGNING_KEY", "")
    env = ROOT / ".env"
    if not seed and env.exists():
        m = re.search(r"^SKILL_LIBRARY_SIGNING_KEY=([0-9a-fA-F]{64})\s*$", env.read_text(encoding="utf-8"), re.M)
        seed = m.group(1) if m else ""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", seed):
        sys.exit("sign_skill: set SKILL_LIBRARY_SIGNING_KEY (64 hex characters) in the environment or .env")
    return seed


def sign_file(path: Path, seed: str) -> str:
    from app.packs import library_key
    from app.packs.skill import SIGNATURE_LINE, normalize, parse_skill, skill_content

    text = normalize(path.read_bytes())
    content, front, _ = skill_content(text)
    sha = parse_skill(content).sha256  # refuses to sign a skill that does not compile
    start = text.index(front)
    unsigned_front = SIGNATURE_LINE.sub("", front)
    signed = (text[:start] + unsigned_front + f'signature: "{library_key.sign(sha, seed)}"\n'
              + text[start + len(front):])
    skill = parse_skill(signed)
    assert skill.verified and skill.sha256 == sha, "signature did not verify against LIBRARY_PUBLIC_KEY"
    path.write_text(signed, encoding="utf-8", newline="\n")
    return sha


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    seed = _seed()
    for name in argv:
        print(f"signed {name}  sha256 {sign_file(Path(name), seed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
