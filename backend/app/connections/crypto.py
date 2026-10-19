"""Encryption at rest for connection secrets (the Gmail refresh token).

XSalsa20-Poly1305 (PyNaCl SecretBox) with a 32-byte key from GMAIL_TOKEN_KEY in .env. A refresh token is stored only
as this ciphertext; it is decrypted in memory to call Google and is never returned by the API, logged or handed to
the LLM (invariant 2 keeps the planner away from connection state entirely).
"""

import nacl.exceptions
import nacl.secret


class TokenKeyMissing(RuntimeError):
    pass


class TokenCipher:
    def __init__(self, key_hex: str):
        try:
            key = bytes.fromhex(key_hex.strip())
        except ValueError:
            key = b""
        if len(key) != nacl.secret.SecretBox.KEY_SIZE:
            raise TokenKeyMissing("GMAIL_TOKEN_KEY must be 64 hex characters (32 bytes)")
        self._box = nacl.secret.SecretBox(key)

    def encrypt(self, plaintext: str) -> bytes:
        return bytes(self._box.encrypt(plaintext.encode()))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._box.decrypt(ciphertext).decode()
        except nacl.exceptions.CryptoError as exc:
            raise TokenKeyMissing("stored token cannot be decrypted with GMAIL_TOKEN_KEY") from exc
