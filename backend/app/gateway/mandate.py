"""Signed mandates: the owner's Ed25519 signature over {action, args_hash, nonce, expiry} (invariant 6).

The owner's private key lives only in the browser (tweetnacl). The server sees public keys and detached
signatures, and verifies them here with PyNaCl. The signed message is the canonical JSON of `SignedPayload`, so the
browser produces the same bytes with `JSON.stringify` over the four keys in sorted order.

Two kinds of mandate use the same envelope:
- approval (T3): `args_hash` is the hash of the exact action arguments; the owner signs one action, once.
- standing (T2): `args_hash` is the hash of `StandingTerms` (caps and allow-list); the owner delegates a bounded
  class of actions until `expiry`.

Nonces are single-use (see store.NonceStore). Expiry is an inclusive simulated-clock date.
"""

from datetime import date
from typing import Literal

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pydantic import BaseModel, ConfigDict, Field

from app.audit.canonical import canonical_hash, canonical_json

HEX64 = r"^[0-9a-f]{64}$"
NONCE = r"^[A-Za-z0-9_\-]{16,128}$"


class SignedPayload(BaseModel):
    """Exactly what the owner signs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    args_hash: str = Field(pattern=HEX64)
    nonce: str = Field(pattern=NONCE)
    expiry: date

    def message(self) -> bytes:
        """Canonical bytes that are signed and verified. `expiry` is an ISO date string."""
        return canonical_json(self.model_dump(mode="json"))


class StandingTerms(BaseModel):
    """What a T2 standing mandate delegates: a cap (never above policy.yaml) and an allow-list of IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_amount_minor: int = Field(ge=0)
    allowlist: tuple[str, ...] = Field(min_length=1)

    def hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class MandateRecord(BaseModel):
    """A verified, stored mandate. `record_hash` is the canonical-JSON hash of `document()`, the anchoring leaf."""

    id: int
    kind: Literal["approval", "standing"]
    payload: SignedPayload
    signature: str
    public_key: str
    terms: StandingTerms | None = None
    signed_on: date
    record_hash: str

    def document(self) -> dict:
        return mandate_document(self.kind, self.payload, self.signature, self.public_key, self.terms)


def mandate_document(
    kind: str, payload: SignedPayload, signature: str, public_key: str, terms: StandingTerms | None
) -> dict:
    """The canonical document of a signed mandate. Hash it with canonical_hash to get the anchoring leaf."""
    doc = {
        "kind": kind,
        "payload": payload.model_dump(mode="json"),
        "signature": signature,
        "public_key": public_key,
    }
    if terms is not None:
        doc["terms"] = terms.model_dump(mode="json")
    return doc


def args_hash(args: dict) -> str:
    """Hash of action argument values (no provenance): what a T3 approval binds the owner's signature to."""
    return canonical_hash(args)


def verify_signature(payload: SignedPayload, signature_hex: str, public_key_hex: str) -> bool:
    """True only if `signature_hex` is a valid Ed25519 signature by `public_key_hex` over `payload.message()`."""
    try:
        key = VerifyKey(bytes.fromhex(public_key_hex))
        key.verify(payload.message(), bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
