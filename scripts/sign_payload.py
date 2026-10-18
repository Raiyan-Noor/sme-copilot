"""Sign gateway payloads locally, for testing the approval flow from FastAPI's /docs.

Stands in for the browser (invariant 6): the private key stays on this machine and is never sent to the server.
Only the public key and signatures are pasted into /docs. Use a throwaway test key, never a real owner's key.

  python scripts/sign_payload.py keygen              print a fresh random seed (keep it; export it as below)
  export OWNER_TEST_SEED=<64 hex chars>
  python scripts/sign_payload.py pubkey              public key to enroll (POST .../gateway/owner-key)
  python scripts/sign_payload.py sign '<message>'    signature for the `message` field of an approval or a
                                                     standing-mandate draft (paste it exactly, including quotes)
"""

import os
import secrets
import sys

from nacl.signing import SigningKey

USAGE = __doc__.split("\n\n", 2)[2]


def _key() -> SigningKey:
    seed = os.environ.get("OWNER_TEST_SEED", "")
    if len(seed) != 64:
        sys.exit("set OWNER_TEST_SEED to 64 hex chars (run `keygen` for one)")
    return SigningKey(bytes.fromhex(seed))


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else ""
    if cmd == "keygen":
        print(secrets.token_hex(32))
    elif cmd == "pubkey":
        print(_key().verify_key.encode().hex())
    elif cmd == "sign" and len(argv) == 2:
        print(_key().sign(argv[1].encode("utf-8")).signature.hex())
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
