"""`make setup`: create backend/.venv with Python 3.12, install the backend, and npm install the frontend if present.

Stdlib only, so any Python 3 can run it. It finds a 3.12 interpreter on Windows (py launcher, including
non-PythonCore registrations) and POSIX (python3.12 on PATH), since the system `python` may be a different version.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV = BACKEND / ".venv"
FRONTEND = ROOT / "frontend"
WANT = (3, 12)


def _version(exe: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run([exe, "-c", "import sys; print(*sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = out.stdout.split()
    return (int(parts[0]), int(parts[1])) if out.returncode == 0 and len(parts) == 2 else None


def _candidates() -> list[str]:
    found = [os.environ.get("PYTHON312", ""), sys.executable]
    found += [p for p in (shutil.which("python3.12"), shutil.which("python3"), shutil.which("python")) if p]
    if shutil.which("py"):
        listing = subprocess.run(["py", "-0p"], capture_output=True, text=True).stdout
        # Lines look like: " -V:Astral/CPython3.12.15   C:\...\python.exe"
        found += [m.group(2).strip() for m in re.finditer(r"-V:(\S+)\s+\*?\s*(.+\.exe)", listing)]
    return [c for c in found if c]


def find_python() -> str:
    for exe in _candidates():
        if _version(exe) == WANT:
            return exe
    sys.exit("Python 3.12 not found. Install it, or set PYTHON312 to its path, then re-run make setup.")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*cmd: str | Path, cwd: Path = ROOT) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def main() -> None:
    if not venv_python().exists() or _version(str(venv_python())) != WANT:
        if VENV.exists():
            shutil.rmtree(VENV)
        run(find_python(), "-m", "venv", VENV)
    run(venv_python(), "-m", "pip", "install", "--upgrade", "pip")
    run(venv_python(), "-m", "pip", "install", "-e", ".[dev]", cwd=BACKEND)

    if (FRONTEND / "package.json").exists():
        npm = shutil.which("npm") or sys.exit("npm not found; install Node.js to set up the frontend.")
        run(npm, "install", cwd=FRONTEND)
    else:
        print("No frontend/package.json yet; skipping npm install.")

    if not (ROOT / ".env").exists():
        print("Note: no .env yet. Copy .env.example to .env and set DEMO_PASSCODE before make dev.")


if __name__ == "__main__":
    main()
