"""Process-wide runtime state behind the API: the simulated clock, the audit log, one Gateway per business and a
cache of computed facts.

Built lazily on first use, so importing the app has no side effects (no files created, nothing seeded). On first
use it creates data_dir, restores the simulated clock, opens the audit log (configured as the default for
`app.audit.append`) and loads any seed businesses that have no tenant yet.

- Clock: one SimClock for the whole app (clock.py is the only time source). Its start date and fast-forward offset
  persist in data_dir/clock.json, so a restart does not rewind the demo. It only moves forward.
- Audit (invariant 7): one hash-chained log, data_dir/audit.jsonl; every mutation through the API appends to it.
- Gateways (invariants 1, 6): one per business, state under data_dir/<business_id>/. Every action goes through one.
- Anchoring (invariant 9): one AnchorService over the audit log, data_dir/_anchoring/anchors.sqlite; subscribed to every
  append so it can cut a batch every ANCHOR_BATCH_SIZE entries. Sends run in the background.
- Inbox events: an in-memory feed of each message's progress through the pipeline, streamed to the Inbox screen.
- Gmail (services/gmail.py): OAuth connections, the background poller and the mail route the gateway sends with.
- Payments (services/payments.py): the SandboxPay connection and the payment route the gateway pays through.
- Fact cache: keyed by business, active pack, simulated date and ledger version, so a page refresh does not
  recompute (or re-log) the same facts. Each fresh computation is logged with a hash of every fact it produced.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import app.audit as audit_module
from app.anchoring import AnchorService, Chain, create_service
from app.audit import AuditLog
from app.clock import SimClock
from app.config import Settings
from app.gateway import Gateway
from app.llm.adapter import LLMAdapter
from app.services.businesses import bootstrap_from_seed, business_info, open_business, seed_profiles
from app.services.finance import Computed, compute, ledger_version, load_inputs, records_version
from app.services.inbox_events import InboxEvents

FACT_CACHE_SIZE = 16


class ClockNotConfigured(RuntimeError):
    """No persisted clock, no SIM_START and no seed data to take the start date from."""


class Runtime:
    def __init__(self, settings: Settings, anchor_chain: Chain | None = None):
        self.settings = settings
        self._anchor_chain = anchor_chain
        self._anchors: AnchorService | None = None
        self._lock = threading.RLock()
        self._ready = False
        self._clock: SimClock | None = None
        self._audit: AuditLog | None = None
        self._gateways: dict[str, Gateway] = {}
        self._facts: dict[tuple, Computed] = {}
        self._llm: LLMAdapter | None = None
        self._demo_llm: LLMAdapter | None = None
        self.inbox_events = InboxEvents()
        self._gmail = None
        self._payments = None

    # Setup
    @property
    def data_dir(self) -> Path:
        return self.settings.data_dir

    def ensure_ready(self) -> None:
        with self._lock:
            if self._ready:
                return
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._clock = self._load_clock()
            self._audit = AuditLog(self.data_dir / "audit.jsonl", self._clock)
            audit_module.configure(self._audit)
            if self.settings.seed_dir.is_dir():
                bootstrap_from_seed(self.settings.seed_dir, self.data_dir, self._audit)
            self._anchors = create_service(self.settings, self._audit, self.data_dir, self._anchor_chain)
            self._ready = True

    @property
    def clock(self) -> SimClock:
        self.ensure_ready()
        return self._clock

    @property
    def audit(self) -> AuditLog:
        self.ensure_ready()
        return self._audit

    @property
    def anchors(self) -> AnchorService:
        self.ensure_ready()
        return self._anchors

    @property
    def llm(self) -> LLMAdapter:
        """The one LLM adapter (OpenAI, Gemini fallback, record/replay), logging to this runtime's audit log."""
        with self._lock:
            if self._llm is None:
                self._llm = LLMAdapter.from_settings(self.settings, self.audit)
            return self._llm

    @property
    def demo_llm(self) -> LLMAdapter:
        """The demo console's adapter: always live (record/replay off), so console mail is read by a real model in
        real time. Same budget cap, spend counter and Gemini fallback as the main adapter."""
        with self._lock:
            if self._demo_llm is None:
                live = self.settings.model_copy(update={"llm_replay": "off"})
                self._demo_llm = LLMAdapter.from_settings(live, self.audit)
            return self._demo_llm

    @property
    def gmail(self):
        """The Gmail connection service (services/gmail.py), built on first use."""
        from app.services.gmail import GmailService  # it imports services.inbox, which imports this module

        with self._lock:
            if self._gmail is None:
                self._gmail = GmailService(self)
            return self._gmail

    @property
    def payments(self):
        """The Payments service (services/payments.py): SandboxPay connection, pay requests, settlement."""
        from app.services.payments import PaymentsService  # it imports services.inbox, which imports this module

        with self._lock:
            if self._payments is None:
                self._payments = PaymentsService(self)
            return self._payments

    # Clock
    def _clock_file(self) -> Path:
        return self.data_dir / "clock.json"

    def _load_clock(self) -> SimClock:
        path = self._clock_file()
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            clock = SimClock(date.fromisoformat(state["start"]), int(state["offset_days"]),
                             state.get("day_began_at"))
            if clock.day_began_at is None:  # a clock saved before it kept a time of day: the day begins now
                clock.now()
                self._save_clock(clock)
            return clock
        start = self.settings.sim_start
        if start is None:
            seed_days = [p["sim_today"] for p in seed_profiles(self.settings.seed_dir)] if (
                self.settings.seed_dir.is_dir()) else []
            if not seed_days:
                raise ClockNotConfigured("set SIM_START or run `make seed`")
            start = date.fromisoformat(max(seed_days))
        clock = SimClock(start)
        clock.now()  # the first simulated day begins at 07:00 now
        self._save_clock(clock)
        return clock

    def _save_clock(self, clock: SimClock) -> None:
        state = {"start": clock.start.isoformat(), "offset_days": clock.offset_days,
                 "day_began_at": clock.day_began_at}
        tmp = self._clock_file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(self._clock_file())

    def advance_clock(self, days: int) -> date:
        """Fast-forward the simulated clock (never backwards), persist it and log it."""
        with self._lock:
            clock = self.clock
            before = clock.today()
            today = clock.advance(days)
            self._save_clock(clock)
            self.audit.append("clock.advanced", {"from": before.isoformat(), "to": today.isoformat(), "days": days})
            return today

    # Businesses
    @contextmanager
    def business(self, business_id: str) -> Iterator:
        """An open tenant connection. Raises TenantError for a bad or unknown ID."""
        self.ensure_ready()
        conn = open_business(self.data_dir, business_id)
        try:
            yield conn
        finally:
            conn.close()

    def gateway(self, business_id: str) -> Gateway:
        """The business's gateway (the only path to executors). Raises TenantError for an unknown business."""
        with self.business(business_id):
            pass
        with self._lock:
            gw = self._gateways.get(business_id)
            if gw is None:
                gw = Gateway.for_tenant(self.data_dir / business_id, self.audit, self.clock,
                                        mail=self.gmail.mail_route(business_id),
                                        payments=self.payments.route(business_id))
                self.payments.attach(business_id, gw)
                self._gateways[business_id] = gw
            return gw

    def forget(self, business_id: str) -> None:
        """Drop a deleted business's gateway and cached facts (onboarding reset)."""
        with self._lock:
            gw = self._gateways.pop(business_id, None)
            if gw is not None:
                gw.close()
            for key in [k for k in self._facts if k[0] == business_id]:
                self._facts.pop(key)

    # Facts
    def facts(self, business_id: str) -> Computed:
        """Every fact for the business as of the simulated today, computed once per ledger version."""
        with self.business(business_id) as conn, self._lock:
            key = (business_id, business_info(conn).pack_id, self.clock.today(), ledger_version(conn),
                   records_version(conn, self.settings.seed_dir))
            cached = self._facts.get(key)
            if cached is not None:
                return cached
            inputs = load_inputs(conn, self.settings.seed_dir, self.settings.holiday_calendar)
            computed = compute(inputs, self.clock)
            self.audit.append("engine.facts_computed", {
                "business_id": business_id,
                "pack": inputs.pack.ref,
                "as_of": key[2].isoformat(),
                "facts": len(computed.store),
                "facts_sha256": computed.facts_sha256,
            })
            if len(self._facts) >= FACT_CACHE_SIZE:
                self._facts.pop(next(iter(self._facts)))
            self._facts[key] = computed
            return computed
