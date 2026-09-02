"""OME-1026 correction: programming defects never masquerade as discovery fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from aigateway.core.background_error_sink import take_unexpected
from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for

_SOURCE = ModelDiscoverySource(
    key="fake:models:list",
    revision="fake-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)
_SECRET = "PROGRAMMING_ERROR_SECRET=must-not-be-retained"


class _NoClient:
    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError(f"DIAL ATTEMPTED: {url}")


@dataclass
class _BrokenPlugin:
    custom_llm_provider: str = "fake"

    def model_discovery_scope(self) -> DiscoveryScope:
        return DiscoveryScope.PROFILE_CREDENTIAL

    def model_discovery_source(self) -> ModelDiscoverySource:
        return _SOURCE

    def profile_discovery_unsupported_reason(self, *, auth_type: str) -> None:
        return None

    async def discover_profile_models(
        self, *, client: Any, limits: Any = None, auth: ProviderAuthContext
    ) -> tuple[ModelEntry, ...] | None:
        raise RuntimeError(_SECRET)


async def _auth() -> ProviderAuthContext:
    return ProviderAuthContext(headers={"x-api-key": "credential"}, auth_type="api_key")


def _profile() -> Profile:
    return Profile(
        id=profile_id_for("acct-a", "fake", "default"),
        account_id="acct-a",
        provider="fake",
        name="default",
        state=ProfileState.AUTHENTICATED,
        auth_type="api_key",
        last_refreshed_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


async def _ask(catalog: ProfileModelCatalog, *, budget: float):
    return await catalog.snapshot_for(
        _BrokenPlugin(),
        account_id="acct-a",
        profile=_profile(),
        client=_NoClient(),
        limits=None,
        auth_provider=_auth,
        credential_generation=1,
        wait_budget_s=budget,
    )


@pytest.mark.asyncio
async def test_an_awaited_programming_error_reaches_the_caller(caplog) -> None:
    catalog = ProfileModelCatalog(max_identities=8, max_inflight_refreshes=4)
    take_unexpected()
    try:
        with pytest.raises(RuntimeError, match="PROGRAMMING_ERROR_SECRET"):
            await _ask(catalog, budget=5.0)
        assert take_unexpected() == (), "an observed error must not also fail teardown"
        assert _SECRET not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        await catalog.aclose()
        take_unexpected()


@pytest.mark.asyncio
async def test_an_unawaited_programming_error_is_retained_only_as_sanitized_metadata() -> None:
    catalog = ProfileModelCatalog(max_identities=8, max_inflight_refreshes=4)
    take_unexpected()
    try:
        snapshot = await _ask(catalog, budget=0.0)
        assert snapshot.status == "refreshing"
        await catalog.drain()

        retained = take_unexpected()
        assert len(retained) == 1
        assert retained[0].type_name == "RuntimeError"
        assert _SECRET not in repr(retained[0])
        assert not hasattr(retained[0], "__traceback__")
    finally:
        await catalog.aclose()
        take_unexpected()
