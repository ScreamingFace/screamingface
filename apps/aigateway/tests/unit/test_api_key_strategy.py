"""Unit tests for the core ApiKeyStrategy — exercised through the
CredentialStrategy port with a dict-backed fake store (no DB)."""

from __future__ import annotations

import json

import pytest

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.core.plugin_base import CredentialStrategy, OAuthStrategy


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    async def read(self, service: str, account: str) -> str | None:
        return self.data.get((service, account))

    async def write(self, service: str, account: str, value: str) -> None:
        self.data[(service, account)] = value

    async def delete(self, service: str, account: str) -> None:
        self.data.pop((service, account), None)

    async def mutate(self, service: str, account: str, mutator) -> None:
        next_value = mutator(await self.read(service, account))
        if next_value is None:
            self.data.pop((service, account), None)
        else:
            self.data[(service, account)] = next_value


def _strategy(store: FakeStore | None = None) -> tuple[ApiKeyStrategy, FakeStore]:
    store = store or FakeStore()
    strategy = ApiKeyStrategy(
        "acct:default",
        service="aigateway:testprov:acct:default",
        account="default",
        header_builder=lambda key: {"x-test-api-key": key},
        credential_store=store,
    )
    return strategy, store


def test_api_key_strategy_implements_the_credential_port() -> None:
    strategy, _ = _strategy()
    assert isinstance(strategy, CredentialStrategy)
    # Back-compat alias resolves to the same port.
    assert isinstance(strategy, OAuthStrategy)


@pytest.mark.asyncio
async def test_persist_then_get_header_round_trip() -> None:
    strategy, store = _strategy()
    await strategy.persist_credentials({"auth_type": "api_key", "api_key": "raw-key-123"})

    headers = await strategy.get_authorization_header()

    assert headers == {"x-test-api-key": "raw-key-123"}
    blob = json.loads(store.data[("aigateway:testprov:acct:default", "default")])
    assert blob == {"auth_type": "api_key", "api_key": "raw-key-123"}


@pytest.mark.asyncio
async def test_missing_blob_raises_credential_not_found() -> None:
    strategy, _ = _strategy()
    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_non_json_blob_raises_auth_error() -> None:
    strategy, store = _strategy()
    store.data[("aigateway:testprov:acct:default", "default")] = "not json"
    with pytest.raises(AuthError, match="not valid JSON"):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_oauth_shaped_blob_raises_auth_error() -> None:
    """A leftover OAuth token blob must not be served as an API key."""
    strategy, store = _strategy()
    store.data[("aigateway:testprov:acct:default", "default")] = json.dumps(
        {"access_token": "tok", "refresh_token": "rt", "expires_at_ms": 1}
    )
    with pytest.raises(AuthError, match="not an API-key blob"):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_blob_missing_api_key_raises_auth_error() -> None:
    strategy, store = _strategy()
    store.data[("aigateway:testprov:acct:default", "default")] = json.dumps(
        {"auth_type": "api_key", "api_key": ""}
    )
    with pytest.raises(AuthError, match="missing 'api_key'"):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_persist_rejects_empty_api_key() -> None:
    strategy, store = _strategy()
    with pytest.raises(AuthError):
        await strategy.persist_credentials({"auth_type": "api_key", "api_key": ""})
    assert store.data == {}


@pytest.mark.asyncio
async def test_refresh_validates_but_never_mutates() -> None:
    strategy, store = _strategy()
    await strategy.persist_credentials({"api_key": "raw-key-123"})
    before = dict(store.data)

    await strategy.refresh_credentials()

    assert store.data == before
    assert await strategy.get_authorization_header() == {"x-test-api-key": "raw-key-123"}


@pytest.mark.asyncio
async def test_refresh_with_missing_blob_raises_credential_not_found() -> None:
    """Refresh must not report success for a profile whose key blob is gone
    (audit F09) — the route lifecycle relies on this to flip ERROR."""
    strategy, _ = _strategy()
    with pytest.raises(CredentialNotFoundError):
        await strategy.refresh_credentials()


@pytest.mark.asyncio
async def test_refresh_with_oauth_shaped_blob_raises_auth_error() -> None:
    strategy, store = _strategy()
    store.data[("aigateway:testprov:acct:default", "default")] = json.dumps({"access_token": "tok"})
    with pytest.raises(AuthError):
        await strategy.refresh_credentials()


@pytest.mark.asyncio
async def test_delete_removes_blob() -> None:
    strategy, store = _strategy()
    await strategy.persist_credentials({"api_key": "raw-key-123"})

    await strategy.delete_credentials()

    assert store.data == {}
    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_a_missing_key_points_the_user_at_the_connection() -> None:
    # WHY (OME-1138 close-out, L5, RT-05): a key is set on a Connection; the Profile is retired.
    strategy, _ = _strategy()

    with pytest.raises(CredentialNotFoundError) as raised:
        await strategy.get_authorization_header()

    assert str(raised.value) == (
        "No API key stored for 'acct:default'. Set or replace the key for this connection."
    )
