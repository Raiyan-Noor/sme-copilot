"""The skill library key: Ed25519, verified with PyNaCl. A skill signed with it gets the "Verified" badge.

Only the public key is in the code. The signing seed is kept by the library maintainer in `.env`
(`SKILL_LIBRARY_SIGNING_KEY`, used by scripts/sign_skill.py) and never reaches the server at run time.

What is signed is `SIGNED_PREFIX + <skill sha256 hex>`, where the sha256 covers the skill file without its
`signature:` line (packs/skill.py `skill_content`). The prefix is domain separation: a library signature can never be
replayed as an owner mandate signature or the other way round.
"""

import base64
import binascii

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

LIBRARY_PUBLIC_KEY = "539ab84a0b2fca0f430af4721768e26f6249f469f582bec6482f62ff7b6418c6"
SIGNED_PREFIX = b"skill-library-v1:"
SIGNATURE_SCHEME = "ed25519:"


def signed_message(sha256_hex: str) -> bytes:
    return SIGNED_PREFIX + sha256_hex.encode("ascii")


def verify(sha256_hex: str, signature: str | None, public_key_hex: str = LIBRARY_PUBLIC_KEY) -> bool:
    """True only for a well-formed `ed25519:<base64>` signature by the library key over this skill hash."""
    if not signature or not signature.startswith(SIGNATURE_SCHEME):
        return False
    try:
        sig = base64.b64decode(signature[len(SIGNATURE_SCHEME):], validate=True)
        VerifyKey(bytes.fromhex(public_key_hex)).verify(signed_message(sha256_hex), sig)
        return True
    except (BadSignatureError, binascii.Error, ValueError, TypeError):
        return False


def sign(sha256_hex: str, seed_hex: str) -> str:
    """The `signature:` value for a skill hash (maintainer tooling only)."""
    sig = SigningKey(bytes.fromhex(seed_hex)).sign(signed_message(sha256_hex)).signature
    return SIGNATURE_SCHEME + base64.b64encode(sig).decode("ascii")
