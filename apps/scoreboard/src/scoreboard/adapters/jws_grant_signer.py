"""Ed25519 JWS signer for the replay grant (C6). PyJWT stays in this adapter.

FEATURE: OME-1307 (E14) replay grants.
INVARIANT: the key never leaves this module. No exception message or log line holds key text.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ED25519_RAW_BYTES = 32
_ALGORITHM = "EdDSA"
_BAD_KEY = "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY must be base64 of a 32-byte Ed25519 private key"


class Ed25519GrantSigner:
    def __init__(self, private_key: Ed25519PrivateKey, kid: str) -> None:
        self._key = private_key
        self._kid = kid

    @classmethod
    def from_config(cls, key_b64: str, kid: str) -> Ed25519GrantSigner:
        """`key_b64` is standard base64 of the RAW 32-byte private key (the seed)."""
        try:
            raw = base64.b64decode(key_b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(_BAD_KEY) from None
        if len(raw) != _ED25519_RAW_BYTES:
            raise ValueError(_BAD_KEY)
        return cls(Ed25519PrivateKey.from_private_bytes(raw), kid)

    def sign(self, claims: Mapping[str, object]) -> str:
        return jwt.encode(dict(claims), self._key, algorithm=_ALGORITHM, headers={"kid": self._kid})
