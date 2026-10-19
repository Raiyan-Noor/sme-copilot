"""Send one approved email through the connected Gmail account (gmail.send). The only place in the codebase that
calls Gmail's send endpoint.

Invariant 1: import only from app.gateway (via mail_sender). It is reached only after the gateway has decided
`executed` (a T2 action within a signed mandate, or a T3 action the owner signed).
"""

import base64
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.connections.gmail import API_URL, GmailError, GmailSendAccess
from app.connections.http import TransportError

SEND_URL = f"{API_URL}/messages/send"


def build_message(from_address: str, from_name: str, to_address: str, to_name: str, subject: str,
                  body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = formataddr((to_name, to_address))
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_address.rsplit("@", 1)[-1])
    msg.set_content(body)
    return msg


def send(access: GmailSendAccess, msg: EmailMessage) -> str:
    """Gmail's message ID for the sent email. Raises GmailError (never retried here: a retry could send twice)."""
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        res = access.transport.request("POST", SEND_URL, headers={"Authorization": f"Bearer {access.token()}"},
                                       json_body={"raw": raw})
    except TransportError as exc:
        raise GmailError(f"network:{exc}") from None
    if not res.ok or not isinstance(res.body, dict) or not res.body.get("id"):
        raise GmailError(res.error_code())
    return str(res.body["id"])
