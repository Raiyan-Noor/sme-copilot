"""`make reset-demo`: delete every business created by onboarding, so a rehearsal starts from zero.

Seeded businesses (Maya's Corner Store, the fashion shop) are never touched. If the API is running it is asked to do
it (POST /onboarding/reset), so its caches drop the deleted businesses too; otherwise the tenant files are deleted
directly. Either way the deletion is in the audit log.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402


def env(name: str, default: str = "") -> str:
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"')
    return default


def main() -> int:
    api = env("NEXT_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    request = urllib.request.Request(f"{api}/onboarding/reset", method="POST",
                                     headers={"X-Passcode": env("DEMO_PASSCODE")})
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            deleted = json.load(r)["deleted"]
        print(f"reset through the API at {api}: deleted {deleted or 'nothing'}")
        return 0
    except urllib.error.HTTPError as e:
        print(f"the API refused the reset ({e.code}): {e.read().decode(errors='replace')}")
        return 1
    except (urllib.error.URLError, TimeoutError):
        pass
    from app.services.onboarding import reset
    from app.services.runtime import Runtime

    deleted = reset(Runtime(get_settings()))
    print(f"API not running; deleted the files directly: {deleted or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
