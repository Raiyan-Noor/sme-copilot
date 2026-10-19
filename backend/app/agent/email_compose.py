"""Compose an outgoing email from text with `{fact:<id>}` placeholders (invariant 4).

The planner and the overnight job write an email's subject, body and reason with placeholders for every amount and
date. Each piece goes through the Numeric Firewall: a digit outside a placeholder, a malformed placeholder or a fact
that was not computed for this request rejects the whole email, so no invented number can reach a customer. What
comes back is the final text (placeholders replaced by each fact's display) plus the facts it was rendered from,
which the draft records so the owner can trace every number in it.

Nothing here sends or even stores anything: the draft goes to the gateway (`Gateway.save_email_draft`), and the email
still needs the owner's signature.
"""

from dataclasses import dataclass

from app.firewall.digit_check import check_output
from app.firewall.render import render
from app.firewall.store import FactStore
from app.gateway.emails import MAX_BODY, MAX_SUBJECT


class EmailRejected(ValueError):
    """The email text was refused; `rule` says why (`numeric_firewall`, `bad_email_text`)."""

    def __init__(self, rule: str, detail: str = ""):
        self.rule = rule
        super().__init__(f"{rule}: {detail}" if detail else rule)


@dataclass(frozen=True)
class Composed:
    subject: str
    body: str
    reason: str
    facts: list[dict[str, str]]  # {id, display} of every placeholder, in order of first appearance


def compose(store: FactStore, subject: str, body: str, reason: str) -> Composed:
    parts = {"subject": subject.strip(), "body": body.strip(), "reason": reason.strip()}
    if not parts["subject"] or not parts["body"]:
        raise EmailRejected("bad_email_text", "an email needs a subject and a body")
    if len(parts["subject"]) > MAX_SUBJECT or len(parts["body"]) > MAX_BODY or "\n" in parts["subject"]:
        raise EmailRejected("bad_email_text", "subject must be one short line and the body short")
    rendered: dict[str, str] = {}
    facts: dict[str, str] = {}
    for name, text in parts.items():
        result = check_output(text, store)
        if not result.ok:
            kinds = ", ".join(sorted({v.kind.value for v in result.violations}))
            raise EmailRejected("numeric_firewall", f"{name}: {kinds}")
        out = render(text, store)
        rendered[name] = out.text
        for fact_id in out.fact_ids:
            facts.setdefault(fact_id, store.get(fact_id).display)
    return Composed(rendered["subject"], rendered["body"], rendered["reason"],
                    [{"id": k, "display": v} for k, v in facts.items()])
