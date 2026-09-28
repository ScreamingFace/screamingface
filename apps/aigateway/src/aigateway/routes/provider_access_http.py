"""The HTTP-edge rendering table for provider-access refusals (OME-1200, spec §3.2).

# INVARIANT: this is the ONLY place a typed refusal becomes a status code and a detail body,
# and every row is byte-identical to what `routes/chat_credentials.py`, `routes/auth.py` and
# `main.py` raised at 17048f5d. A new refusal gets a row here; an implementation never picks
# a code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

from ..core.provider_access import (
    CredentialStoreUnavailable,
    ProviderAccessRefusal,
    ProviderUnknown,
    SelectorAmbiguous,
    SelectorUnknown,
    SelectorUnsupported,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    UnsupportedAuthMode,
    WriteConflict,
)

_AMBIGUOUS_MESSAGE = (
    "Multiple active connections exist. Select one by setting X-Profile to the connection label."
)
_CONNECTION_CONFLICT_MESSAGE = "Connection changed during auth-type repair"
_INDEX_CONFLICT_MESSAGE = "Profile metadata update conflicted. Try again."


def _reauth_detail(exc: TargetReauthRequired) -> dict[str, Any]:
    # Two shapes, both today's: the resolve-time refusal names the target; the authorize-time
    # refusal carries the provider's message (`chat_credentials.py` :266-274 vs :433-445).
    if exc.message is None:
        return {
            "code": "auth_required",
            "provider": exc.provider,
            "name": exc.requested,
            "reauth_url": exc.reauth_url,
        }
    return {"code": "auth_required", "message": exc.message, "reauth_url": exc.reauth_url}


def _unsupported_detail(exc: UnsupportedAuthMode) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": "api_key_not_supported"
        if exc.auth_mode == "api_key"
        else "provider_does_not_use_oauth",
    }
    if exc.provider:
        detail["provider"] = exc.provider
    return detail


def _write_conflict(exc: WriteConflict) -> HTTPException:
    if exc.kind == "retry_exhausted":
        # `main.py::_profile_index_conflict` — the CAS on the index blob ran out of retries.
        return HTTPException(
            status_code=503,
            detail={"code": "profile_index_conflict", "message": _INDEX_CONFLICT_MESSAGE},
        )
    if exc.subject == "connection":
        return HTTPException(
            status_code=409,
            detail={"code": "connection_conflict", "message": _CONNECTION_CONFLICT_MESSAGE},
        )
    return HTTPException(
        status_code=409,
        detail={"code": "profile_conflict", "provider": exc.provider, "profile": exc.requested},
    )


def render_refusal(exc: ProviderAccessRefusal) -> HTTPException:
    """Today's status + detail for one refusal; unknown refusals are a programming error."""
    if isinstance(exc, TargetMissing):
        return HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": exc.provider, "name": exc.requested},
        )
    if isinstance(exc, TargetPending):
        return HTTPException(
            status_code=409,
            detail={
                "code": "profile_pending_auth",
                "provider": exc.provider,
                "name": exc.requested,
            },
        )
    if isinstance(exc, TargetReauthRequired):
        return HTTPException(status_code=401, detail=_reauth_detail(exc))
    if isinstance(exc, SelectorAmbiguous):
        return HTTPException(
            status_code=409,
            detail={
                "code": "connection_ambiguous",
                "provider": exc.provider,
                "message": _AMBIGUOUS_MESSAGE,
            },
        )
    if isinstance(exc, SelectorUnknown):
        return HTTPException(
            status_code=404,
            detail={
                "code": "connection_not_found",
                "provider": exc.provider,
                "requested_label": exc.requested,
                "valid_labels": list(exc.valid_labels),
            },
        )
    if isinstance(exc, UnsupportedAuthMode):
        return HTTPException(status_code=400, detail=_unsupported_detail(exc))
    if isinstance(exc, WriteConflict):
        return _write_conflict(exc)
    rendered = _management_refusal(exc)
    if rendered is not None:
        return rendered
    raise TypeError(f"no HTTP rendering for {type(exc).__name__}")  # pragma: no cover


def _management_refusal(exc: ProviderAccessRefusal) -> HTTPException | None:
    """The rows added after A1's read table: the Stage D selector sunset and the A3 admin rows."""
    if isinstance(exc, SelectorUnsupported):
        return HTTPException(
            status_code=400,
            detail={"code": "x_profile_unsupported", "requested_label": exc.requested},
        )
    if isinstance(exc, ProviderUnknown):
        # `routes/auth.py::upsert_api_key_profile` :1264-1266 at 248b0b6d (the PUT shape; the
        # delete shell's provider-less shape is `render_legacy_delete_refusal`).
        return HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": exc.provider}
        )
    if isinstance(exc, CredentialStoreUnavailable):
        # `routes/credential_persistence.py::persist_credentials_or_503` at 248b0b6d.
        return HTTPException(
            status_code=503,
            detail={
                "code": "credential_store_unavailable",
                "message": f"Could not store {exc.description}. Try again.",
            },
        )
    return None


def render_legacy_delete_refusal(exc: ProviderAccessRefusal) -> HTTPException:
    """The delete shell's own rows (F3, owner 2026-09-18): today's provider-less 404 bodies.

    # COMPATIBILITY (window-only, retired with the shells at Stage E / OME-1209):
    # `routes/auth.py::delete_profile_for_account` :1380 and :1384 at 248b0b6d raised
    # `{"code": "unknown_provider"}` and `{"code": "profile_not_found"}` with NO provider or name
    # field, unlike every other row. Every other refusal renders through the shared table.
    """
    if isinstance(exc, ProviderUnknown):
        return HTTPException(status_code=404, detail={"code": "unknown_provider"})
    if isinstance(exc, TargetMissing):
        return HTTPException(status_code=404, detail={"code": "profile_not_found"})
    return render_refusal(exc)


@contextmanager
def refusals_as_http() -> Iterator[None]:
    """Render any refusal raised inside the block as its `HTTPException`, chaining the cause."""
    try:
        yield
    except ProviderAccessRefusal as exc:
        raise render_refusal(exc) from exc


@contextmanager
def legacy_delete_refusals_as_http() -> Iterator[None]:
    """`refusals_as_http`, rendering through the delete shell's rows (F3)."""
    try:
        yield
    except ProviderAccessRefusal as exc:
        raise render_legacy_delete_refusal(exc) from exc
