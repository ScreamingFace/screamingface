"""The rendering rows the admin boundary adds to the HTTP edge (OME-1230, Stage A3; spec §3.2).

# INVARIANT: byte-identical to what `routes/auth.py` raised at 248b0b6d — `upsert_api_key_profile`
# :1264-1266 and `persist_credentials_or_503`.
# WHY no delete rows: the delete shell's provider-less 404 bodies (F3) retired with the Profile
# routes at OME-1209 Stage E3b; every refusal now renders through the shared table.
"""

from __future__ import annotations

from fastapi import HTTPException

from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    ProviderAccessRefusal,
    ProviderUnknown,
)
from aigateway.routes.provider_access_http import render_refusal


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
