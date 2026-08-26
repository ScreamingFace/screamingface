"""HS256 JWT minting and verification for screamingface-engine capability tokens.

A capability token binds a client to a topic (the WS/stream routing key). Lifetime is
carried by the standard ``exp`` claim (``iat + capability_lifetime_s``); the ``iat``
window guards only clock skew (a mint from the future). See :meth:`JwtCodec.verify`.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime

import jwt as pyjwt

from screamingface_engine.auth.errors import (
    IatWindowExceeded,
    InvalidToken,
    MissingIat,
    TokenExpired,
)

_ALGORITHM = "HS256"
_JTI_BYTES = 16


@dataclass(frozen=True)
class JwtCodec:
    """Symmetric (HS256) signer/verifier for capability tokens, bound to a
    shared secret and an iat acceptance window.
    """

    # AIDEV-NOTE: `secret` is signing key material — never log it, include it in an
    # error/problem detail, or otherwise let it leak to a client-facing response.
    secret: str
    iat_window_s: int
    # Run-horizon token lifetime (D1, OME-1016): `exp = iat + lifetime` at mint, so a Run's
    # owner can re-attach, stop, or redeem for the Run's whole life (up to 16 h + slack).
    capability_lifetime_s: int

    def sign(self, topic: str, now: datetime) -> str:
        """Mint a capability token for `topic`, stamped with `now` as issued-at
        and expiring after `capability_lifetime_s` seconds.
        """
        iat = int(now.timestamp())
        payload = {
            "sub": topic,
            "iat": iat,
            "exp": iat + self.capability_lifetime_s,
            "jti": secrets.token_hex(_JTI_BYTES),
        }
        return pyjwt.encode(payload, self.secret, algorithm=_ALGORITHM)

    def verify(self, token: str, now: datetime) -> dict[str, object]:
        """Verify signature and freshness, returning the decoded claims.

        Raises:
            InvalidToken: token is malformed or its signature does not verify.
            MissingIat: token has no ``iat`` claim.
            IatWindowExceeded: ``iat`` is more than `iat_window_s` in the FUTURE
                (clock skew only — lifetime is the ``exp`` claim alone).
            TokenExpired: the token's ``exp`` claim has passed.
        """
        try:
            # WHY: exp is not trusted to pyjwt's own clock; it — and the iat skew check
            # below — are checked manually against the caller-supplied `now`, so
            # verification stays deterministic and testable under a fake Clock.
            claims = pyjwt.decode(
                token, self.secret, algorithms=[_ALGORITHM], options={"verify_exp": False}
            )
        except pyjwt.InvalidTokenError as exc:
            raise InvalidToken("token is malformed or its signature is invalid") from exc

        if "iat" not in claims:
            raise MissingIat("token has no iat claim")
        now_s = int(now.timestamp())
        iat = int(claims["iat"])
        # INVARIANT (OME-1018): the iat check is FRESHNESS ONLY — a future mint is clock
        # skew, not a valid credential. It never bounds lifetime; `exp` is the only
        # lifetime rule, so a Run's capability outlives its 60 s mint window.
        if iat - now_s > self.iat_window_s:
            raise IatWindowExceeded("token iat is outside the acceptance window")
        exp = claims.get("exp")
        # INVARIANT: valid requires now < exp (RFC 7519); at now == exp the token is expired.
        if exp is not None and now_s >= int(exp):
            raise TokenExpired("token has expired")
        return claims
