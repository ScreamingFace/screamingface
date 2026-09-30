"""Ed25519 JWS verifier for the cache-version receipt (C3). PyJWT stays in this adapter.

FEATURE: OME-1307 (E14). INVARIANT: the reason is the only detail that leaves this module. Never
put the token, a claim value or key material into an exception message or a log line.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scoreboard.core.submissions.receipts import ReceiptClaims, ReceiptRejected

_ED25519_RAW_BYTES = 32
_ALGORITHM = "EdDSA"
_AUDIENCE = "scoreboard"
_ISSUER = "aigateway"
# WHY 60: the same skew allowance as C6. The gateway clock can be ahead of this one, and the
# receipt has no `exp` (C3), so nothing else bounds `iat`.
_LEEWAY_S = 60
_REQUIRED = ["iss", "aud", "sub", "vid", "tid", "sha", "n", "c", "cov", "iat"]
_TID = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _public_key(kid: str, value: str) -> Ed25519PublicKey:
    message = (
        f"SCOREBOARD_RECEIPT_PUBLIC_KEYS[{kid!r}] is not base64 of a 32-byte Ed25519 public key"
    )
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(message) from None
    if len(raw) != _ED25519_RAW_BYTES:
        raise ValueError(message)
    return Ed25519PublicKey.from_public_bytes(raw)


def _is_count(value: object) -> bool:
    # `bool` is an `int` in Python; a receipt with `"n": true` is malformed.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _claims_from(payload: Mapping[str, Any]) -> ReceiptClaims | None:
    """The typed claims, or None when any claim has the wrong shape."""
    sub, tid, sha, cov = payload["sub"], payload["tid"], payload["sha"], payload["cov"]
    iat = payload["iat"]
    shapes_ok = (
        isinstance(sub, str)
        and bool(sub)
        and isinstance(tid, str)
        and _TID.match(tid) is not None
        and isinstance(sha, str)
        and _SHA.match(sha) is not None
        and _is_count(payload["n"])
        and _is_count(payload["c"])
        and cov in ("complete", "partial")
        and isinstance(iat, int)
        and not isinstance(iat, bool)
    )
    if not shapes_ok:
        return None
    try:
        vid = UUID(str(payload["vid"]))
    except ValueError:
        return None
    return ReceiptClaims(
        sub=sub, vid=vid, tid=tid, sha=sha, n=payload["n"], c=payload["c"], cov=cov, iat=iat
    )


class Ed25519ReceiptVerifier:
    def __init__(self, public_keys: Mapping[str, Ed25519PublicKey]) -> None:
        self._keys = dict(public_keys)

    @classmethod
    def from_config(cls, raw: Mapping[str, str]) -> Ed25519ReceiptVerifier:
        return cls({kid: _public_key(kid, value) for kid, value in raw.items()})

    def verify(self, token: str) -> ReceiptClaims:
        key = self._key_for(token)
        payload = self._decode(token, key)
        claims = _claims_from(payload)
        if claims is None:
            raise ReceiptRejected("malformed")
        return claims

    def _key_for(self, token: str) -> Ed25519PublicKey:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise ReceiptRejected("malformed") from None
        if header.get("alg") != _ALGORITHM:
            raise ReceiptRejected("bad_alg")
        kid = header.get("kid")
        if not isinstance(kid, str) or kid not in self._keys:
            raise ReceiptRejected("unknown_kid")
        return self._keys[kid]

    def _decode(self, token: str, key: Ed25519PublicKey) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[_ALGORITHM],
                audience=_AUDIENCE,
                issuer=_ISSUER,
                leeway=_LEEWAY_S,
                options={"require": _REQUIRED},
            )
        except jwt.InvalidSignatureError:
            raise ReceiptRejected("bad_signature") from None
        except jwt.InvalidAudienceError:
            raise ReceiptRejected("bad_audience") from None
        except jwt.InvalidIssuerError:
            raise ReceiptRejected("bad_issuer") from None
        except jwt.InvalidTokenError:
            raise ReceiptRejected("malformed") from None
