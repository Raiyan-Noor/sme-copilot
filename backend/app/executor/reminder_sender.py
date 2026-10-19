"""Invoice reminder sender (Tier 2 under a standing mandate): a fixed, code-written reminder, sent through
mail_sender (Gmail when connected and the recipient is allow-listed, otherwise the sandbox outbox).

The text is a template filled only with ledger values (the invoice ID, the business and contact names); no LLM
writes it and it states no amount, so no number reaches the customer that the Numeric Firewall has not seen.

Invariant 1: import only from app.gateway.
"""

from datetime import date

from app.executor.mail_sender import MailSender


def send_invoice_reminder(sender: MailSender, customer_id: str, invoice_id: str, today: date) -> dict:
    route = sender.route
    business = route.business_name() if route else ""
    rcpt = route.recipient(customer_id) if route else None
    hello = f"Hello {rcpt.name}," if rcpt and rcpt.name else "Hello,"
    body = "\n\n".join([
        hello,
        f"This is a friendly reminder that invoice {invoice_id} is now due. If you have already paid it, thank you, "
        "and please ignore this message.",
        f"Kind regards,\n{business}".rstrip(),
    ])
    return sender.send("invoice_reminder", customer_id, f"Reminder: invoice {invoice_id}", body,
                       {"invoice_id": invoice_id}, today)
