"""The credential-admin contract, re-run over a MIGRATED pair (OME-1208, Stage B S2'b1).

# FEATURE: OME-1138 Stage B — every admin contract test written for the Profile-backed body runs
# unchanged against `ConnectionBackedCredentialAdmin` on a pair whose marker is `migrated`: the
# seam only differs in WHAT it seeds first (the effective Connection + marker, S4's after-state).
# INVARIANT: the effective Connection's locator IS the Profile address `<account>:<name>`, so the
# contract's blob probes read the very slot the Connection-backed authority writes — no consumer
# rewrite. The one test that cannot re-run (`NOT_REIMPORTED`) is re-expressed below: a document of
# a migrated provider renders from the Connection, so a seeded PENDING document lists as the
# Connection's state, not its own.
# AIDEV-NOTE: the originals are imported and injected by name; append-only forbids parametrizing
# their `seam` fixture, so this module overrides the fixture instead.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_provider_credential_admin as contract
from connection_backed_harness import migrate_pair

from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import ConnectionBackedCredentialAdmin

NOT_REIMPORTED = frozenset(
    {
        # Re-expressed below: a migrated provider's documents render from the Connection.
        "test_list_returns_masked_summaries_carrying_the_legacy_projection",
    }
)

for _name in dir(contract):
    if _name.startswith("test_") and _name not in NOT_REIMPORTED:
        globals()[_name] = getattr(contract, _name)


class MigratedSeam(contract._Seam):
    """The contract's seam over a pair the backfill has ALREADY migrated (one OAuth Connection)."""

    def __init__(self, client: Any, blobs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(client, blobs, monkeypatch)
        self.connection = self.call(
            migrate_pair,
            self.account_id,
            name="keyed",
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
        )


@pytest.fixture
def seam(authenticated_client, credential_blobs, monkeypatch) -> MigratedSeam:
    return MigratedSeam(authenticated_client, credential_blobs, monkeypatch)


def test_every_admin_contract_test_is_re_run_or_named_here() -> None:
    originals = {name for name in dir(contract) if name.startswith("test_")}
    assert NOT_REIMPORTED <= originals
    assert {name for name in originals - NOT_REIMPORTED if name not in globals()} == set()


def test_the_migrated_seam_runs_over_the_connection_backed_admin(seam: MigratedSeam) -> None:
    assert isinstance(seam.admin, ConnectionBackedCredentialAdmin)
    assert seam.connection.status == "active"


def test_list_renders_every_document_of_a_migrated_provider_from_its_connection(
    seam: MigratedSeam,
) -> None:
    seam.set_api_key("keyed")
    oauth = seam.seed_oauth_profile("work", state=ProfileState.PENDING)

    everything = seam.call(seam.admin.list, seam.account_id)
    only_anthropic = seam.call(seam.admin.list, seam.account_id, "anthropic")
    nothing = seam.call(seam.admin.list, seam.account_id, "codex")

    assert isinstance(everything, tuple)
    assert {s.selector for s in everything} == {"keyed", "work"}
    assert everything == only_anthropic
    assert nothing == ()
    by_selector = {s.selector: s for s in everything}
    # INVARIANT (D14/D16 (a)): one credential per pair — the seeded PENDING/oauth document is a
    # compatibility alias of the SAME effective Connection, so it lists as that Connection.
    for summary in everything:
        assert (summary.auth_type, summary.state) == ("api_key", "authenticated")
    rendered = oauth.model_copy(
        update={"state": ProfileState.AUTHENTICATED, "auth_type": "api_key"}
    )
    assert by_selector["work"].legacy_projection == rendered.model_dump(mode="json")
    keyed = seam.profile("keyed")
    assert keyed is not None
    assert by_selector["keyed"].legacy_projection == keyed.model_dump(mode="json")
