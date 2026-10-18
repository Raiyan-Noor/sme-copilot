"""Write-once store of draft loan applications, keyed by their content-derived ID (engine.application).

Gateway state, like the mandate store: the financing service saves drafts here, and the gateway checks that a
`submit_loan_application` proposal names an intact draft for the same product and amount, both when it is proposed
and again just before it executes (invariants 1 and 6). A draft whose bytes no longer hash to its ID is reported
as tampered and never sent. Drafts live in `<tenant>/loan_drafts/<draft_id>.json` (memory only without a tenant).
"""

import json
import re
import threading
from pathlib import Path
from typing import Any, Literal

from app.audit.canonical import canonical_json, sha256_hex
from app.engine.application import draft_id_for

DRAFT_ID = re.compile(r"^lad_[a-p]{24}$")
Lookup = Literal["ok", "unknown_draft", "draft_tampered"]


class LoanDraftStore:
    def __init__(self, folder: Path | None):
        self.folder = folder
        self._memory: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def save(self, draft_id: str, doc: dict[str, Any]) -> str:
        """Store a draft; returns its SHA-256. The ID must be the one derived from the document."""
        data = canonical_json(doc)
        digest = sha256_hex(data)
        if draft_id_for(digest) != draft_id:
            raise ValueError("draft ID does not match the document")
        with self._lock:
            if self.folder is None:
                self._memory.setdefault(draft_id, data)
            else:
                self.folder.mkdir(parents=True, exist_ok=True)
                path = self.folder / f"{draft_id}.json"
                if not path.exists():
                    path.write_bytes(data)
        return digest

    def _bytes(self, draft_id: str) -> bytes | None:
        if not DRAFT_ID.match(draft_id or ""):
            return None
        if self.folder is None:
            return self._memory.get(draft_id)
        path = self.folder / f"{draft_id}.json"
        return path.read_bytes() if path.is_file() else None

    def load(self, draft_id: str) -> tuple[Lookup, dict[str, Any] | None, str | None]:
        """(status, document, sha256). Only an intact draft comes back with its document."""
        data = self._bytes(draft_id)
        if data is None:
            return "unknown_draft", None, None
        digest = sha256_hex(data)
        if draft_id_for(digest) != draft_id:
            return "draft_tampered", None, None
        return "ok", json.loads(data), digest

    def check(self, args: dict[str, Any]) -> str | None:
        """None if `args` name an intact draft for the same product and amount, else the rule that fired."""
        status, doc, _ = self.load(str(args.get("draft_id", "")))
        if status != "ok":
            return status
        if doc["product"]["id"] != args.get("product_id") or doc["amount_minor"] != args.get("amount_minor"):
            return "draft_mismatch"
        return None
