"""`make dev`: FastAPI on :8000 with reload, plus Next.js on :3000 once frontend/package.json exists.

Run with the backend venv's Python. Ctrl+C stops both.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


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
            procs.append(subprocess.Popen([npm, "run", "dev", "--", "--port", "3000"], cwd=FRONTEND))
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
