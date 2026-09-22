"""Short-lived signed URLs for spilled artifacts (OQ-3.2, contracts.md C6).

FEATURE (unit 3, D9): the sync caller never holds a capability token, yet a spilled
artifact must be fetchable. The node signs the artifact id together with an expiry using
a key shared with the App; the App verifies the signature as an ALTERNATIVE credential on
``GET /artifacts/{id}``. The bare route stays capability-token-only.

WHY the signature exists at all: an artifact id is a SHA-256 of the content, not a random
capability. It is guessable whenever the content is guessable, so the id alone must never
authorize a fetch — the signature, not the secrecy of the id, is the credential.

INVARIANT: the signature binds exactly two values, the artifact id and the expiry. Nothing
else may enter the signed message, because anything added is something an issuer must also
propagate through every caller, and the contract names only these two.

INVARIANT: this is a shared leaf (`artifacts` is), so it imports neither the control plane
nor the run mode: the node signs and the App verifies from the same bytes.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable

# The query-parameter names the 303 `Location` carries and the App reads back. Named here so
# the issuer and the verifier cannot spell them differently.
EXPIRY_PARAM = "exp"
SIGNATURE_PARAM = "sig"

# Domain separation: without it, a signature minted for any other use of the same key could be
# replayed as an artifact credential. The prefix is not secret — it only keeps the message
# spaces disjoint.
_DOMAIN = b"url4-artifact-v1"

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def sign_artifact_id(artifact_id: str, *, expires_at: int, key: str) -> str:
    """The lowercase hex HMAC-SHA256 over ``id + expiry`` under ``key``.

    Raises:
        ValueError: when ``key`` is empty. An empty key is not a weak key to be tolerated —
            it is a missing configuration, and signing with it would mint a credential any
            caller could reproduce. Verification refuses an empty key for the same reason.
    """
    if not key:
        raise ValueError("artifact signing key is empty — signed URLs cannot be issued")
    message = _message(artifact_id, expires_at)
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_artifact_path(
    artifact_id: str,
    *,
    key: str,
    ttl_s: int,
    now: Callable[[], float],
) -> str:
    """The relative ``Location`` for a spilled artifact: id + expiry + signature.

    WHY a relative path and not an absolute URL: the node does not know the public origin the
    caller used (the App owns that), and the App rewrites only if its artifact path differs
    (contracts.md C2). A relative `/artifacts/...` survives both placements unchanged.
    """
    expires_at = int(now()) + int(ttl_s)
    signature = sign_artifact_id(artifact_id, expires_at=expires_at, key=key)
    return f"/artifacts/{artifact_id}?{EXPIRY_PARAM}={expires_at}&{SIGNATURE_PARAM}={signature}"


def verify_artifact_signature(
    artifact_id: str,
    *,
    exp: str | None,
    sig: str | None,
    key: str,
    now: float,
) -> bool:
    """Whether ``sig`` is a valid, unexpired signature for ``artifact_id``.

    INVARIANT: the comparison is constant-time (`hmac.compare_digest`). A signature check
    that leaked its mismatch position through timing would let a caller recover a valid
    signature byte by byte.

    The expiry is inclusive: a signature is valid while ``now <= expires_at``. An absent or
    unparseable expiry, an empty key, a ``sig`` that is not ASCII hex, and any mismatch all
    answer ``False`` — this function never raises, so a malformed query string can only mean
    "not signed", never a 500.
    """
    if not key or not sig or not _is_hex(sig):
        return False
    expires_at = _parse_expiry(exp)
    if expires_at is None or now > expires_at:
        return False
    expected = hmac.new(key.encode("utf-8"), _message(artifact_id, expires_at), hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), sig)


def _is_hex(sig: str) -> bool:
    """Whether ``sig`` is ASCII hex — the only shape `sign_artifact_id` ever issues.

    WHY checked before the comparison: `hmac.compare_digest` raises ``TypeError`` for a ``str``
    with non-ASCII characters, and ``sig`` is caller-controlled (FX-10). Rejecting the shape
    first keeps the never-raises contract without weakening the constant-time comparison.
    """
    return sig.isascii() and all(char in _HEX_DIGITS for char in sig)


def _parse_expiry(exp: str | None) -> int | None:
    """The expiry as an int, or None when it is absent or not a number."""
    if exp is None:
        return None
    try:
        return int(exp)
    except (TypeError, ValueError):
        return None


def _message(artifact_id: str, expires_at: int) -> bytes:
    """The exact signed bytes: a domain tag, the id, and the decimal expiry.

    The `:` separators make the two fields unambiguous (``a`` + ``12`` and ``a1`` + ``2``
    must not sign the same bytes).
    """
    return b":".join((_DOMAIN, artifact_id.encode("utf-8"), str(expires_at).encode("ascii")))


__all__ = [
    "EXPIRY_PARAM",
    "SIGNATURE_PARAM",
    "sign_artifact_id",
    "signed_artifact_path",
    "verify_artifact_signature",
]
