"""The rendering rows the admin boundary adds to the HTTP edge (OME-1230, Stage A3; spec §3.2).

# INVARIANT: byte-identical to what `routes/auth.py` raised at 248b0b6d — `upsert_api_key_profile`
# :1264-1266 and `persist_credentials_or_503`, and `delete_profile_for_account` :1380,:1384.
# F3 (owner, 2026-09-18): the delete route's provider-less 404 bodies keep their OWN rows; no
# provider or name field is added to them.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    ProviderAccessRefusal,
    ProviderUnknown,
    TargetMissing,
    WriteConflict,
)
from aigateway.routes.provider_access_http import (
    legacy_delete_refusals_as_http,
    render_legacy_delete_refusal,
    render_refusal,
)


def test_the_new_refusals_are_provider_access_refusals() -> None:
    assert isinstance(ProviderUnknown("p"), ProviderAccessRefusal)
    assert isinstance(CredentialStoreUnavailable("API-key credentials"), ProviderAccessRefusal)


def test_an_unknown_provider_renders_todays_put_body() -> None:
    exc = render_refusal(ProviderUnknown("nope"))

    assert isinstance(exc, HTTPException)
    assert exc.status_code == 404
    assert exc.detail == {"code": "unknown_provider", "provider": "nope"}


def test_an_unavailable_credential_store_renders_todays_503() -> None:
    exc = render_refusal(CredentialStoreUnavailable("API-key credentials"))

    assert exc.status_code == 503
    assert exc.detail == {
        "code": "credential_store_unavailable",
        "message": "Could not store API-key credentials. Try again.",
    }


@pytest.mark.parametrize(
    ("refusal", "detail"),
    [
        (ProviderUnknown("nope"), {"code": "unknown_provider"}),
        (TargetMissing("anthropic", "absent"), {"code": "profile_not_found"}),
    ],
    ids=["unknown_provider", "profile_not_found"],
)
def test_the_delete_shell_keeps_its_provider_less_404_bodies(
    refusal: ProviderAccessRefusal, detail: dict
) -> None:
    exc = render_legacy_delete_refusal(refusal)

    assert exc.status_code == 404
    assert exc.detail == detail


def test_the_delete_rows_fall_through_to_the_shared_table_for_everything_else() -> None:
    conflict = WriteConflict("retry_exhausted", subject="profile")

    assert render_legacy_delete_refusal(conflict).detail == render_refusal(conflict).detail
    assert render_legacy_delete_refusal(conflict).status_code == 503


def test_the_delete_context_manager_converts_refusals_and_chains_the_cause() -> None:
    with pytest.raises(HTTPException) as info, legacy_delete_refusals_as_http():
        raise TargetMissing("anthropic", "absent")

    assert info.value.status_code == 404
    assert info.value.detail == {"code": "profile_not_found"}
    assert isinstance(info.value.__cause__, TargetMissing)


def test_the_delete_context_manager_leaves_other_exceptions_alone() -> None:
    with pytest.raises(RuntimeError), legacy_delete_refusals_as_http():
        raise RuntimeError("not ours")
