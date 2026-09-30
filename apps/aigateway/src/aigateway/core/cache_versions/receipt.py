"""The receipt signer: an EdDSA JWS over a frozen version (OME-1307, GW-freeze; contract C3).

FEATURE: OME-1307 (E14) - the gateway signs a receipt that attests one fact about an immutable
version: this account froze this trace into this archive hash. The scoreboard verifies it.

INVARIANT: the signing key and its raw bytes never appear in a log, an exception text or a repr.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from .ports import ReceiptClaims

_RAW_KEY_BYTES = 32
_KEY_ERROR = "AIGATEWAY_RECEIPT_SIGNING_KEY must be base64 of a 32-byte Ed25519 private key"


class Ed25519ReceiptSigner:
    def __init__(
        self,
        private_key: Ed25519PrivateKey,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._key = private_key
        self._now = now
        # WHY derived (decided: D7, X-4): the kid is the first 16 hex chars of the sha256 of the raw
        # public key, so no second env var can drift from the key. The public key is not a secret.
        raw_public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self._kid = hashlib.sha256(raw_public).hexdigest()[:16]

    @classmethod
    def from_base64(cls, secret: SecretStr, **kw: Any) -> Ed25519ReceiptSigner:
        # INVARIANT: every failure raises the SAME message, and it never holds the value. The
        # `from None` drops the chained cause, whose text can quote the input.
        try:
            raw = base64.b64decode(secret.get_secret_value(), validate=True)
        except (binascii.Error, ValueError):
            raise RuntimeError(_KEY_ERROR) from None
        if len(raw) != _RAW_KEY_BYTES:
            raise RuntimeError(_KEY_ERROR)
        return cls(Ed25519PrivateKey.from_private_bytes(raw), **kw)

    @property
    def kid(self) -> str:
        return self._kid

    def sign(self, claims: ReceiptClaims) -> str:
        # INVARIANT (C3): no `exp`. A receipt attests a fact about an immutable version.
        payload = {
            "iss": "aigateway",
            "aud": "scoreboard",
            "sub": claims.sub,
            "vid": str(claims.vid),
            "tid": claims.tid,
            "sha": claims.sha,
            "n": claims.n,
            "c": claims.c,
            "cov": claims.cov,
            "iat": int(self._now().timestamp()),
        }
        return jwt.encode(payload, self._key, algorithm="EdDSA", headers={"kid": self._kid})
