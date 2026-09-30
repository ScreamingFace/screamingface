"""The replay grant verifier (OME-1307, GW-replay): the gateway half of contract C6.

FEATURE: OME-1307 (E14) - a caller replays a frozen version only with a grant that the scoreboard
minted for that version and that caller. This module decides "yes" or "no, and why" with a reason
from a closed vocabulary.

STORY: as a benchmark reviewer I replay the run of a published result, and the gateway answers my
calls from the frozen version - and refuses anyone else's grant.

INVARIANT: PyJWT checks the signature BEFORE the claims, so a forged token never reports
``audience`` or ``expired`` (a forger learns nothing about the claims).
INVARIANT (RP-D1): a cached grant never skips the subject check or the expiry check. Only the
version lookup is cached.
INVARIANT: the token is never logged. A log line carries the reason and 12 characters of the
token's digest.

AIDEV-NOTE: the grant public keys are configuration, not secrets
(``AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS``). The error message still names the kid only, never the
value, like the receipt signer.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any, Final
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .ports import CacheVersionLookup, GrantRejected, GrantRejectReason, VerifiedGrant

logger = logging.getLogger(__name__)

MAX_GRANT_BYTES: Final = 4096
LEEWAY_S: Final = 60

_REQUIRED_CLAIMS: Final = ["iss", "aud", "sub", "vid", "rid", "iat", "exp"]
_LOG_DIGEST_LENGTH: Final = 12
_ED25519_PUBLIC_KEY_BYTES: Final = 32


def _refuse(reason: GrantRejectReason, digest: str) -> GrantRejected:
    logger.warning("replay grant refused reason=%s grant=%s…", reason, digest[:_LOG_DIGEST_LENGTH])
    return GrantRejected(reason)


class Ed25519ReplayGrantVerifier:
    def __init__(
        self,
        *,
        public_keys: Mapping[str, Ed25519PublicKey],
        lookup: CacheVersionLookup,
        cache_ttl_s: float = 60.0,
        max_cached: int = 1024,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._public_keys = public_keys
        self._lookup = lookup
        self._cache_ttl_s = cache_ttl_s
        self._max_cached = max_cached
        self._monotonic = monotonic
        self._wall = wall
        # sha256(token) -> (grant, monotonic time of the lookup). Oldest first.
        self._cache: OrderedDict[str, tuple[VerifiedGrant, float]] = OrderedDict()

    @classmethod
    def from_config(cls, keys: Mapping[str, str], **kw: Any) -> Ed25519ReplayGrantVerifier:
        """Build from the ``{kid: base64 of the raw 32-byte public key}`` map (decided: D7, X-4)."""
        public_keys: dict[str, Ed25519PublicKey] = {}
        for kid, value in keys.items():
            try:
                raw = base64.b64decode(value, validate=True)
                if len(raw) != _ED25519_PUBLIC_KEY_BYTES:
                    raise ValueError("wrong length")
                public_keys[kid] = Ed25519PublicKey.from_public_bytes(raw)
            except (binascii.Error, ValueError):
                # WHY no `from exc`-text: the message names the kid only, never the value.
                raise RuntimeError(
                    f"AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS[{kid!r}] is not base64 of a "
                    "32-byte Ed25519 public key"
                ) from None
        return cls(public_keys=public_keys, **kw)

    async def verify(self, token: str, *, caller: str | None) -> VerifiedGrant:
        """Verify ``token``. ``caller`` is None when auth is disabled (no subject check, RP-D8)."""
        digest = hashlib.sha256(token.encode()).hexdigest()
        if len(token.encode()) > MAX_GRANT_BYTES:
            raise _refuse("signature", digest)
        grant = self._cached(digest)
        if grant is None:
            grant = await self._verify_fresh(token, digest)
        # INVARIANT (RP-D1): these two checks run on EVERY call, cached or fresh.
        if self._wall() > grant.expires_at + LEEWAY_S:
            self._cache.pop(digest, None)
            raise _refuse("expired", digest)
        if caller is not None and grant.subject.strip().lower() != caller.strip().lower():
            raise _refuse("subject", digest)
        return grant

    def _cached(self, digest: str) -> VerifiedGrant | None:
        entry = self._cache.get(digest)
        if entry is None:
            return None
        grant, stamp = entry
        if self._monotonic() - stamp >= self._cache_ttl_s:
            del self._cache[digest]
            return None
        return grant

    async def _verify_fresh(self, token: str, digest: str) -> VerifiedGrant:
        claims = self._decode(token, digest)
        try:
            version_id = UUID(str(claims["vid"]))
        except ValueError:
            raise _refuse("signature", digest) from None
        subject, result_id = claims["sub"], claims["rid"]
        if not isinstance(subject, str) or not isinstance(result_id, str):
            raise _refuse("signature", digest)
        if not await self._lookup.version_exists(version_id):
            raise _refuse("unknown_version", digest)
        grant = VerifiedGrant(
            version_id=version_id,
            result_id=result_id,
            subject=subject,
            expires_at=int(claims["exp"]),
        )
        self._cache[digest] = (grant, self._monotonic())
        while len(self._cache) > self._max_cached:
            self._cache.popitem(last=False)
        return grant

    def _decode(self, token: str, digest: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError:
            raise _refuse("signature", digest) from None
        key = self._public_keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise _refuse("signature", digest)
        try:
            return jwt.decode(
                token,
                key,
                algorithms=["EdDSA"],
                audience="aigateway",
                issuer="scoreboard",
                leeway=LEEWAY_S,
                options={"require": _REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise _refuse("expired", digest) from None
        except jwt.InvalidAudienceError:
            raise _refuse("audience", digest) from None
        except jwt.InvalidTokenError:
            raise _refuse("signature", digest) from None
