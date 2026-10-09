"""G0 native OAuth callback — a compat-document conflict keeps its wire outcome (OME-1497).

# FEATURE: OME-1138 D18, G0 (contract §5.3) — the native callback updates a same-named compat
# Profile inside its activation transaction. A Profile-index write that exhausted its retries rolls
# the whole activation back and answers the callback's existing 503 `profile_index_conflict`; the
# Connection stays pending so the user can simply retry.
# AIDEV-NOTE: helpers are bound from `test_writer_floor_native`.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import blob_at_connection_address, marker
from connection_backed_oauth_probes import callback, use_tokens
from provider_access_harness import ProfileBackedHarness
from test_writer_floor_native import KEY, _row, _start

from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.routes import auth as auth_routes


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def test_a_compat_document_conflict_rolls_the_native_callback_back_as_an_index_conflict(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(name="work", auth_type="api_key", credential=KEY)
    use_tokens(legacy, "not-published")
    started = _start(legacy, label="work")
    before_callback = marker(legacy)

    async def index_conflict(*_args: Any, **_kwargs: Any) -> None:
        raise CredentialBlobMutationConflict("profile index retries exhausted")

    monkeypatch.setattr(auth_routes, "_mark_profile_authenticated", index_conflict)

    response = callback(legacy, started.json()["state"])

    assert response.status_code == 503, response.text
    assert "profile_index_conflict" in response.text
    assert marker(legacy) == before_callback
    connection_id = started.json()["connection_id"]
    assert _row(legacy, connection_id).status == "pending"
    assert blob_at_connection_address(legacy, connection_id) is None
