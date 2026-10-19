"""Inbox Sentinel rules, one boundary at a time, over a hand-built directory (no LLM, no tenant DB)."""

from datetime import date

import pytest

from app.quarantine.feed import plan_items
from app.quarantine.typed import DocumentFields, OwnerView, PromiseField, Untrusted
from app.sentinel.checks import Headers, LedgerInvoice, TextEvidence, assess
from app.sentinel.directory import Counterparty, Directory
from app.sentinel.domains import find_lookalike

KNOWN = frozenset({"goldengrain.example", "shop.example", "cafe.example"})


def _u(v, src="em-1:email"):
    return Untrusted(value=v, source=src, confidence=0.95, needs_review=False)


def _dir() -> Directory:
    ggw = Counterparty("sup_ggw", "Golden Grain", "supplier", frozenset({"goldengrain.example"}),
                       frozenset({"billing@goldengrain.example"}), frozenset({"acct_known"}), ("5532",),
                       ("Sam Ortega",), 30)
    cafe = Counterparty("cus_cafe", "Sunrise Cafe", "customer", frozenset({"cafe.example"}), terms_days=30)
    owner = Counterparty("owner", "Maya Collins", "owner", frozenset({"shop.example"}),
                         frozenset({"maya@shop.example"}), person_names=("Maya Collins",))
    return Directory("Shop", "shop.example", "Maya Collins", "maya@shop.example",
                     {c.id: c for c in (ggw, cafe, owner)}, KNOWN,
                     payments_by_token={"acct_known": [100_000, 120_000, 110_000]},
                     category_by_counterparty={"sup_ggw": "staples", "cus_cafe": "customer_invoice"},
                     typical_payment_minor=8_500)


def _assess(fields: DocumentFields, *, sender="billing@goldengrain.example", display="Golden Grain",
            reply_to=None, text=TextEvidence(), ledger=None, seen=None):
    h = Headers(sender, display, sender.split("@")[1], reply_to, date(2026, 10, 16))
    return assess(h, fields, OwnerView(), text, _dir(), "USD", ledger or {}, seen or {}, "em-9")


def _invoice(**kw) -> DocumentFields:
    base = dict(category="invoice", has_invoice_document=True, amount_minor=_u(105_000),
                due_date=_u(date(2026, 11, 1)), invoice_number=_u("GGW-1"), invoice_number_from_document=True,
                payee_account_token=_u("acct_known"), payee_account_last4="5532")
    base.update(kw)
    return DocumentFields(**base)


def test_clean_known_invoice_has_no_flags():
    r = _assess(_invoice())
    assert (r.sender_status, r.flags, r.risk, r.hold) == ("known", [], "none", False)


def test_unreadable_message_with_a_code_side_high_flag_is_held():
    """If the model could not read the message (outage), a lookalike sender still holds it; a clean one does not."""
    unread = DocumentFields(extraction_status={"email": "unavailable"})
    r = _assess(unread, sender="ar@goldengra1n.example")
    assert "lookalike_domain" in r.codes and r.hold and not r.payment_requested
    clean = _assess(unread)
    assert clean.flags == [] and not clean.hold
    read_ok = _assess(DocumentFields(extraction_status={"email": "ok"}), sender="ar@goldengra1n.example")
    assert "lookalike_domain" in read_ok.codes and not read_ok.hold  # read fine and no payment asked: review only


def test_lookalike_sender_with_new_account_is_bank_change_and_held():
    r = _assess(_invoice(payee_account_token=_u("acct_new"), payee_account_last4="9918"),
                sender="ar@goldengra1n.example")
    assert {"lookalike_domain", "bank_detail_change", "display_name_spoof"} <= set(r.codes)
    assert r.hold and r.payee_counterparty_id == "sup_ggw" and "first_time_payee" not in r.codes
    script = " ".join(r.call_script.lines)
    assert "ending 5532" in script and "ending 9918" in script and "Golden Grain" in script


def test_known_sender_asking_for_new_account_is_bank_change():
    r = _assess(_invoice(payee_account_token=_u("acct_new"), payee_account_last4="0001"))
    assert r.codes == ["bank_detail_change"] and r.risk == "hold"


def test_owner_display_name_on_free_mail_is_spoof_and_new_payee_is_held():
    f = DocumentFields(category="payment_request", amount_minor=_u(285_000), payee_account_token=_u("acct_x"),
                       payee_account_last4="7731")
    r = _assess(f, sender="maya.collins@quickmail.example", display="Maya Collins",
                text=TextEvidence(urgency_patterns=("urgent",)))
    assert {"display_name_spoof", "first_time_payee", "amount_anomaly", "urgency"} <= set(r.codes)
    assert r.hold and "verify_by_phone_before_paying" in r.recommended


def test_new_payee_small_amount_is_held_but_not_anomalous():
    f = DocumentFields(category="invoice", amount_minor=_u(5_000), payee_account_token=_u("acct_y"))
    r = _assess(f, sender="x@newvendor.example", display="New Vendor")
    assert "first_time_payee" in r.codes and "amount_anomaly" not in r.codes


@pytest.mark.parametrize("amount,anomaly", [(180_000, False), (180_001, True)])
def test_amount_anomaly_boundary_vs_payee_history(amount, anomaly):
    r = _assess(_invoice(amount_minor=_u(amount)))  # largest previous payment 120_000; limit 1.5x
    assert ("amount_anomaly" in r.codes) is anomaly


def test_reply_to_lookalike():
    r = _assess(_invoice(), reply_to="cafe-example.example")
    assert "reply_to_mismatch" in r.codes


def test_duplicate_and_amount_mismatch_against_ledger_and_earlier_mail():
    ledger = {"GGW-1": LedgerInvoice("GGW-1", 100_000, date(2026, 10, 20), "sup_ggw")}
    r = _assess(_invoice(marked_overdue=True), ledger=ledger, seen={"GGW-1": "em-3"})
    assert {"duplicate_invoice", "amount_mismatch"} <= set(r.codes)
    dup = next(f for f in r.flags if f.code == "duplicate_invoice")
    assert dup.evidence["first_received_in"] == "em-3" and dup.evidence["ledger_due_date"] == "2026-10-20"


def test_original_invoice_matching_ledger_is_not_a_duplicate():
    ledger = {"GGW-1": LedgerInvoice("GGW-1", 105_000, date(2026, 11, 1), "sup_ggw")}
    assert _assess(_invoice(), ledger=ledger).flags == []


def test_receipt_totals():
    f = DocumentFields(category="payment_request", has_receipt=True, amount_minor=_u(18_460),
                       line_items_sum_minor=8_460, stated_total_minor=18_460, cash_tendered_minor=10_000,
                       change_minor=1_540)
    r = _assess(f, sender="maya@shop.example", display="Maya Collins")
    flag = next(x for x in r.flags if x.code == "receipt_total_mismatch")
    assert flag.evidence["line_items_sum"] == "$84.60" and flag.evidence["cash_minus_change"] == "$84.60"
    assert "reimburse_line_items_only" in r.recommended


def test_instruction_and_hidden_text_from_code_alone():
    r = _assess(_invoice(), text=TextEvidence(instruction_patterns=("ignore_instructions",),
                                              hidden_reasons=("render_mode_3",)))
    assert {"instruction_like_text", "hidden_text"} <= set(r.codes) and r.risk == "hold"


@pytest.mark.parametrize("category,flagged", [("ignore_instructions", True), ("data_exfiltration", True),
                                              ("payment_or_approval_request", False)])
def test_model_instruction_flag_counts_only_when_aimed_at_an_ai(category, flagged):
    r = _assess(_invoice(model_instruction_flag=True, model_instruction_category=category))
    assert ("instruction_like_text" in r.codes) is flagged


def test_lookalike_helper():
    assert find_lookalike("goldengrain.example", KNOWN) is None
    assert find_lookalike("go1dengrain.example", KNOWN).method == "homoglyph"
    assert find_lookalike("goldengrian.example", KNOWN).method == "edit_distance"
    assert find_lookalike("goldengrain.com", KNOWN).method == "tld_swap"
    assert find_lookalike("cafe.example".replace("a", "а"), KNOWN).imitates == "cafe.example"  # Cyrillic a
    assert find_lookalike("totallydifferent.example", KNOWN) is None


# Forecast feed -------------------------------------------------------------------------------------------------

def test_flagged_mail_never_feeds_the_forecast():
    r = _assess(_invoice(payee_account_token=_u("acct_new")))
    assert plan_items("em-9", _invoice(), r, _dir(), (), date(2026, 10, 19)) == ("held_by_sentinel", [])


def test_promise_from_known_customer_is_scheduled():
    f = DocumentFields(category="promise_to_pay", referenced_invoice_numbers=("AR-5",),
                       promises=(PromiseField(date=_u(date(2026, 10, 23)), amount_minor=_u(64_280)),
                                 PromiseField(date=_u(date(2026, 10, 1)), amount_minor=_u(1))))
    r = _assess(f, sender="orders@cafe.example", display="Sunrise Cafe")
    from app.ledger.scheduled import ScheduledItem
    original = ScheduledItem(id="S1", kind="receivable", category="customer_invoice", due_date=date(2026, 8, 31),
                             amount_minor=64_280, counterparty_id="cus_cafe", reference="AR-5", source="invoice")
    outcome, items = plan_items("em-15", f, r, _dir(), (original,), date(2026, 10, 19))
    assert outcome == "scheduled" and len(items) == 1  # the past-dated promise is dropped
    assert (items[0].id, items[0].reference, items[0].source) == ("MBX-EM-15-1", "AR-5", "mailbox_promise")
