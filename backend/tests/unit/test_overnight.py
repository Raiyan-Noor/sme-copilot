"""The overnight job: T2 send_invoice_reminder through the gateway under a signed standing mandate, then the
Morning Brief through the Numeric Firewall. Runs over the real seed, via the API, with a scripted brief writer.

Expected reminder outcomes come from the seed manifest's `t2_send_invoice_reminder` ground truth.
"""

import json
from dataclasses import dataclass

import pytest
from nacl.signing import SigningKey

from app.audit import AuditLog
from app.firewall.digit_check import check_output
from app.gateway import SignedPayload
from app.llm.adapter import LLMUnavailable
from tests.agent_env import MAYA, agent_client, build_template, copy_data_dir

LINA = "lina-boutique"
OWNER = SigningKey(b"\x07" * 32)
OWNER_PK = OWNER.verify_key.encode().hex()


@dataclass
class Draft:
    content: str | None


class FakeBriefWriter:
    """Stands in for the brief_writer role: returns scripted drafts (or raises) and records requests."""

    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.requests: list[list[dict]] = []

    def chat(self, role, messages, *, tools=None, tool_choice=None, max_output_tokens=None):
        assert role == "brief_writer" and not tools, "the brief writer has no tools"
        self.requests.append(messages)
        step = self.drafts.pop(0) if self.drafts else LLMUnavailable([])
        if isinstance(step, Exception):
            raise step
        return Draft(step)


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("overnight")
    data_dir, seed_dir = build_template(root)
    manifest = json.loads((seed_dir / "manifest.json").read_text(encoding="utf-8"))
    return data_dir, seed_dir, manifest


@pytest.fixture
def env(template, tmp_path):
    data_dir, seed_dir, manifest = template

    def make(llm=None):
        client = agent_client(copy_data_dir(data_dir, tmp_path / "data"), seed_dir, llm or FakeBriefWriter())
        return client, client.app.state.runtime

    return make, manifest


def grant(client, business=MAYA, allowlist=("cus_littlesteps", "cus_sunrise"), cap=50_000, days=30):
    base = f"/businesses/{business}/gateway"
    assert client.post(f"{base}/owner-key", json={"public_key": OWNER_PK}).status_code == 200
    draft = client.post(f"{base}/mandates/draft", json={
        "action": "send_invoice_reminder", "terms": {"max_amount_minor": cap, "allowlist": list(allowlist)},
        "days": days}).json()
    signature = OWNER.sign(SignedPayload.model_validate(draft["payload"]).message()).signature.hex()
    result = client.post(f"{base}/mandates", json={"payload": draft["payload"], "terms": draft["terms"],
                                                   "signature": signature, "public_key": OWNER_PK}).json()
    assert result["accepted"], result


def advance(client, days=1):
    r = client.post("/clock/advance", json={"days": days})
    assert r.status_code == 200, r.text
    return {rep["business_id"]: rep for rep in r.json()["overnight"]}


def outbox(rt, business=MAYA):
    return rt.gateway(business).executors.mailbox.outbox()


def overnight(client, business=MAYA):
    r = client.post(f"/businesses/{business}/overnight")
    assert r.status_code == 200, r.text
    return r.json()


def denial_rules(rt, business=MAYA) -> dict[str, str]:
    """customer_id -> the rule the gateway denied the T2 reminder with, from the audit log."""
    entries = [json.loads(line) for line in (rt.data_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    return {e["data"]["args"]["customer_id"]: e["data"]["rule"] for e in entries
            if e["kind"] == "gateway.decision" and e["data"]["tool"] == "send_invoice_reminder"
            and e["data"]["status"] == "denied"}


def by_customer(report):
    return {o["customer_id"]: o for o in report["reminders"]}


# --- reminders ----------------------------------------------------------------------------------------------------

def test_reminders_follow_the_signed_mandate_and_policy(env):
    make, manifest = env
    client, rt = make()
    grant(client)
    outcomes = by_customer(advance(client)[MAYA])
    truth = {a["facts"]["customer_id"]: a["expected_detection"]["t2_send_invoice_reminder"]
             for a in manifest["anomalies"] if a["business_id"] == "maya_corner_store"
             and a["kind"] == "overdue_receivable"}
    assert set(outcomes) == set(truth)
    for customer, t in truth.items():
        o = outcomes[customer]
        if t["eligible"]:
            assert o["status"] == "executed" and o["mandate_id"] is not None
        else:
            # Not covered by the signed limits: the gateway denied the T2 reminder (the audit log has the rule) and the
            # job drafted the reminder as an email for the owner to sign instead.
            expected = {"over_cap": "over_policy_cap", "customer_not_allowlisted": "not_allowlisted:customer_id"}
            assert denial_rules(rt)[customer] == expected[t["reason"]]
            assert o["status"] == "pending_approval" and o["tool"] == "send_email" and o["approval_id"]
    sent = outbox(rt)
    assert [(m["kind"], m["recipient_id"]) for m in sent] == [("invoice_reminder", "cus_littlesteps")]


def test_no_mandate_means_nothing_is_sent(env):
    make, _ = env
    client, rt = make()
    reports = advance(client)
    for report in reports.values():
        # No standing limit: nothing runs on its own. Each overdue invoice becomes a drafted email that waits.
        assert report["reminders"] and {o["rule"] for o in report["reminders"]} == {"tier_T3"}
        assert {o["status"] for o in report["reminders"]} == {"pending_approval"}
    assert outbox(rt, MAYA) == [] and outbox(rt, LINA) == []


def test_frequency_cap_holds_across_nights(env):
    make, _ = env
    client, rt = make()
    grant(client)
    assert by_customer(advance(client)[MAYA])["cus_littlesteps"]["status"] == "executed"
    for _ in range(2):  # days two and three of the three-day window
        assert by_customer(advance(client)[MAYA])["cus_littlesteps"]["rule"] == "frequency_cap"
    assert by_customer(advance(client)[MAYA])["cus_littlesteps"]["status"] == "executed"
    assert len(outbox(rt)) == 2


def test_a_lower_mandate_cap_is_enforced(env):
    make, _ = env
    client, rt = make()
    grant(client, cap=30_000)  # Little Steps owes more than this
    o = by_customer(advance(client)[MAYA])["cus_littlesteps"]
    assert denial_rules(rt)["cus_littlesteps"] == "over_mandate_cap"
    assert o["status"] == "pending_approval" and o["tool"] == "send_email"  # the owner may still sign it by hand
    assert outbox(rt) == []


def test_expired_mandate_stops_reminders(env):
    make, _ = env
    client, rt = make()
    grant(client, days=1)
    advance(client, days=2)
    assert outbox(rt) == []


def test_invoice_from_an_untrusted_source_is_never_proposed(env):
    """Red team: a due date the extractor read from an email must not trigger an autonomous reminder."""
    make, _ = env
    client, rt = make()
    grant(client, allowlist=("cus_littlesteps", "cus_sunrise", "cus_mallory"))
    with rt.business(MAYA) as conn, conn:
        conn.execute("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                     " counterparty_id, reference, source) VALUES ('MBX-1', 'receivable', 'customer_invoice',"
                     " '2026-10-01', 9000, 'open', 'cus_mallory', 'FAKE-INV', 'mailbox')")
    o = by_customer(advance(client)[MAYA])["cus_mallory"]
    assert o["status"] == "skipped" and o["rule"] == "untrusted_source"
    assert all(m["recipient_id"] != "cus_mallory" for m in outbox(rt))


def test_every_reminder_decision_is_in_the_audit_log(env):
    make, _ = env
    client, rt = make()
    grant(client)
    advance(client)
    entries = [json.loads(line) for line in (rt.data_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in entries]
    decisions = [e for e in entries if e["kind"] == "gateway.decision" and e["data"]["tool"] == "send_invoice_reminder"]
    assert len(decisions) == 5  # three overdue at Maya's, two at Lina's
    assert kinds.count("executor.executed") == 1
    assert {"overnight.started", "overnight.finished", "brief.generated", "clock.advanced"} <= set(kinds)
    assert AuditLog(rt.data_dir / "audit.jsonl", rt.clock).verify().ok


# --- Morning Brief -------------------------------------------------------------------------------------------------

def test_template_brief_reports_exactly_what_the_gateway_did(env):
    make, _ = env
    client, _ = make()  # the fake writer is unavailable: template text
    grant(client)
    brief = advance(client)[MAYA]["brief"]
    assert brief["generated_by"] == "template" and brief["firewall"]["fallback"]
    assert [d["status"] for d in brief["done_overnight"]] == ["executed"]
    assert {d["rule"] for d in brief["not_done"]} == {"tier_T3"}
    assert {d["tool"] for d in brief["not_done"]} == {"send_email"}
    assert [n["email"]["subject"] for n in brief["needs_you"]] == ["A friendly reminder about your open invoice"] * 2
    text = "\n".join(brief["paragraphs"])
    assert "Little Steps Daycare" in text and "Done overnight" in text
    assert check_output(text, set(brief["facts"])).ok  # no digit outside a placeholder, only cited facts
    assert brief["improve"]["detector"] == "supplier_price_creep"


def test_template_brief_greets_the_owner_by_first_name(env):
    make, _ = env
    client, _ = make()  # template text
    assert advance(client)[MAYA]["brief"]["paragraphs"][0] == "Good morning, Maya."


def test_a_writer_that_already_greets_is_not_greeted_twice(env):
    make, _ = env
    client, _ = make(FakeBriefWriter("Good morning, Maya. Cash on hand is {fact:cash.balance}."))
    assert overnight(client)["brief"]["paragraphs"] == ["Good morning, Maya. Cash on hand is {fact:cash.balance}."]


def test_a_brief_saved_without_a_greeting_is_greeted_when_served(env):
    make, _ = env
    client, _ = make()
    overnight(client)
    briefs = client.app.state.runtime.data_dir / MAYA / "briefs"
    saved = sorted(briefs.glob("*.json"))[-1]
    old = json.loads(saved.read_text(encoding="utf-8"))
    old["paragraphs"] = old["paragraphs"][1:]  # as written before the greeting existed
    saved.write_text(json.dumps(old), encoding="utf-8")
    served = client.get(f"/businesses/{MAYA}/brief").json()["paragraphs"]
    assert served == ["Good morning, Maya.", *old["paragraphs"]]


def test_brief_without_executions_never_says_done(env):
    make, _ = env
    client, _ = make()
    brief = advance(client)[MAYA]["brief"]
    assert brief["done_overnight"] == []
    assert not any("Done overnight" in p for p in brief["paragraphs"])


def test_llm_brief_is_used_when_it_passes_the_firewall(env):
    make, _ = env
    writer = FakeBriefWriter("Cash on hand is {fact:cash.balance}.\n\nOne thing to improve: rice prices.")
    client, _ = make(writer)
    brief = overnight(client)["brief"]
    assert brief["generated_by"] == "llm"
    assert brief["paragraphs"] == ["Good morning, Maya.", "Cash on hand is {fact:cash.balance}.",
                                   "One thing to improve: rice prices."]
    bundle = writer.requests[0][1]["content"]
    # The writer sees placeholders and names, never a fact value or statement text.
    assert "{fact:cash.balance}" in bundle
    cash = client.app.state.runtime.facts(MAYA).store.get("cash.balance")
    assert cash.display not in bundle and str(cash.value) not in bundle


def test_digits_in_the_brief_get_one_reprompt_then_the_template(env):
    make, _ = env
    writer = FakeBriefWriter("You have $4,280 in cash.", "Cash is 4280 today.")
    client, _ = make(writer)
    brief = overnight(client)["brief"]
    assert len(writer.requests) == 2 and brief["generated_by"] == "template"
    assert brief["firewall"] == {"attempts": 2, "rejected": [["digit"], ["digit"]], "fallback": True}


def test_brief_may_not_cite_facts_outside_its_bundle(env):
    make, _ = env
    writer = FakeBriefWriter("Gross margin is {fact:margin.last_90d.gross_margin}.", "Still {fact:nope.x}.")
    client, _ = make(writer)
    assert overnight(client)["brief"]["generated_by"] == "template"


def test_latest_brief_and_leaks_endpoints(env):
    make, _ = env
    client, _ = make()
    assert client.get(f"/businesses/{MAYA}/brief").status_code == 404
    report = client.post(f"/businesses/{MAYA}/overnight", params={"reminders": False}).json()
    assert report["reminders"] == []
    latest = client.get(f"/businesses/{MAYA}/brief").json()
    assert latest["as_of"] == report["brief"]["as_of"]
    leaks = client.get(f"/businesses/{MAYA}/leaks").json()
    assert {lk["detector"] for lk in leaks} == {"supplier_price_creep", "missed_early_pay_discounts",
                                                "payment_fees", "duplicate_subscription", "unprofitable_products",
                                                "late_fees"}
    values = [lk["yearly_impact"]["value"] for lk in leaks]
    assert values == sorted(values, reverse=True)
    trace = client.get(f"/businesses/{MAYA}/facts/{leaks[0]['yearly_impact']['id']}/explain").json()
    assert {r["kind"] for r in trace["rows"]} == {"purchase_line"}


def test_advance_without_overnight_runs_nothing(env):
    make, _ = env
    client, rt = make()
    r = client.post("/clock/advance", json={"days": 1, "run_overnight": False}).json()
    assert r["overnight"] == [] and client.get(f"/businesses/{MAYA}/brief").status_code == 404


# --- reminder emails drafted for the owner to sign (P4) -----------------------------------------------------------

def waiting_emails(client, business=MAYA):
    return client.get(f"/businesses/{business}/outbox").json()["waiting"]


def sign(client, approval_id, business=MAYA):
    from tests.owner_api import approve, enroll
    owner = enroll(client, business)
    return approve(client, business, approval_id, owner)


def test_an_overdue_invoice_becomes_a_drafted_email_the_owner_signs(env):
    make, _ = env
    client, rt = make()
    report = advance(client)[MAYA]  # no mandate: nothing runs on its own, every reminder is drafted
    drafted = {o["customer_id"]: o for o in report["reminders"]}
    assert drafted and all(o["status"] == "pending_approval" and o["tool"] == "send_email" for o in drafted.values())
    waiting = {w["email"]["recipient_id"]: w for w in waiting_emails(client)}
    assert set(waiting) == set(drafted)
    mail = waiting["cus_littlesteps"]["email"]
    assert mail["origin"] == "overnight" and mail["subject"] == "A friendly reminder about your open invoice"
    assert "{fact:" not in mail["body"] and "Hello Little Steps Daycare" in mail["body"]
    facts = rt.facts(MAYA).store
    by_key = {f.split(".")[-1]: facts.get(f) for f in mail["fact_ids"]}
    assert set(by_key) == {"amount", "due_date", "days_overdue"}  # the body and the reason, all traced to facts
    for key in ("amount", "due_date"):
        assert by_key[key].display in mail["body"]  # every number in the email is a traced fact's display
    assert by_key["days_overdue"].display in mail["reason"]
    assert outbox(rt) == []
    assert sign(client, waiting["cus_littlesteps"]["approval_id"])["status"] == "executed"
    [sent] = outbox(rt)
    assert sent["kind"] == "email" and sent["recipient_id"] == "cus_littlesteps" and sent["body"] == mail["body"]
    assert sent["about"]["invoice_id"] and sent["transport"] == "sandbox"


def test_a_waiting_reminder_is_not_drafted_twice_and_a_signed_one_waits_out_the_window(env):
    make, _ = env
    client, rt = make()
    first = by_customer(advance(client)[MAYA])["cus_littlesteps"]
    again = by_customer(advance(client)[MAYA])["cus_littlesteps"]
    assert again["approval_id"] == first["approval_id"] and again["status"] == "pending_approval"
    assert len([w for w in waiting_emails(client) if w["email"]["recipient_id"] == "cus_littlesteps"]) == 1
    assert sign(client, first["approval_id"])["status"] == "executed"
    for _ in range(2):  # the rest of the three-day window
        o = by_customer(advance(client)[MAYA])["cus_littlesteps"]
        assert o["status"] == "denied" and o["rule"] == "frequency_cap"
    assert by_customer(advance(client)[MAYA])["cus_littlesteps"]["status"] == "pending_approval"


def test_a_frequency_capped_reminder_is_not_worked_around_by_an_email(env):
    make, _ = env
    client, rt = make()
    grant(client)
    assert by_customer(advance(client)[MAYA])["cus_littlesteps"]["status"] == "executed"
    o = by_customer(advance(client)[MAYA])["cus_littlesteps"]
    assert o["rule"] == "frequency_cap" and o["tool"] == "send_invoice_reminder"
    assert not [w for w in waiting_emails(client) if w["email"]["recipient_id"] == "cus_littlesteps"]


def test_no_email_is_drafted_for_an_invoice_from_an_untrusted_source(env):
    make, _ = env
    client, rt = make()
    with rt.business(MAYA) as conn, conn:
        conn.execute("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                     " counterparty_id, reference, source) VALUES ('MBX-2', 'receivable', 'customer_invoice',"
                     " '2026-10-01', 9000, 'open', 'cus_mallory', 'FAKE-INV', 'mailbox')")
    o = by_customer(advance(client)[MAYA])["cus_mallory"]
    assert o["status"] == "skipped" and o["rule"] == "untrusted_source"
    assert all(w["email"]["recipient_id"] != "cus_mallory" for w in waiting_emails(client))
