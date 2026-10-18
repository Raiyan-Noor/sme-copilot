"""`make dev`: FastAPI on :8000 with reload, plus Next.js on :3000 once frontend/package.json exists.

Run with the backend venv's Python. Ctrl+C stops both. Next.js only reads .env files in frontend/, so the
NEXT_PUBLIC_* values from the root .env are passed to it here; no other .env value (no secret) is.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def public_env() -> dict[str, str]:
    """NEXT_PUBLIC_* lines from the root .env; real environment variables win."""
    found = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.startswith("NEXT_PUBLIC_"):
                found[key] = value.strip().strip("\"'")
    return {**os.environ, **{k: v for k, v in found.items() if k not in os.environ}}


def main() -> int:
    procs = [subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
         "--reload", "--reload-dir", "app"],
        cwd=ROOT / "backend",
    )]
    if (FRONTEND / "package.json").exists():
        npm = shutil.which("npm")
        if npm is None:
            print("npm not found; starting backend only.")
        else:
            procs.append(subprocess.Popen([npm, "run", "dev", "--", "--port", "3000"], cwd=FRONTEND,
                                          env=public_env()))
    try:
        return procs[0].wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    sys.exit(main())
