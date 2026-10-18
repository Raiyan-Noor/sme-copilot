"""Invoice reminder sender (Tier 2 under a standing mandate), backed by the sandbox mailbox.

Invariant 1: import only from app.gateway.
"""

from datetime import date

from app.executor.sandbox_mailbox import SandboxMailbox


def send_invoice_reminder(mailbox: SandboxMailbox, customer_id: str, invoice_id: str, today: date) -> dict:
    return mailbox.send("invoice_reminder", customer_id, {"invoice_id": invoice_id}, today)
