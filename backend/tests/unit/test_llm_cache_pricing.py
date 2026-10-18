"""Generic request cache (shared with the anchoring RPC mock later), pricing and the strict schema helper."""

import json

import pytest
from pydantic import BaseModel

from app.llm.cache import ReplayMiss, RequestCache
from app.llm.pricing import CONSERVATIVE, cost_microusd, price_for
from app.llm.schema import strict_json_schema
from app.llm.types import Usage


def test_cache_modes(tmp_path):
    calls = []

    def call():
        calls.append(1)
        return {"tx": "0xabc"}

    content = {"method": "eth_sendRawTransaction", "params": ["0xdead"]}
    with pytest.raises(ReplayMiss):
        RequestCache(tmp_path, "replay").fetch("rpc", content, call)
    assert RequestCache(tmp_path, "off").fetch("rpc", content, call).status == "off"
    assert not (tmp_path / "rpc").exists()
    rec = RequestCache(tmp_path, "record").fetch("rpc", content, call)
    assert rec.status == "miss"
    stored = json.loads((tmp_path / "rpc" / f"{rec.key}.json").read_text(encoding="utf-8"))
    assert stored["request"] == content and stored["response"] == {"tx": "0xabc"}
    hit = RequestCache(tmp_path, "replay").fetch("rpc", content, call)
    assert hit.status == "hit" and hit.response == {"tx": "0xabc"}
    assert len(calls) == 2


def test_key_is_order_independent_and_namespaced():
    a = RequestCache.key("llm", {"x": 1, "y": [1, 2]})
    assert a == RequestCache.key("llm", {"y": [1, 2], "x": 1})
    assert a != RequestCache.key("rpc", {"x": 1, "y": [1, 2]})
    with pytest.raises(ValueError):
        RequestCache.key("../etc", {})


def test_pricing_rounds_up_and_discounts_cached_input():
    assert cost_microusd("gpt-5.6-terra", Usage(input_tokens=1)) == 2
    assert cost_microusd("gpt-5.6-terra", Usage(input_tokens=1000, cached_input_tokens=1000)) == 200
    assert cost_microusd("gpt-5.6-sol", Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == 35_000_000
    assert cost_microusd("gemini-2.5-flash", Usage(output_tokens=3)) == 8  # 7.5 rounded up


def test_unknown_model_is_priced_conservatively():
    price, known = price_for("gpt-9-mystery")
    assert not known and price == CONSERVATIVE
    assert price_for("gpt-5.6-terra-2026-08-01") == price_for("gpt-5.6-terra")


class Inner(BaseModel):
    title: str
    default: int = 3


class Outer(BaseModel):
    inner: Inner
    note: str | None = None


def test_strict_schema_keeps_field_names_and_closes_objects():
    schema = strict_json_schema(Outer)
    inner = schema["$defs"]["Inner"]
    assert inner["required"] == ["title", "default"] and inner["additionalProperties"] is False
    assert "default" not in inner["properties"]["default"]
    assert schema["required"] == ["inner", "note"]
