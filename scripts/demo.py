"""`make demo`: stop any stale servers, then start the API (:8000), SandboxPay (:8100) and Next.js (:3000) in demo mode.

Demo mode turns on the live demo console: DEMO_MODE=true mounts its API routes and NEXT_PUBLIC_DEMO_MODE=true shows
its screen. Both are set here for this run only, whatever .env says.

Stale servers: on Windows, uvicorn's --reload workers (`multiprocessing.spawn`) inherit the listening socket and can
keep answering with old code after their reloader is gone, so before starting we stop every process listening on
the three ports, every uvicorn process for this app or SandboxPay, and every spawn worker left behind by one.
Ctrl+C stops everything, as with `make dev`.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

PORTS = (8000, 8100, 3000)
URLS = [("App", "http://localhost:3000"), ("Demo console", "http://localhost:3000/demo-console"),
        ("API docs", "http://localhost:8000/docs"), ("SandboxPay", "http://localhost:8100")]

WINDOWS_FIND = r"""
$ports = @({ports})
$listen = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object {{ $ports -contains $_.LocalPort }} | ForEach-Object {{ $_.OwningProcess }})
$procs = Get-CimInstance Win32_Process
$servers = @($procs | Where-Object {{ $_.CommandLine -match 'uvicorn.*(app\.main:app|sandboxpay\.main)' }} |
  ForEach-Object {{ $_.ProcessId }})
$parents = $listen + $servers
$alive = @($procs | ForEach-Object {{ $_.ProcessId }})
$workers = @($procs | Where-Object {{ $_.CommandLine -match 'multiprocessing\.spawn' -and
  (($parents -contains $_.ParentProcessId) -or -not ($alive -contains $_.ParentProcessId)) }} |
  ForEach-Object {{ $_.ProcessId }})
($listen + $servers + $workers) | Where-Object {{ $_ -gt 0 -and $_ -ne $PID }} | Sort-Object -Unique
"""


def stale_pids() -> list[int]:
    if os.name == "nt":
        script = WINDOWS_FIND.format(ports=",".join(map(str, PORTS)))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    else:
        cmds = [["lsof", "-ti", f"tcp:{p}", "-sTCP:LISTEN"] for p in PORTS]
        cmds += [["pgrep", "-f", r"uvicorn.*(app\.main:app|sandboxpay\.main)"]]
        out = "\n".join(subprocess.run(c, capture_output=True, text=True).stdout for c in cmds)
    own = {os.getpid(), os.getppid()}
    return sorted({int(x) for x in out.split() if x.strip().isdigit()} - own)


def stop_stale() -> None:
    pids = stale_pids()
    for pid in pids:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    if pids:
        print(f"make demo: stopped {len(pids)} stale server process(es): {', '.join(map(str, pids))}")
    deadline = time.time() + 10
    while any(port_open(p) for p in PORTS) and time.time() < deadline:
        time.sleep(0.3)
    busy = [p for p in PORTS if port_open(p)]
    if busy:
        print(f"make demo: port(s) {busy} still in use; stop whatever holds them and retry.")
        sys.exit(1)


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def announce() -> None:
    deadline = time.time() + 180
    while time.time() < deadline and not all(port_open(p) for p in PORTS):
        time.sleep(1)
    up = all(port_open(p) for p in PORTS)
    print("\n" + ("make demo: ready (demo mode on)" if up else "make demo: still starting; check the logs above"))
    width = max(len(n) for n, _ in URLS)
    for name, url in URLS:
        print(f"  {name.ljust(width)}  {url}")
    print("  Reset rehearsal businesses: make demo-reset\n", flush=True)


def main() -> int:
    stop_stale()
    os.environ["DEMO_MODE"] = "true"
    os.environ["NEXT_PUBLIC_DEMO_MODE"] = "true"
    threading.Thread(target=announce, daemon=True).start()
    return dev.main()


if __name__ == "__main__":
    sys.exit(main())
