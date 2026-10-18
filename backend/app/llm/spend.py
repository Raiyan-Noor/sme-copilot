"""Running LLM spend per provider, in integer micro-USD, from usage returned by each call.

Persisted to a small JSON file (when a path is given) so the LLM_BUDGET_USD cap survives restarts: we have one
pool of credit across every dev session, not one per process. Replayed calls cost nothing and are not added.
"""

import json
import threading
from pathlib import Path


class SpendTracker:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._spent: dict[str, int] = {}
        if self.path and self.path.is_file():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._spent = {str(k): int(v) for k, v in raw.get("spent_microusd", {}).items()}

    def spent(self, provider: str) -> int:
        with self._lock:
            return self._spent.get(provider, 0)

    def add(self, provider: str, microusd: int) -> int:
        """Add a call's cost and return the provider's new total."""
        if microusd < 0:
            raise ValueError("cost cannot be negative")
        with self._lock:
            total = self._spent.get(provider, 0) + microusd
            self._spent[provider] = total
            self._save()
            return total

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"spent_microusd": self._spent}, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
