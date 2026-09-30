"""The cache-version receipt port (C3, scoreboard side).

FEATURE: OME-1307 (E14) — the gateway signs a receipt for a frozen cache version; the scoreboard
verifies it and stores the five I-R1 columns. INVARIANT: pure. Standard library only. The
signature check lives in `adapters/jws_receipt_verifier.py`, behind `ReceiptVerifier`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

RejectReason = Literal[
    "malformed", "bad_alg", "unknown_kid", "bad_signature", "bad_audience", "bad_issuer"
]


@dataclass(frozen=True, slots=True)
class ReceiptClaims:
    sub: str
    vid: UUID
    tid: str  # 32 lowercase hex
    sha: str  # 64 lowercase hex
    n: int
    c: int
    cov: Literal["complete", "partial"]
    iat: int


class ReceiptRejected(Exception):
    """INVARIANT: `reason` is the only detail that leaves the verifier. Never a token or a key."""

    def __init__(self, reason: RejectReason) -> None:
        super().__init__(reason)
        self.reason: RejectReason = reason


class ReceiptNotYours(Exception):
    """The receipt was issued for another trace or another user (-> 403 cache_version_not_yours)."""


class ReceiptVerifier(Protocol):
    def verify(self, token: str) -> ReceiptClaims: ...


def _same_user(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left.strip().casefold() == right.strip().casefold()


def check_receipt_binding(
    claims: ReceiptClaims, *, submitter: str | None, trace_id: str | None, check_subject: bool
) -> None:
    """Raise ReceiptNotYours when `tid` differs from the report's trace id, or (when
    `check_subject`) when `sub` is not the submitter.

    `sub` is compared with `casefold()` on both sides, after `strip()`: the gateway lowercases
    usernames (apps/aigateway/src/aigateway/config.py:275-290).
    INVARIANT: `trace_id` None never matches, so a receipt without a trace id in the report is
    refused. WHY `check_subject`: C3 skips the `sub` check where the identity is not verified.
    """
    if trace_id is None or claims.tid != trace_id:
        raise ReceiptNotYours
    if check_subject and not _same_user(claims.sub, submitter):
        raise ReceiptNotYours


def receipt_columns(claims: ReceiptClaims | None) -> dict[str, object]:
    """The five I-R1 columns: all set from the claims, or all None."""
    if claims is None:
        return {
            "cache_version_id": None,
            "cache_version_sha256": None,
            "cache_entry_count": None,
            "cache_call_count": None,
            "cache_coverage_status": None,
        }
    return {
        "cache_version_id": claims.vid,
        "cache_version_sha256": claims.sha,
        "cache_entry_count": claims.n,
        "cache_call_count": claims.c,
        "cache_coverage_status": claims.cov,
    }
