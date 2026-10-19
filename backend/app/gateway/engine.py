"""The gateway: decides every proposed action (invariants 1, 3, 5, 6, 7).

`propose()` returns exactly one of:
- `executed`: a T2 action inside an active, signed standing mandate and every policy.yaml ceiling;
- `pending_approval`: a T3 action, or any action with an untrusted-provenance argument (invariant 3), waiting for
  the owner to sign the exact payload; the response carries the payload to sign;
- `denied`: with the rule that fired.

`approve()` executes a pending action only after verifying, in order: the signer's key is enrolled, the Ed25519
signature covers the stored payload, the payload has not expired, any out-of-band call is confirmed, and the nonce
is unused. The nonce is consumed before execution, so the same signature can never run twice.

Unknown tools, system tools and anything T4-like are denied and logged as violations (invariant 5). Every decision,
stored mandate and execution is appended to the audit log (invariant 7).

Emails (`send_email`, T3) are drafts first: `save_email_draft` stores the exact text content-addressed and logs it,
the owner may revise it (`revise_email` replaces the pending approval with a new one for the new text, so a signature
for the old text can never send the new one), and `decline` closes an approval without executing it.
"""

import secrets
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.audit import AuditLog
from app.clock import Clock
from app.connections.gmail import MailRoute
from app.connections.sandboxpay import PaymentRoute
from app.gateway.dispatch import ACTION_ARGS, Executors, check_args
from app.gateway.emails import MAX_BODY, MAX_SUBJECT, AddedRecipient, build_draft
from app.gateway.mandate import MandateRecord, SignedPayload, StandingTerms, args_hash, verify_signature
from app.gateway.policy import Policy, Tier, load_policy
from app.gateway.store import Approval, GatewayStore

Provenance = Literal["trusted", "untrusted"]
Status = Literal["executed", "pending_approval", "denied"]


class ArgValue(BaseModel):
    """One action argument with where its value came from. Provenance is required: there is no default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str | int | bool | None
    provenance: Provenance


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, ArgValue] = {}

    def values(self) -> dict[str, Any]:
        return {k: v.value for k, v in self.args.items()}

    def untrusted(self) -> list[str]:
        return sorted(k for k, v in self.args.items() if v.provenance == "untrusted")


class ApprovalRequest(BaseModel):
    """What the owner is asked to sign. `payload` is signed as canonical JSON; `args` are shown to the owner."""

    approval_id: str
    payload: SignedPayload
    args: dict[str, Any]
    reasons: list[str]
    requires_out_of_band_call_script: bool = False


class Decision(BaseModel):
    status: Status
    tool: str
    tier: Tier | None = None
    effective_tier: Tier | None = None
    rule: str | None = None
    approval: ApprovalRequest | None = None
    mandate_id: int | None = None
    result: dict[str, Any] | None = None


class MandateResult(BaseModel):
    accepted: bool
    rule: str | None = None
    mandate: MandateRecord | None = None


class Gateway:
    def __init__(
        self,
        store: GatewayStore,
        audit: AuditLog,
        clock: Clock,
        policy: Policy | None = None,
        data_dir: Path | None = None,
        mail: MailRoute | None = None,
        payments: PaymentRoute | None = None,
    ):
        self.store = store
        self.audit = audit
        self.clock = clock
        self.policy = policy or load_policy()
        self.data_dir = data_dir  # the tenant directory, or None for an in-memory gateway
        self.executors = Executors(data_dir, mail=mail, payments=payments)
        self.loan_drafts = self.executors.loan_drafts
        # Told about every execution after it is logged: (tool, args, result, mandate_id). The Payments service
        # tracks settlement from here. A listener cannot change the decision; it runs after the action.
        self.listeners: list[Callable[[str, dict, dict, int], None]] = []
        assert set(self.policy.t2) | set(self.policy.t3) == set(ACTION_ARGS), "policy.yaml and dispatch disagree"

    def close(self) -> None:
        """Release the business's state files (onboarding deletes a business)."""
        self.store.close()
        self.executors.bank.close()
        self.executors.mailbox.close()

    @classmethod
    def for_tenant(cls, tenant_dir: Path, audit: AuditLog, clock: Clock, policy: Policy | None = None,
                   mail: MailRoute | None = None, payments: PaymentRoute | None = None) -> "Gateway":
        """`mail`: how approved emails reach contacts (Gmail when connected, else the sandbox outbox).
        `payments`: how approved payments reach the payment provider (SandboxPay), and the payees' accounts on file."""
        return cls(GatewayStore(tenant_dir / "gateway.sqlite"), audit, clock, policy, tenant_dir, mail, payments)

    # Owner keys
    def enroll_owner_key(self, public_key_hex: str) -> None:
        """Store an owner's Ed25519 public key. The private key never reaches the server (invariant 6)."""
        self.store.enroll_key(public_key_hex, self.clock.today())
        self.audit.append("gateway.key_enrolled", {"public_key": public_key_hex.lower()})

    # Proposals
    def propose(self, action: ProposedAction) -> Decision:
        tool, today = action.tool, self.clock.today()
        tier = self.policy.tier_of(tool)

        if tier is None:
            rule = "system_tool" if tool in self.policy.system_tools else "unknown_tool"
            self.audit.append("gateway.violation", {"tool": tool, "rule": rule})
            return self._log(action, Decision(status="denied", tool=tool, rule=rule))
        if tier == "T1":
            return self._log(action, Decision(status="denied", tool=tool, tier=tier, rule="t1_is_not_an_action"))

        bad = check_args(tool, action.values())
        untrusted = action.untrusted()
        if not bad and untrusted and tier == "T3" and self.policy.t3[tool].deny_untrusted_args:
            bad = "untrusted_args_denied"  # content from an email can never make the assistant send one
        bad = bad or self.executors.precheck(tool, action.values())
        if bad:
            return self._log(action, Decision(status="denied", tool=tool, tier=tier, rule=bad))

        if untrusted or tier == "T3":
            reasons = [f"untrusted_provenance:{','.join(untrusted)}"] if untrusted else ["tier_T3"]
            return self._log(action, self._request_approval(action, tier, reasons))

        # T2, every argument trusted.
        rule, mandate = self._check_t2(tool, action.values())
        if rule:
            return self._log(action, Decision(status="denied", tool=tool, tier=tier, effective_tier=tier, rule=rule))
        result = self._execute(tool, action.values(), mandate.id)
        return self._log(action, Decision(
            status="executed", tool=tool, tier=tier, effective_tier=tier, mandate_id=mandate.id, result=result))

    def _check_t2(self, tool: str, args: dict) -> tuple[str | None, MandateRecord | None]:
        rule = self.policy.t2[tool]
        today = self.clock.today()
        mandate = self.store.active_standing(tool, today)
        if mandate is None:
            return "no_standing_mandate", None
        terms = mandate.terms
        if args[rule.allowlist_arg] not in terms.allowlist:
            return f"not_allowlisted:{rule.allowlist_arg}", None
        amount = args[rule.amount_arg]
        if amount > rule.max_amount_minor:
            return "over_policy_cap", None
        if amount > terms.max_amount_minor:
            return "over_mandate_cap", None
        if rule.frequency:
            key = str(args[rule.frequency.per])
            since = today - timedelta(days=rule.frequency.window_days - 1)
            if self.store.executions_since(tool, key, since) >= rule.frequency.max:
                return "frequency_cap", None
        return None, mandate

    def payee_account(self, payee_id: str) -> str | None:
        """Read-only: the account a payment to this payee would go to now (a signed payee change, else the contact
        book's). The Payments service puts it in the args the owner signs, so a later change is caught."""
        return self.executors.bank.account_for(payee_id)

    def mandate_covers(self, action: ProposedAction) -> bool:
        """Read-only: would this exact T2 action run under the active standing mandate right now? Nothing is logged
        or executed; `propose()` still decides. Untrusted arguments are never covered (invariant 3)."""
        if self.policy.tier_of(action.tool) != "T2" or action.untrusted():
            return False
        values = action.values()
        if check_args(action.tool, values) or self.executors.precheck(action.tool, values):
            return False
        rule, _ = self._check_t2(action.tool, values)
        return rule is None

    def _request_approval(self, action: ProposedAction, tier: Tier, reasons: list[str]) -> Decision:
        today = self.clock.today()
        values = action.values()
        payload = SignedPayload(
            action=action.tool,
            args_hash=args_hash(values),
            nonce=secrets.token_hex(16),
            expiry=today + timedelta(days=self.policy.approval_ttl_days),
        )
        approval = Approval(f"apr_{secrets.token_hex(8)}", action.tool, values, payload, reasons, "pending")
        self.store.add_approval(approval, today)
        t3 = self.policy.t3.get(action.tool)
        request = ApprovalRequest(
            approval_id=approval.id,
            payload=payload,
            args=values,
            reasons=reasons,
            # A payee change always needs the call, including when escalated from untrusted content.
            requires_out_of_band_call_script=bool(t3 and t3.requires_out_of_band_call_script),
        )
        return Decision(status="pending_approval", tool=action.tool, tier=tier, effective_tier="T3",
                        rule=reasons[0], approval=request)

    # Approvals
    def approve(
        self, approval_id: str, signature_hex: str, public_key_hex: str, out_of_band_confirmed: bool = False
    ) -> Decision:
        """Execute a pending action once the owner has signed its exact payload (invariant 6)."""
        today = self.clock.today()
        approval = self.store.get_approval(approval_id)
        if approval is None:
            return self._log_approval(approval_id, None, Decision(status="denied", tool="", rule="unknown_approval"))
        tool, payload = approval.tool, approval.payload

        def deny(rule: str) -> Decision:
            return self._log_approval(approval_id, payload, Decision(
                status="denied", tool=tool, tier=self.policy.tier_of(tool), effective_tier="T3", rule=rule))

        if not self.store.is_enrolled(public_key_hex):
            return deny("unknown_signer")
        if not verify_signature(payload, signature_hex, public_key_hex):
            return deny("bad_signature")
        if today > payload.expiry:
            return deny("expired")
        t3 = self.policy.t3.get(tool)
        if t3 and t3.requires_out_of_band_call_script and not out_of_band_confirmed:
            return deny("out_of_band_call_required")
        # The draft (or other referent) must still be intact before the signature is spent.
        bad = self.executors.precheck(tool, approval.args)
        if bad:
            return deny(bad)
        if not self.store.consume_nonce(payload.nonce, today):
            return deny("replayed_nonce")
        if approval.status != "pending":
            return deny("approval_not_pending")
        # Defense in depth: the stored args must still hash to what the owner signed.
        if args_hash(approval.args) != payload.args_hash:
            return deny("args_hash_mismatch")

        mandate = self._store_mandate("approval", payload, signature_hex, public_key_hex, None)
        self.store.set_approval_status(approval_id, "executed")
        result = self._execute(tool, approval.args, mandate.id)
        return self._log_approval(approval_id, payload, Decision(
            status="executed", tool=tool, tier=self.policy.tier_of(tool), effective_tier="T3",
            mandate_id=mandate.id, result=result))

    def decline(self, approval_id: str) -> bool:
        """The owner declines a pending approval: it can never be signed afterwards. False if it is not pending."""
        approval = self.store.get_approval(approval_id)
        if approval is None or approval.status != "pending":
            return False
        self.store.set_approval_status(approval_id, "declined")
        self.audit.append("gateway.approval_declined", {"approval_id": approval_id, "tool": approval.tool,
                                                        "nonce": approval.payload.nonce})
        return True

    # Emails
    def save_email_draft(self, doc: dict[str, Any]) -> tuple[str, str]:
        """Store a draft email (content-addressed) and log it. The text itself stays in the draft store; the log
        carries its hash, who wrote it and which facts it was rendered from (invariant 7)."""
        draft_id, sha256 = self.executors.email_drafts.save(doc)
        self.audit.append("email.drafted", {
            "draft_id": draft_id, "sha256": sha256, "recipient_id": doc["recipient_id"], "origin": doc["origin"],
            "fact_ids": [f["id"] for f in doc.get("facts", [])], "edited_from": doc.get("edited_from"),
            "subject_chars": len(doc["subject"]), "body_chars": len(doc["body"]),
        })
        return draft_id, sha256

    def email_view(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """What the owner reads before signing a `send_email`: recipient, subject, full body and why. None if the
        draft is missing or altered (the approval cannot execute either)."""
        status, doc, sha256 = self.executors.email_drafts.load(str(args.get("draft_id", "")))
        if status != "ok" or doc is None:
            return None
        recipients = self.executors.recipients
        rcpt = recipients.get(doc["recipient_id"])
        return {
            "draft_id": args["draft_id"], "sha256": sha256, "recipient_id": doc["recipient_id"],
            "recipient_name": rcpt.name if rcpt else "", "recipient_email": rcpt.email if rcpt else None,
            "added_by_owner": recipients.added_by_owner(doc["recipient_id"]), "subject": doc["subject"],
            "body": doc["body"], "reason": doc["reason"], "origin": doc["origin"],
            "edited": bool(doc.get("edited_from")), "about": doc.get("about") or {},
            "fact_ids": [f["id"] for f in doc.get("facts", [])],
        }

    def revise_email(self, approval_id: str, subject: str, body: str) -> Decision:
        """The owner edits a pending email. The new text becomes a new draft and a new approval to sign; the old
        approval is closed, so a signature over the old text can never send the new one (invariant 6). The owner's
        own words are not LLM output, so digits they type are theirs; placeholders are not allowed in an edit."""
        old = self.store.get_approval(approval_id)
        if old is None or old.tool != "send_email" or old.status != "pending":
            return Decision(status="denied", tool="send_email", rule="not_a_pending_email")
        subject, body = subject.strip(), body.strip()
        if not subject or not body or len(subject) > MAX_SUBJECT or len(body) > MAX_BODY:
            return Decision(status="denied", tool="send_email", rule="bad_email_text")
        if "{fact" in (subject + body).lower() or "\n" in subject or "\r" in subject:
            return Decision(status="denied", tool="send_email", rule="bad_email_text")
        status, doc, _ = self.executors.email_drafts.load(str(old.args.get("draft_id", "")))
        if status != "ok" or doc is None:
            return Decision(status="denied", tool="send_email", rule=status)
        new = build_draft(recipient_id=doc["recipient_id"], subject=subject, body=body, reason=doc["reason"],
                          origin=doc["origin"], facts=[], about=doc.get("about"), edited_from=old.args["draft_id"])
        draft_id, _ = self.save_email_draft(new)
        action = ProposedAction(tool="send_email", args={
            "recipient_id": ArgValue(value=doc["recipient_id"], provenance="trusted"),
            "draft_id": ArgValue(value=draft_id, provenance="trusted")})
        bad = self.executors.precheck("send_email", action.values())
        if bad:
            return self._log(action, Decision(status="denied", tool="send_email", tier="T3", rule=bad))
        decision = self._request_approval(action, "T3", old.reasons)
        self.store.set_approval_status(approval_id, "superseded")
        self.audit.append("email.revised", {
            "old_approval_id": approval_id, "new_approval_id": decision.approval.approval_id,
            "old_draft_id": old.args["draft_id"], "new_draft_id": draft_id})
        return self._log(action, decision)

    def add_email_recipient(self, name: str, email: str) -> AddedRecipient:
        """Add an address the contact book does not have. The API demands the address typed twice and an explicit
        confirmation first; the planner has no way here. Raises ValueError for an invalid address."""
        added = self.executors.recipients.add(name, email, self.clock.today())
        self.audit.append("email.recipient_added", {"recipient_id": added.id,
                                                    "domain": added.email.rsplit("@", 1)[-1]})
        return added

    def email_contacts(self) -> list[tuple[str, str, str, str]]:
        """(id, name, kind, email) of everyone that can be emailed: the contact book, then owner-added addresses."""
        return self.executors.recipients.contacts()

    def email_recipient(self, recipient_id: str):
        """The contact (name, email) behind an ID, or None."""
        return self.executors.recipients.get(recipient_id)

    def outbox(self) -> list[dict]:
        """Every email sent or simulated for this business, oldest first (read-only)."""
        return self.executors.mailbox.outbox()

    # Standing mandates
    def register_standing_mandate(
        self, payload: SignedPayload, terms: StandingTerms, signature_hex: str, public_key_hex: str
    ) -> MandateResult:
        """Accept a signed T2 standing mandate. Its terms may lower policy.yaml caps but never raise them."""
        today = self.clock.today()
        rule = self._standing_rule(payload, terms, signature_hex, public_key_hex)
        if rule:
            self.audit.append("gateway.mandate_rejected", {"action": payload.action, "rule": rule,
                                                           "nonce": payload.nonce})
            return MandateResult(accepted=False, rule=rule)
        if not self.store.consume_nonce(payload.nonce, today):
            self.audit.append("gateway.mandate_rejected", {"action": payload.action, "rule": "replayed_nonce",
                                                           "nonce": payload.nonce})
            return MandateResult(accepted=False, rule="replayed_nonce")
        mandate = self._store_mandate("standing", payload, signature_hex, public_key_hex, terms)
        return MandateResult(accepted=True, mandate=mandate)

    def _standing_rule(
        self, payload: SignedPayload, terms: StandingTerms, signature_hex: str, public_key_hex: str
    ) -> str | None:
        today = self.clock.today()
        rule = self.policy.t2.get(payload.action)
        if rule is None:
            return "not_a_t2_tool"
        if payload.args_hash != terms.hash():
            return "args_hash_mismatch"
        if not self.store.is_enrolled(public_key_hex):
            return "unknown_signer"
        if not verify_signature(payload, signature_hex, public_key_hex):
            return "bad_signature"
        if today > payload.expiry:
            return "expired"
        if payload.expiry > today + timedelta(days=self.policy.standing_mandate_max_days):
            return "mandate_too_long"
        if terms.max_amount_minor > rule.max_amount_minor:
            return "raises_policy_cap"
        return None

    # Internals
    def _store_mandate(
        self, kind: str, payload: SignedPayload, signature: str, public_key: str, terms: StandingTerms | None
    ) -> MandateRecord:
        mandate = self.store.add_mandate(kind, payload, signature, public_key.lower(), terms, self.clock.today())
        self.audit.append("gateway.mandate_stored", {
            "mandate_id": mandate.id, "kind": kind, "action": payload.action,
            "expiry": payload.expiry.isoformat(), "record_hash": mandate.record_hash,
        })
        return mandate

    def _execute(self, tool: str, args: dict, mandate_id: int) -> dict:
        today = self.clock.today()
        result = self.executors.run(tool, args, today)
        rule = self.policy.t2.get(tool)
        key = str(args[rule.frequency.per]) if rule and rule.frequency else None
        self.store.record_execution(tool, key, today, mandate_id)
        self.audit.append("executor.executed", {"tool": tool, "mandate_id": mandate_id, "result": result})
        for listener in self.listeners:
            try:
                listener(tool, args, result, mandate_id)
            except Exception as exc:  # noqa: BLE001 - the action already ran; record the bookkeeping failure
                self.audit.append("gateway.listener_failed", {"tool": tool, "error": type(exc).__name__})
        return result

    def _log(self, action: ProposedAction, decision: Decision) -> Decision:
        self.audit.append("gateway.decision", {
            "tool": action.tool,
            "args": action.values(),
            "untrusted_args": action.untrusted(),
            "status": decision.status,
            "tier": decision.tier,
            "effective_tier": decision.effective_tier,
            "rule": decision.rule,
            "approval_id": decision.approval.approval_id if decision.approval else None,
            "mandate_id": decision.mandate_id,
        })
        return decision

    def _log_approval(self, approval_id: str, payload: SignedPayload | None, decision: Decision) -> Decision:
        self.audit.append("gateway.approval", {
            "approval_id": approval_id,
            "tool": decision.tool,
            "nonce": payload.nonce if payload else None,
            "status": decision.status,
            "rule": decision.rule,
            "mandate_id": decision.mandate_id,
        })
        return decision
