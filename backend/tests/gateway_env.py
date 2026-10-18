"""Gateway test helpers: a tenant directory, a movable simulated clock, an owner key pair held only by
the test (standing in for the browser), and helpers to sign payloads and register standing mandates."""

from datetime import date, timedelta
from pathlib import Path

from nacl.signing import SigningKey

from app.audit import AuditLog
from app.clock import SimClock
from app.gateway import ArgValue, Gateway, ProposedAction, SignedPayload, StandingTerms

TODAY = date(2026, 10, 18)


class Owner:
    """The owner's browser: holds the private key and signs canonical payloads."""

    def __init__(self, seed: bytes = b"\x01" * 32):
        self.key = SigningKey(seed)
        self.public_key = self.key.verify_key.encode().hex()

    def sign(self, payload: SignedPayload) -> str:
        return self.key.sign(payload.message()).signature.hex()


class Env:
    def __init__(self, tmp_path: Path):
        self.clock = SimClock(TODAY)
        self.audit = AuditLog(tmp_path / "audit.jsonl", self.clock)
        self.gateway = Gateway.for_tenant(tmp_path, self.audit, self.clock)
        self.owner = Owner()
        self.gateway.enroll_owner_key(self.owner.public_key)
        self._nonce = 0

    def nonce(self) -> str:
        self._nonce += 1
        return f"client-nonce-{self._nonce:08d}"

    def standing_payload(self, action: str, terms: StandingTerms, days: int = 30, nonce: str | None = None):
        return SignedPayload(action=action, args_hash=terms.hash(), nonce=nonce or self.nonce(),
                             expiry=self.clock.today() + timedelta(days=days))

    def grant(self, action: str, max_amount_minor: int, allowlist: tuple[str, ...], days: int = 30):
        terms = StandingTerms(max_amount_minor=max_amount_minor, allowlist=allowlist)
        payload = self.standing_payload(action, terms, days)
        result = self.gateway.register_standing_mandate(payload, terms, self.owner.sign(payload),
                                                        self.owner.public_key)
        assert result.accepted, result.rule
        return result.mandate

    def approve(self, decision, owner: Owner | None = None, **kwargs):
        owner = owner or self.owner
        request = decision.approval
        return self.gateway.approve(request.approval_id, owner.sign(request.payload), owner.public_key, **kwargs)

    @property
    def bank_ops(self) -> list[dict]:
        return self.gateway.executors.bank.operations()

    @property
    def outbox(self) -> list[dict]:
        return self.gateway.executors.mailbox.outbox()


def action(tool: str, untrusted: tuple[str, ...] = (), **args) -> ProposedAction:
    return ProposedAction(tool=tool, args={
        k: ArgValue(value=v, provenance="untrusted" if k in untrusted else "trusted") for k, v in args.items()
    })


def reminder(customer_id: str = "cus_sunrise", amount: int = 38_650, invoice_id: str = "INV-1", **kw):
    return action("send_invoice_reminder", customer_id=customer_id, invoice_id=invoice_id,
                  invoice_amount_minor=amount, **kw)


def bill(payee_id: str = "pay_citygrid", amount: int = 34_000, bill_id: str = "bill_power", **kw):
    return action("pay_recurring_bill", payee_id=payee_id, bill_id=bill_id, amount_minor=amount, **kw)

