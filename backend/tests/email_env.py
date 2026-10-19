"""Email test helpers: a mail route over a tiny contact book whose flagged senders the test can change, and helpers to
draft an email in a gateway the way the planner, the overnight job and the owner's compose route do."""

from dataclasses import dataclass, field
from pathlib import Path

from app.connections.gmail import FlaggedSenders, MailRoute, Recipient
from app.gateway import Gateway
from app.gateway.emails import build_draft
from tests.gateway_env import Env, action

CONTACTS = {
    "cus_sunrise": Recipient("Sunrise Cafe", "orders@sunrisecafe.example"),
    "cus_littlesteps": Recipient("Little Steps Daycare", "office@littlestepsdaycare.example"),
    "sup_fresh": Recipient("FreshLine Produce", "invoices@freshlineproduce.example"),
    "pay_citygrid": Recipient("CityGrid Power", None),  # a payee with no email on file
}


@dataclass
class Flagged:
    """What the Inbox Sentinel flagged; mutate between proposal and approval to test the re-check."""

    addresses: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)

    def __call__(self) -> FlaggedSenders:
        return FlaggedSenders(frozenset(self.addresses), frozenset(self.ids))


def mail_route(flagged: Flagged) -> MailRoute:
    kinds = {"cus_sunrise": "customer", "cus_littlesteps": "customer", "sup_fresh": "supplier"}
    return MailRoute(
        business_name=lambda: "Maya's Corner Store", recipient=CONTACTS.get, gmail=lambda: None,
        allowlist=frozenset(), flagged_senders=flagged,
        contacts=lambda: [(i, c.name, kinds[i], c.email) for i, c in CONTACTS.items() if i in kinds])


class EmailEnv(Env):
    def __init__(self, tmp_path: Path):
        self.flagged = Flagged()
        super().__init__(tmp_path, mail=mail_route(self.flagged))

    def draft(self, recipient_id: str = "cus_sunrise", subject: str = "A friendly reminder",
              body: str = "Hello, your invoice is overdue. Thank you.", origin: str = "planner") -> str:
        draft_id, _ = self.gateway.save_email_draft(build_draft(
            recipient_id=recipient_id, subject=subject, body=body, reason="It is overdue.", origin=origin,
            facts=[]))
        return draft_id

    def email(self, recipient_id: str = "cus_sunrise", untrusted: tuple[str, ...] = (), **draft):
        return action("send_email", untrusted=untrusted, recipient_id=recipient_id,
                      draft_id=self.draft(recipient_id, **draft))

    def draft_path(self, draft_id: str) -> Path:
        return self.gateway.executors.email_drafts.folder / f"{draft_id}.json"


def gateway_of(env: Env) -> Gateway:
    return env.gateway
