from __future__ import annotations

import pytest
from provider_access_harness import RealAppHarness

from aigateway.core.provider_access import Selector
from aigateway.core.provider_access.connection_backed import ConnectionBackedProviderAccess
from aigateway.core.provider_access.pair_authority import PairAuthority, PairAuthorityStore


class _NoCredentialPlugin:
    custom_llm_provider = "local"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("none",)

    def allows_chatless_credential(self) -> bool:
        return True

    def credentialless_auth_mode(self) -> None:
        return None


class _MarkersMustNotBeRead(PairAuthorityStore):
    async def read(self, account_id: str, provider: str) -> PairAuthority:
        raise AssertionError(f"authority read for no-auth pair {account_id}/{provider}")


def test_no_auth_provider_bypasses_profile_and_connection_rows(
    authenticated_client,
    credential_blobs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = RealAppHarness(authenticated_client, credential_blobs, monkeypatch)
    harness.seed_blob()
    harness.seed_connection(label="work")
    selector = Selector.from_header(None)

    profile_target = harness.call(
        harness.access.resolve,
        harness.account_id,
        "local",
        selector,
        plugin=_NoCredentialPlugin(),
    )
    connection_access = ConnectionBackedProviderAccess(
        authenticated_client.app,
        markers=_MarkersMustNotBeRead(),
    )
    connection_target = harness.call(
        connection_access.resolve,
        harness.account_id,
        "local",
        selector,
        plugin=_NoCredentialPlugin(),
    )

    assert profile_target.kind == "none"
    assert profile_target.credential_name is None
    assert connection_target.kind == "none"
    assert connection_target.credential_name is None
