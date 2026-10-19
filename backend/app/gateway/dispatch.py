"""The only bridge from gateway decisions to executors (invariant 1).

`ACTION_ARGS` declares each action's required arguments and types; the gateway rejects a proposal whose arguments
do not match before any policy or signature check. `Executors.precheck()` adds per-action checks on the arguments'
referents (a loan application must name an intact draft for the same product and amount); the gateway runs it on
proposal and again just before execution: a payment (`pay_invoice`) is refused if the payee's account on file is no
longer the account the owner approved, or if it came from a Sentinel-flagged email whose call-script check is not
done. An email (`send_email`) is refused if its draft is missing or altered, its recipient is not a known contact
(or one the owner added with the extra confirmation), or the recipient is the sender of a flagged email.
`Executors.run()` is called by `Gateway` only after a decision
of `executed`. This is the single module in the codebase allowed to import `app.executor`.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

from app.connections.gmail import FlaggedSenders, MailRoute
from app.connections.sandboxpay import PaymentRoute
from app.executor import reminder_sender
from app.executor.mail_sender import MailSender
from app.executor.sandbox_bank import SandboxBank
from app.executor.sandbox_mailbox import SandboxMailbox
from app.gateway.drafts import LoanDraftStore
from app.gateway.emails import EmailDraftStore, RecipientBook, check_draft

ACTION_ARGS: dict[str, dict[str, type]] = {
    "send_invoice_reminder": {"customer_id": str, "invoice_id": str, "invoice_amount_minor": int},
    "pay_recurring_bill": {"payee_id": str, "bill_id": str, "amount_minor": int},
    # One payment the owner signs: payee, amount and account are all inside the signed args hash.
    "pay_invoice": {"payee_id": str, "account_token": str, "amount_minor": int, "reference": str, "request_id": str},
    "submit_loan_application": {"product_id": str, "amount_minor": int, "draft_id": str},
    "change_payee_details": {"payee_id": str, "account_token": str},
    "delay_supplier_payment": {"payment_ref": str, "new_date": str},
    "send_supplier_message": {"supplier_id": str, "template_id": str},
    # One email the owner signs: the draft ID commits to the exact subject and body (gateway/emails.py).
    "send_email": {"recipient_id": str, "draft_id": str},
    "cancel_subscription": {"subscription_id": str},
}


def check_args(tool: str, args: dict) -> str | None:
    """None if `args` match the tool's declared arguments exactly, else the rule that fired."""
    spec = ACTION_ARGS.get(tool)
    if spec is None:
        return "no_executor"
    if set(args) != set(spec):
        missing, extra = sorted(set(spec) - set(args)), sorted(set(args) - set(spec))
        return f"bad_args:missing={','.join(missing)};extra={','.join(extra)}"
    for name, typ in spec.items():
        value = args[name]
        if isinstance(value, bool) or not isinstance(value, typ):
            return f"bad_args:{name} must be {typ.__name__}"
    return None


class Executors:
    def __init__(self, data_dir: Path | None, loan_drafts: LoanDraftStore | None = None,
                 mail: MailRoute | None = None, payments: PaymentRoute | None = None):
        self.loan_drafts = loan_drafts or LoanDraftStore(data_dir / "loan_drafts" if data_dir else None)
        self.payments = payments
        self.mail_route = mail
        self.email_drafts = EmailDraftStore(data_dir / "email_drafts" if data_dir else None)
        self.recipients = RecipientBook(data_dir / "email_recipients.json" if data_dir else None,
                                        mail.recipient if mail else None,
                                        mail.contacts if mail else None)
        self.bank = SandboxBank(data_dir / "sandbox_bank.sqlite" if data_dir else ":memory:", payments)
        self.mailbox = SandboxMailbox(data_dir / "sandbox_mailbox.sqlite" if data_dir else ":memory:")
        self.mail = MailSender(self.mailbox, mail, self.recipients.get)
        self._run: dict[str, Callable[[dict, date], dict]] = {
            "send_invoice_reminder": lambda a, d: reminder_sender.send_invoice_reminder(
                self.mail,a["customer_id"], a["invoice_id"], d),
            "pay_recurring_bill": lambda a, d: self.bank.pay(a["payee_id"], a["amount_minor"], a["bill_id"], d),
            "pay_invoice": lambda a, d: self.bank.pay(a["payee_id"], a["amount_minor"], a["reference"], d,
                                                      account_token=a["account_token"],
                                                      idempotency_key=a["request_id"], request_id=a["request_id"]),
            "submit_loan_application": self._submit_loan_application,
            "change_payee_details": lambda a, d: self.bank.change_payee(a["payee_id"], a["account_token"], d),
            "delay_supplier_payment": lambda a, d: self.bank.reschedule_payment(a["payment_ref"], a["new_date"], d),
            "send_supplier_message": lambda a, d: self.mailbox.send(
                "supplier_message", a["supplier_id"], {"template_id": a["template_id"]}, d),
            "cancel_subscription": lambda a, d: self.bank.cancel_subscription(a["subscription_id"], d),
            "send_email": self._send_email,
        }
        assert set(self._run) == set(ACTION_ARGS)

    def precheck(self, tool: str, args: dict) -> str | None:
        """None if the action's referents are sound, else the rule that fired."""
        if tool == "submit_loan_application":
            return self.loan_drafts.check(args)
        if tool == "send_email":
            flagged = self.mail_route.flagged_senders() if self.mail_route else FlaggedSenders()
            return check_draft(self.email_drafts, self.recipients, flagged, args)
        if tool == "pay_invoice":
            if self.bank.account_for(args["payee_id"]) != args["account_token"]:
                return "payee_account_changed"
            if self.payments is not None:
                return self.payments.check_request(args)
        return None

    def run(self, tool: str, args: dict, today: date) -> dict:
        return self._run[tool](args, today)

    def _send_email(self, args: dict, today: date) -> dict:
        """Send the signed draft (intact and for this recipient: precheck has just verified both)."""
        _, doc, sha256 = self.email_drafts.load(args["draft_id"])
        return self.mail.send("email", args["recipient_id"], doc["subject"], doc["body"],
                              {"draft_id": args["draft_id"], "draft_sha256": sha256, "origin": doc["origin"],
                               **({"about": doc["about"]} if doc.get("about") else {})}, today)

    def _submit_loan_application(self, args: dict, today: date) -> dict:
        _, _, sha256 = self.loan_drafts.load(args["draft_id"])
        return self.mailbox.send("loan_application_draft", args["product_id"], {
            "amount_minor": args["amount_minor"], "draft_id": args["draft_id"], "draft_sha256": sha256}, today)
