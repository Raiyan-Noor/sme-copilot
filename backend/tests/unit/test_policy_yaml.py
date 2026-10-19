"""policy.yaml matches the canonical Tiers table in CLAUDE.md, and T4 stays empty (invariant 5)."""

from pathlib import Path

import yaml

POLICY = Path(__file__).resolve().parents[2] / "app" / "gateway" / "policy.yaml"

EXPECTED = {
    "T1": {"get_*", "list_*", "explain_fact", "match_financing", "get_passport", "rank_products_for_ads",
          "product_performance", "ad_budget_what_if"},
    "T2": {"send_invoice_reminder", "pay_recurring_bill"},
    "T3": {
        "submit_loan_application",
        "change_payee_details",
        "delay_supplier_payment",
        "send_supplier_message",
        "cancel_subscription",
        "pay_invoice",
        "send_email",
    },
    "T4": set(),
}


def _policy() -> dict:
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_default_is_deny():
    assert _policy()["default_decision"] == "deny"


def test_untrusted_provenance_escalates_to_t3():
    assert _policy()["untrusted_provenance"]["escalate_to"] == "T3"


def test_tiers_match_claude_md():
    tiers = _policy()["tiers"]
    assert set(tiers) == set(EXPECTED)
    for tier, tools in EXPECTED.items():
        assert set(tiers[tier]["tools"]) == tools, tier


def test_no_tool_in_two_tiers():
    tiers = _policy()["tiers"]
    seen: list[str] = [t for tier in tiers.values() for t in tier["tools"]]
    assert len(seen) == len(set(seen))


def test_t4_has_no_tools():
    assert _policy()["tiers"]["T4"]["tools"] == []


def test_anchor_is_system_only_testnet_t1():
    policy = _policy()
    anchor = policy["system_tools"]["anchor"]
    assert anchor["tier"] == "T1" and anchor["caller"] == "system"
    assert anchor["testnet_only"] is True and anchor["moves_value"] is False
    assert set(anchor["allowed_chain_ids"]) == {11155111, 84532}
    assert "anchor" not in {t for tier in policy["tiers"].values() for t in tier["tools"]}
