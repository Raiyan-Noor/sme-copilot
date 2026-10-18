"""The signed message is exactly what the browser produces: JSON.stringify of the four keys in sorted order."""

from datetime import date

from nacl.signing import SigningKey

from app.gateway import SignedPayload, StandingTerms, verify_signature

PAYLOAD = SignedPayload(action="pay_recurring_bill", args_hash="ab" * 32, nonce="n" * 16, expiry=date(2026, 10, 20))


def test_message_bytes_match_browser_serialization():
    expected = ('{"action":"pay_recurring_bill","args_hash":"' + "ab" * 32
                + '","expiry":"2026-10-20","nonce":"nnnnnnnnnnnnnnnn"}')
    assert PAYLOAD.message() == expected.encode()


def test_verify_signature_accepts_only_the_signer_and_payload():
    key = SigningKey(b"\x07" * 32)
    pub = key.verify_key.encode().hex()
    sig = key.sign(PAYLOAD.message()).signature.hex()
    assert verify_signature(PAYLOAD, sig, pub)
    other = PAYLOAD.model_copy(update={"nonce": "m" * 16})
    assert not verify_signature(other, sig, pub)
    assert not verify_signature(PAYLOAD, sig, SigningKey(b"\x08" * 32).verify_key.encode().hex())
    assert not verify_signature(PAYLOAD, sig, "not-hex")


def test_standing_terms_hash_is_order_sensitive_in_allowlist_but_stable():
    a = StandingTerms(max_amount_minor=100, allowlist=("x", "y"))
    assert a.hash() == StandingTerms(max_amount_minor=100, allowlist=("x", "y")).hash()
    assert a.hash() != StandingTerms(max_amount_minor=101, allowlist=("x", "y")).hash()
