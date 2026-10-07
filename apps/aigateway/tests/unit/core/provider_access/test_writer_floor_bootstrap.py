"""G0 writer floor — the opt-in startup import is a legacy writer on its pair (OME-1497).

# FEATURE: OME-1138 D18, G0 (contract §5.3: "the G0 inventory includes ... bootstrap where it
# writes a credential") — `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1` imports a legacy Profile and its
# blob at startup; it claims a `none`/`quarantined` pair like every other legacy writer.
# INVARIANT: a `migrated` pair is skipped — its Connection owns the Profile address (D5).
# INVARIANT: a startup that imports nothing changes no owner, so it leaves the marker untouched.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import document, marker
from connection_backed_harness import ConnectionBackedHarness
from fastapi.testclient import TestClient
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.core.provider_access.writer_floor import bootstrap_under_the_floor
from tests.conftest import _prepare_sqlite_db


class _ImportingPlugin(ProviderPluginBase):
    """A provider whose startup import publishes one `default` Profile, or nothing."""

    def __init__(self, provider: str = PROVIDER, *, imports: bool = True) -> None:
        self.custom_llm_provider = provider
        self.imports = imports
        self.calls = 0

    def register_models(self) -> list[ModelEntry]:
        return []

    async def bootstrap_profiles(
        self, *, account_id: str, credential_store: Any = None, index_store: Any = None
    ) -> None:
        self.calls += 1
        if self.imports:
            await index_store.upsert(
                Profile(
                    id=profile_id_for(account_id, self.custom_llm_provider, "default"),
                    account_id=account_id,
                    provider=self.custom_llm_provider,
                    name="default",
                    state=ProfileState.AUTHENTICATED,
                )
            )


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _bootstrap(harness: Any, plugin: _ImportingPlugin) -> None:
    state = harness.client.app.state
    harness.call(
        bootstrap_under_the_floor,
        plugin,
        account_id=harness.account_id,
        credential_store=state.credential_store,
        index_store=state.profile_index,
    )


def _seed_marker(harness: Any, state: str, note: str | None) -> None:
    harness.call(
        PairAuthorityStore().advance,
        harness.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state=state,
        migration_note=note,
    )


def test_a_bootstrap_import_claims_an_unmarked_pair_and_keeps_it_legacy_owned(
    legacy: ProfileBackedHarness,
) -> None:
    _bootstrap(legacy, _ImportingPlugin())

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation) == ("none", 1)
    assert document(legacy) is not None


@pytest.mark.parametrize(("state", "note"), [("quarantined", "conflict"), ("none", "rollback")])
def test_a_bootstrap_import_keeps_the_state_and_the_note_of_a_legacy_owned_pair(
    legacy: ProfileBackedHarness, state: str, note: str
) -> None:
    _seed_marker(legacy, state, note)

    _bootstrap(legacy, _ImportingPlugin())

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation, pair.migration_note) == (state, 2, note)


def test_a_bootstrap_that_imports_nothing_leaves_the_marker_untouched(
    legacy: ProfileBackedHarness,
) -> None:
    plugin = _ImportingPlugin(imports=False)

    _bootstrap(legacy, plugin)

    assert plugin.calls == 1
    assert marker(legacy).generation == 0
    _seed_marker(legacy, "none", "rollback")
    _bootstrap(legacy, plugin)
    assert marker(legacy).generation == 1


def test_a_bootstrap_skips_a_migrated_pair(migrated: ConnectionBackedHarness) -> None:
    migrated.seed_authority()
    before = marker(migrated)
    plugin = _ImportingPlugin()

    _bootstrap(migrated, plugin)

    assert plugin.calls == 0
    assert marker(migrated) == before


def test_the_startup_runs_the_opt_in_bootstrap_under_the_floor(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    monkeypatch.setenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE", "1")
    _prepare_sqlite_db(database_url)
    from aigateway import main as main_module

    plugin = _ImportingPlugin("spy")
    monkeypatch.setattr(main_module, "load_plugins", lambda registry: registry.register(plugin))

    with TestClient(main_module.create_app()) as client:
        token = client.post(
            "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
        ).json()["token"]
        me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        portal = client.portal
        assert portal is not None
        pair = portal.call(PairAuthorityStore().read, me["id"], "spy")

    assert plugin.calls == 1
    assert (pair.migration_state, pair.generation) == ("none", 1)
