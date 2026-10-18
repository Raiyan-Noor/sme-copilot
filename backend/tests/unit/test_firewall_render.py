"""Fact store and placeholder renderer (invariant 4)."""

from datetime import date

import pytest

from app.firewall import (
    Fact,
    FactConflictError,
    FactStore,
    FirewallViolation,
    Segment,
    UnknownFactError,
    ViolationKind,
    render,
)


def fact(fact_id: str = "cash_balance", value=125_000, display: str = "1,250.00", **kw) -> Fact:
    kw.setdefault("unit", "money")
    kw.setdefault("currency", "USD" if kw["unit"] == "money" else None)
    kw.setdefault("source_row_ids", ("txn_1", "txn_2"))
    return Fact(id=fact_id, value=value, display=display, computed_by="test", **kw)


@pytest.fixture
def store() -> FactStore:
    s = FactStore()
    s.add(fact())
    s.add(fact("payroll_due_date", value=date(2026, 10, 20), unit="date", display="Tue 20 Oct"))
    return s


# --- store --------------------------------------------------------------------------------------------------------


def test_store_get_and_contains(store):
    assert "cash_balance" in store
    assert store.get("cash_balance").source_row_ids == ("txn_1", "txn_2")
    assert len(store) == 2
    assert store.ids() == {"cash_balance", "payroll_due_date"}


def test_store_unknown_id_raises(store):
    with pytest.raises(UnknownFactError):
        store.get("nope")


def test_store_identical_readd_is_noop():
    seen = []
    s = FactStore(on_add=seen.append)
    s.add(fact())
    s.add(fact())
    assert len(s) == 1
    assert len(seen) == 1


def test_store_conflicting_readd_raises(store):
    with pytest.raises(FactConflictError):
        store.add(fact(value=999, display="9.99"))
    assert store.get("cash_balance").value == 125_000


def test_stores_are_independent_per_request(store):
    assert "cash_balance" not in FactStore()


# --- render -------------------------------------------------------------------------------------------------------


def test_render_substitutes_display(store):
    out = render("Cash is {fact:cash_balance}; payroll due {fact:payroll_due_date}.", store)
    assert out.text == "Cash is 1,250.00; payroll due Tue 20 Oct."
    assert out.fact_ids == ("cash_balance", "payroll_due_date")
    assert out.segments == (
        Segment("Cash is "),
        Segment("1,250.00", "cash_balance"),
        Segment("; payroll due "),
        Segment("Tue 20 Oct", "payroll_due_date"),
        Segment("."),
    )


def test_render_plain_text(store):
    out = render("Nothing to report.", store)
    assert out.text == "Nothing to report."
    assert out.segments == (Segment("Nothing to report."),)


def test_render_rejects_digits(store):
    with pytest.raises(FirewallViolation) as exc:
        render("Cash is {fact:cash_balance}, about 1,250.", store)
    assert {v.kind for v in exc.value.result.violations} == {ViolationKind.DIGIT}


def test_render_rejects_unknown_fact(store):
    with pytest.raises(FirewallViolation) as exc:
        render("Runway is {fact:runway_days}.", store)
    assert [v.kind for v in exc.value.result.violations] == [ViolationKind.UNKNOWN_FACT]


def test_render_rejects_malformed_placeholder(store):
    with pytest.raises(FirewallViolation):
        render("Cash is {fact: cash_balance}.", store)


def test_render_is_single_pass():
    """A display string that looks like a placeholder is shown as-is, never resolved again."""
    s = FactStore()
    s.add(fact("a", value=1, unit="count", display="{fact:b}"))
    s.add(fact("b", display="secret"))
    assert render("{fact:a}", s).text == "{fact:b}"
