"""Ad advisor planner tools (P7) end to end: rank_products_for_ads, product_performance, ad_budget_what_if,
against a freshly onboarded fashion business loaded from the onboarding sample data (the seeded businesses carry
no ad spend at all). Multi-turn follow-ups ("why not X?", "what if I move budget?") reuse the conversation's
fact IDs and product/campaign IDs, the same way test_agent_financing.py checks a draft-then-propose follow-up."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import PASSCODE_HEADER, create_app
from tests.agent_env import FakeLLM, calls, text
from tests.helpers import TEST_PASSCODE, make_settings

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "fashion_shop"


def _onboard(client: TestClient) -> str:
    bid = client.post("/onboarding", json={"name": "Rosa & Thread", "business_type": "a small clothing boutique",
                                           "currency": "USD"}).json()["id"]
    for name in ("products.csv", "sales.csv", "ad_spend.csv", "bank.csv"):
        with (SAMPLES / name).open("rb") as f:
            r = client.post(f"/businesses/{bid}/onboarding/uploads", files={"file": (name, f.read())})
            assert r.status_code == 200, r.text
    assert client.post(f"/businesses/{bid}/onboarding/finish").status_code == 200
    return bid


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory):
    from data.seed.generate import generate

    out = tmp_path_factory.mktemp("generated")
    generate(out)
    return out


@pytest.fixture
def business(seed_dir, tmp_path):
    app = create_app(make_settings(data_dir=tmp_path / "tenants", seed_dir=seed_dir))
    client = TestClient(app, headers={PASSCODE_HEADER: TEST_PASSCODE})
    bid = _onboard(client)
    llm = FakeLLM()
    client.app.state.runtime._llm = llm
    return client, bid, llm


def ask(client, bid, message, conversation_id=None):
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    r = client.post(f"/businesses/{bid}/agent/ask", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def results(llm, idx=-1):
    return [json.loads(m["content"]) for m in llm.requests[idx] if m["role"] == "tool"]


def test_rank_products_for_ads_matches_the_planted_traps(business):
    client, bid, llm = business
    llm.steps += [calls(("rank_products_for_ads", {})), text("Promote the kurta more.")]
    ask(client, bid, "Which product should I advertise more?")
    [result] = results(llm)

    assert result["worth_promoting_more"][0]["product_id"] == "KURTA-COT"
    excluded = {e["product_id"]: {r["reason"] for r in e["exclusion_reasons"]} for e in result["excluded"]}
    assert "low_stock_cover" in excluded["LINEN-SHIRT"]
    assert "negative_profit_after_ads" in excluded["SLIM-CHINO"]
    assert {c["campaign_id"] for c in result["campaigns"]} >= {"summer-linen-sale", "festive-kurta-push"}

    flat = re.sub(r"\{fact:[^}]*\}", "", json.dumps(result))
    flat = re.sub(r'"(product_id|campaign_id)": "[^"]*"', "", flat)
    assert not re.search(r"\d", flat), flat


def test_why_not_follow_up_uses_product_performance(business):
    client, bid, llm = business
    llm.steps += [calls(("rank_products_for_ads", {})), text("The linen shirt sells well but is almost out.")]
    first = ask(client, bid, "Which product should I advertise more?")

    llm.steps += [calls(("product_performance", {"product_id": "LINEN-SHIRT"})),
                 text("It's almost out of stock, so restock before advertising it more.")]
    ask(client, bid, "Why not the linen shirt?", first["conversation_id"])
    result = results(llm)[-1]
    assert result["product_id"] == "LINEN-SHIRT"
    assert "low_stock_cover" in {r["reason"] for r in result["exclusion_reasons"]}
    assert "gross_margin_last_quarter" in result and result["gross_margin_last_quarter"].startswith("{fact:")


def test_product_performance_without_an_id_defaults_to_the_top_ranked_product(business):
    client, bid, llm = business
    llm.steps += [calls(("product_performance", {})), text("Your best performer is the kurta.")]
    ask(client, bid, "How is my best-advertised product doing?")
    [result] = results(llm)
    assert result["product_id"] == "KURTA-COT"


def test_ad_budget_what_if_is_a_range_and_caps_to_historical_spend(business):
    client, bid, llm = business
    llm.steps += [calls(("ad_budget_what_if", {"from_campaign_id": "summer-linen-sale",
                                               "to_campaign_id": "festive-kurta-push", "amount_minor": 500_000})),
                 text("That would help, within limits.")]
    ask(client, bid, "What if I move $5,000 from the linen sale to the kurta campaign?")
    [result] = results(llm)
    assert result["from_campaign_id"] == "summer-linen-sale" and result["to_campaign_id"] == "festive-kurta-push"
    assert result["capped_to_historical_spend"] is True
    for key in ("amount_requested", "amount_applied", "return_on_ad_spend_from", "return_on_ad_spend_to",
               "estimated_gross_profit_change_low", "estimated_gross_profit_change_high"):
        assert result[key].startswith("{fact:"), key


def test_unknown_campaign_id_is_a_clean_error(business):
    client, bid, llm = business
    llm.steps += [calls(("ad_budget_what_if", {"from_campaign_id": "made-up", "to_campaign_id": "festive-kurta-push",
                                               "amount_minor": 1000})),
                 text("I couldn't find that campaign.")]
    ask(client, bid, "What if I move money from a campaign called made-up?")
    [result] = results(llm)
    assert result == {"error": "unknown campaign_id; call rank_products_for_ads first for valid campaign_ids"}
