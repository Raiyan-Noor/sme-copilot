"""The only bridge from gateway decisions to executors (invariant 1).

`ACTION_ARGS` declares each action's required arguments and types; the gateway rejects a proposal whose arguments
do not match before any policy or signature check. `Executors.run()` is called by `Gateway` only after a decision
of `executed`. This is the single module in the codebase allowed to import `app.executor`.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

from app.executor import reminder_sender
from app.executor.sandbox_bank import SandboxBank
from app.executor.sandbox_mailbox import SandboxMailbox

ACTION_ARGS: dict[str, dict[str, type]] = {
    "send_invoice_reminder": {"customer_id": str, "invoice_id": str, "invoice_amount_minor": int},
    "pay_recurring_bill": {"payee_id": str, "bill_id": str, "amount_minor": int},
    "submit_loan_application": {"product_id": str, "amount_minor": int},
    "change_payee_details": {"payee_id": str, "account_token": str},
    "delay_supplier_payment": {"payment_ref": str, "new_date": str},
    "send_supplier_message": {"supplier_id": str, "template_id": str},
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
    def __init__(self, data_dir: Path | None):
        self.bank = SandboxBank(data_dir / "sandbox_bank.sqlite" if data_dir else ":memory:")
        self.mailbox = SandboxMailbox(data_dir / "sandbox_mailbox.sqlite" if data_dir else ":memory:")
        self._run: dict[str, Callable[[dict, date], dict]] = {
            "send_invoice_reminder": lambda a, d: reminder_sender.send_invoice_reminder(
                self.mailbox, a["customer_id"], a["invoice_id"], d),
            "pay_recurring_bill": lambda a, d: self.bank.pay(a["payee_id"], a["amount_minor"], a["bill_id"], d),
            "submit_loan_application": lambda a, d: self.mailbox.send(
                "loan_application_draft", a["product_id"], {"amount_minor": a["amount_minor"]}, d),
            "change_payee_details": lambda a, d: self.bank.change_payee(a["payee_id"], a["account_token"], d),
            "delay_supplier_payment": lambda a, d: self.bank.reschedule_payment(a["payment_ref"], a["new_date"], d),
            "send_supplier_message": lambda a, d: self.mailbox.send(
                "supplier_message", a["supplier_id"], {"template_id": a["template_id"]}, d),
            "cancel_subscription": lambda a, d: self.bank.cancel_subscription(a["subscription_id"], d),
        }
        assert set(self._run) == set(ACTION_ARGS)

    def run(self, tool: str, args: dict, today: date) -> dict:
        return self._run[tool](args, today)
