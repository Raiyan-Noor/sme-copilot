"""Conversation state and the per-turn context every planner tool works in.

Invariant 4: each turn gets a fresh FactStore that holds only the facts tools returned to the planner (this turn,
or earlier in the conversation and recomputed now). The Numeric Firewall checks the reply against that store, so
the planner can cite only fact IDs it was actually given, never one it remembers or invents.

Invariant 3: the conversation records which string values arrived from trusted tool results (`trusted_values`).
propose_action marks any argument the planner did not get that way as untrusted, which forces owner approval.
Values from quarantined content (prompt 12) go in `untrusted_values` / `untrusted_fact_ids` and win over trust.
"""

import json
import re
import secrets
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.audit import AuditLog
from app.clock import Clock
from app.firewall.digit_check import is_numeric_char
from app.firewall.fact import Fact
from app.firewall.store import FactStore
from app.gateway import Gateway
from app.quarantine.facts import record_facts
from app.quarantine.store import InboxRecord
from app.services.finance import Computed

CONVERSATION_ID_PATTERN = r"^conv_[a-z]{16}$"
MAX_CONVERSATIONS = 64
TODAY_FACT_ID = "clock.today"


def new_conversation_id() -> str:
    # Letters only, so the ID can never put a digit in front of the planner or the owner.
    return "conv_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(16))


def safe_label(text: str | None, limit: int = 60) -> str:
    """A label the planner may repeat: numeric characters removed, empty brackets and extra spaces dropped.

    Product, customer and category names can contain digits ("Eggs (12)"); the planner would copy them into a
    reply and trip the Numeric Firewall, so labels it sees never carry any.
    """
    s = "".join(" " if is_numeric_char(c) else c for c in (text or ""))
    s = re.sub(r"\(\s*[^\w\s]*\s*\)|\[\s*\]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -_.,/")
    return s[:limit] or "item"


@dataclass
class Conversation:
    """One owner conversation. `messages` excludes the system prompt and firewall-rejected drafts."""

    id: str
    business_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    seen_fact_ids: dict[str, str] = field(default_factory=dict)  # fact ID -> label, in the order first seen
    trusted_values: set[str] = field(default_factory=set)
    untrusted_values: set[str] = field(default_factory=set)
    untrusted_fact_ids: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ConversationStore:
    """In-memory conversations, newest kept. A conversation belongs to one business."""

    def __init__(self, max_size: int = MAX_CONVERSATIONS):
        self._items: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_size

    def get_or_create(self, business_id: str, conversation_id: str | None) -> Conversation:
        with self._lock:
            conv = self._items.get(conversation_id) if conversation_id else None
            if conv is None or conv.business_id != business_id:
                conv = Conversation(new_conversation_id(), business_id)
                self._items[conv.id] = conv
                while len(self._items) > self._max:
                    self._items.popitem(last=False)
            self._items.move_to_end(conv.id)
            return conv


@dataclass(frozen=True)
class Profile:
    business_name: str
    pack_display_name: str
    owner_name: str
    currency: str
    counterparty_names: dict[str, str]  # counterparty ID -> digit-free display name


def load_profile(computed: Computed, seed_dir: Path) -> Profile:
    """Names the planner may use. Comes from the business's own records (seed folder, or the contacts the owner
    confirmed at onboarding), never from untrusted content."""
    info = computed.inputs.info
    owner, names = "the owner", {}
    folder = computed.inputs.records or (seed_dir / info.seed_source if info.seed_source else None)
    if folder and (folder / "counterparties.json").is_file():
        doc = json.loads((folder / "counterparties.json").read_text(encoding="utf-8"))
        owner = safe_label((doc.get("owner") or {}).get("name")) or owner
        for group in doc.values():
            for item in group if isinstance(group, list) else []:
                if isinstance(item, dict) and item.get("id") and item.get("name"):
                    names[str(item["id"])] = safe_label(item["name"])
    return Profile(safe_label(info.name), safe_label(computed.inputs.pack.display_name), owner,
                   info.currency, names)


class TurnContext:
    """Everything one planner turn needs. Tools read facts through `cite`, which is the only way a fact ID
    reaches the planner, and the only way one gets into the turn's FactStore."""

    def __init__(self, *, conversation: Conversation, computed: Computed, clock: Clock, audit: AuditLog,
                 gateway: Gateway, profile: Profile, inbox: Sequence[InboxRecord] = ()):
        self.conversation = conversation
        self.computed = computed
        self.clock = clock
        self.audit = audit
        self.gateway = gateway
        self.profile = profile
        self.store = FactStore()
        self.cited: dict[str, str] = {}  # this turn: fact ID -> label
        # Every fact computed for the business today (services.finance.compute), including the simulated date.
        self.pool: dict[str, Fact] = {f.id: f for f in computed.store}
        # Processed inbox items (typed fields and sentinel reports only, never message text: invariant 2) and
        # their amount/date facts, which are untrusted whenever a tool hands them over (invariant 3).
        self.inbox: list[InboxRecord] = list(inbox)
        for record in self.inbox:
            for fact in record_facts(record, computed.inputs.info.currency):
                self.pool[fact.id] = fact
        # Facts the planner saw earlier in this conversation stay citable if they still exist after a clock move.
        for fact_id in conversation.seen_fact_ids:
            if fact_id in self.pool:
                self.store.add(self.pool[fact_id])
        self.store.add(self.pool[TODAY_FACT_ID])

    @property
    def business_id(self) -> str:
        return self.conversation.business_id

    def has(self, fact_id: str) -> bool:
        return fact_id in self.pool

    def value(self, fact_id: str) -> Any:
        """A fact's machine value, for code-side comparisons only. Never put it in a tool result."""
        fact = self.pool.get(fact_id)
        return fact.value if fact else None

    def cite(self, fact_id: str, label: str) -> str | None:
        """Register a fact for this turn and return its placeholder, or None if the business has no such fact."""
        fact = self.pool.get(fact_id)
        if fact is None:
            return None
        self.store.add(fact)
        label = safe_label(label)
        self.cited.setdefault(fact_id, label)
        self.conversation.seen_fact_ids.setdefault(fact_id, label)
        return "{fact:" + fact_id + "}"

    def trust(self, *values: str | None) -> None:
        """Record IDs a trusted tool result handed the planner (invariant 3: anything else counts as untrusted)."""
        self.conversation.trusted_values.update(v for v in values if v)

    def distrust(self, fact_ids: list[str], *values: str | None) -> None:
        """Record facts and IDs that came from untrusted content; they stay untrusted even if seen elsewhere."""
        self.conversation.untrusted_fact_ids.update(fact_ids)
        self.conversation.untrusted_values.update(v for v in values if v)

    def provenance_of_value(self, value: str) -> str:
        conv = self.conversation
        return "trusted" if value in conv.trusted_values and value not in conv.untrusted_values else "untrusted"

    def provenance_of_fact(self, fact_id: str) -> str:
        return "untrusted" if fact_id in self.conversation.untrusted_fact_ids else "trusted"
