"""The HTTP-edge rendering table (OME-1200, spec §3.2): typed refusal → today's status + detail.

# INVARIANT: every status code and detail body below is byte-identical to what
# `routes/chat_credentials.py`, `routes/auth.py` and `main.py` raise at 17048f5d. This table is
# the ONLY place a refusal becomes an HTTP code; implementations never choose codes.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from aigateway.core.provider_access import (
    ProviderAccessRefusal,
    SelectorAmbiguous,
    SelectorUnknown,
    SelectorUnsupported,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    UnsupportedAuthMode,
    WriteConflict,
)
from aigateway.routes.provider_access_http import refusals_as_http, render_refusal

_CASES: list[tuple[ProviderAccessRefusal, int, dict]] = [
    (
        TargetMissing("anthropic", "work"),
        404,
        {"code": "profile_not_found", "provider": "anthropic", "name": "work"},
    ),
    (
        TargetPending("anthropic", "default"),
        409,
        {"code": "profile_pending_auth", "provider": "anthropic", "name": "default"},
    ),
    (
        TargetReauthRequired("anthropic", "/v1/auth/anthropic/profiles/work", requested="work"),
        401,
        {
            "code": "auth_required",
            "provider": "anthropic",
            "name": "work",
            "reauth_url": "/v1/auth/anthropic/profiles/work",
        },
    ),
    (
        TargetReauthRequired(
            "anthropic", "/v1/auth/anthropic/profiles/work/api-key", message="No API key stored"
        ),
        401,
        {
            "code": "auth_required",
            "message": "No API key stored",
            "reauth_url": "/v1/auth/anthropic/profiles/work/api-key",
        },
    ),
    (
        SelectorAmbiguous("anthropic"),
        409,
        {
            "code": "connection_ambiguous",
            "provider": "anthropic",
            "message": (
                "Multiple active connections exist. Select one by setting "
                "X-Profile to the connection label."
            ),
        },
    ),
    (
        SelectorUnknown("anthropic", "nope", ("work", "personal")),
        404,
        {
            "code": "connection_not_found",
            "provider": "anthropic",
            "requested_label": "nope",
            "valid_labels": ["work", "personal"],
        },
    ),
    (
        UnsupportedAuthMode("api_key", provider="codex"),
        400,
        {"code": "api_key_not_supported", "provider": "codex"},
    ),
    (
        UnsupportedAuthMode("oauth", provider=None),
        400,
        {"code": "provider_does_not_use_oauth"},
    ),
    (
        UnsupportedAuthMode("oauth", provider=""),
        400,
        {"code": "provider_does_not_use_oauth"},
    ),
    (
        WriteConflict("superseded", subject="connection"),
        409,
        {"code": "connection_conflict", "message": "Connection changed during auth-type repair"},
    ),
    (
        WriteConflict("superseded", subject="profile", provider="anthropic", requested="work"),
        409,
        {"code": "profile_conflict", "provider": "anthropic", "profile": "work"},
    ),
    (
        WriteConflict("retry_exhausted", subject="profile"),
        503,
        {
            "code": "profile_index_conflict",
            "message": "Profile metadata update conflicted. Try again.",
        },
    ),
    (
        SelectorUnsupported("work"),
        400,
        {"code": "x_profile_unsupported", "requested_label": "work"},
    ),
]


@pytest.mark.parametrize(("refusal", "status", "detail"), _CASES, ids=lambda c: type(c).__name__)
def test_each_refusal_renders_todays_status_and_detail(
    refusal: ProviderAccessRefusal, status: int, detail: dict
) -> None:
    exc = render_refusal(refusal)

    assert isinstance(exc, HTTPException)
    assert exc.status_code == status
    assert exc.detail == detail


def test_every_refusal_is_a_provider_access_refusal() -> None:
    assert all(isinstance(case[0], ProviderAccessRefusal) for case in _CASES)


def test_the_context_manager_converts_refusals_and_chains_the_cause() -> None:
    with pytest.raises(HTTPException) as info, refusals_as_http():
        raise TargetMissing("anthropic", "work")

    assert info.value.status_code == 404
    assert isinstance(info.value.__cause__, TargetMissing)


def test_the_context_manager_leaves_other_exceptions_alone() -> None:
    with pytest.raises(RuntimeError), refusals_as_http():
        raise RuntimeError("not ours")
