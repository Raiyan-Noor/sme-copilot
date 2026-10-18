"""docs/openapi.json is the frontend's contract: it must match the app exactly, and every route but /health must
require the passcode. The local signing helper produces signatures the gateway accepts."""

import importlib.util
import json
import os
from pathlib import Path

from app.gateway import SignedPayload, verify_signature

ROOT = Path(__file__).resolve().parents[3]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_openapi_matches_the_app():
    exporter = _script("export_openapi")
    committed = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")
    assert json.loads(committed) == exporter.build_schema(), "run `make openapi` and commit docs/openapi.json"


def test_openapi_declares_passcode_for_everything_but_health():
    schema = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert schema["security"] == [{"Passcode": []}]
    for path, ops in schema["paths"].items():
        for op in ops.values():
            assert "security" not in op or path == "/health", path
    operation_ids = [op["operationId"] for ops in schema["paths"].values() for op in ops.values()]
    assert len(operation_ids) == len(set(operation_ids))


def test_sign_payload_script_signs_what_the_gateway_verifies(capsys, monkeypatch):
    signer = _script("sign_payload")
    monkeypatch.setitem(os.environ, "OWNER_TEST_SEED", "11" * 32)
    signer.main(["pubkey"])
    public_key = capsys.readouterr().out.strip()
    payload = SignedPayload(action="cancel_subscription", args_hash="a" * 64, nonce="n" * 16, expiry="2026-10-20")
    signer.main(["sign", payload.message().decode()])
    signature = capsys.readouterr().out.strip()
    assert verify_signature(payload, signature, public_key)
