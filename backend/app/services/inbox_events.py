"""Live inbox events for the owner's Inbox screen: each message's progress through the pipeline and changes to the
Gmail connection, streamed over SSE (api/inbox.py).

In-process and in-memory: a short ring buffer per business with a global sequence number, so a client that
reconnects can ask for everything after the last event it saw. Events go only to the owner's UI, never to the
planner (invariant 2); the audit log remains the record of what happened (invariant 7).
"""

import threading
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel

KEEP = 200

Stage = Literal["received", "extracting", "checking", "accepted", "flagged", "held", "failed"]


class InboxEvent(BaseModel):
    seq: int
    kind: Literal["message", "connection"]
    email_id: str | None = None
    source: str | None = None  # mailbox (sandbox) | gmail | upload
    stage: Stage | None = None
    sender: str | None = None  # owner display only
    subject: str | None = None  # owner display only
    flags: list[str] = []
    connection: dict[str, Any] | None = None  # kind="connection": the new GmailStatus


class InboxEvents:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._by_business: dict[str, deque[InboxEvent]] = {}

    def publish(self, business_id: str, **fields: Any) -> InboxEvent:
        with self._lock:
            self._seq += 1
            event = InboxEvent(seq=self._seq, **fields)
            self._by_business.setdefault(business_id, deque(maxlen=KEEP)).append(event)
            return event

    def latest(self) -> int:
        with self._lock:
            return self._seq

    def since(self, business_id: str, seq: int) -> list[InboxEvent]:
        with self._lock:
            return [e for e in self._by_business.get(business_id, ()) if e.seq > seq]
