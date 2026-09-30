"""Coded error bodies of the E14 routes (D7 X-8): `{"detail": {"code", "message", ...}}`.

FEATURE: OME-1307 (E14). One place builds them, so a route never spells the shape by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from scoreboard.core.paging import InvalidCursor
from scoreboard.core.registry import (
    InvalidSystemName,
    InvalidUrl4,
    NotSystemOwner,
    RegistryConflict,
    SystemNameTaken,
    SystemNotFound,
    Url4TooLarge,
)
from scoreboard.core.submissions.receipts import ReceiptNotYours, ReceiptRejected
from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS
from scoreboard.scores.cluster_store import CacheVersionAlreadyBound, InvalidReplayClaim

# WHY a literal: Starlette renamed `HTTP_422_UNPROCESSABLE_ENTITY` and the old name now warns.
UNPROCESSABLE = 422
STORE_UNAVAILABLE_DETAIL = "score store unavailable"
# INVARIANT (OME-894): one detail for a missing score AND for a private score the caller
# may not read, so the two are indistinguishable.
SCORE_NOT_FOUND_DETAIL = "score not found"


def coded_error(status: int, code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def score_not_found() -> HTTPException:
    # INVARIANT (OME-894): the same bytes and headers for a missing score and a private score that
    # is not the caller's, so holding a real id is not confirmable.
    return HTTPException(
        status_code=404, detail=SCORE_NOT_FOUND_DETAIL, headers=PRIVATE_CACHE_HEADERS
    )


def store_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=STORE_UNAVAILABLE_DETAIL)


def _from_registry(status: int, exc: Exception) -> HTTPException:
    # WHY `code` from the class: each registry error carries its stable code (D7 X-8).
    return coded_error(status, getattr(exc, "code"), str(exc))


_BUILDERS: dict[type[Exception], Callable[[Any], HTTPException]] = {
    ReceiptRejected: lambda exc: coded_error(
        422,
        "invalid_cache_version_receipt",
        "the cache version receipt was refused",
        reason=exc.reason,
    ),
    ReceiptNotYours: lambda exc: coded_error(
        403, "cache_version_not_yours", "this receipt was not issued for this run and user"
    ),
    CacheVersionAlreadyBound: lambda exc: coded_error(
        409,
        "cache_version_already_bound",
        "this cache version already belongs to another run",
    ),
    InvalidReplayClaim: lambda exc: coded_error(
        422, "invalid_replay_claim", "the replay claim names no result you may replay"
    ),
    NotSystemOwner: lambda exc: _from_registry(403, exc),
    SystemNotFound: lambda exc: _from_registry(404, exc),
    SystemNameTaken: lambda exc: coded_error(409, exc.code, str(exc), suggestion=exc.suggestion),
    InvalidSystemName: lambda exc: coded_error(422, exc.code, exc.message, rule=exc.rule),
    RegistryConflict: lambda exc: _from_registry(409, exc),
    InvalidUrl4: lambda exc: _from_registry(422, exc),
    Url4TooLarge: lambda exc: _from_registry(422, exc),
    InvalidCursor: lambda exc: coded_error(422, "invalid_cursor", "the cursor is not valid"),
}

# The exceptions `coded_http_error` maps; a route catches exactly these.
CODED_ERRORS: tuple[type[Exception], ...] = tuple(_BUILDERS)


def coded_http_error(exc: Exception) -> HTTPException:
    """The HTTP error of a domain error in `CODED_ERRORS` (D7 X-8)."""
    return _BUILDERS[type(exc)](exc)
