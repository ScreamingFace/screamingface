"""Port contract — `resolve` over a MIGRATED pair (OME-1208, Stage B S2').

Re-runs `test_provider_access_resolve_contract` unchanged over `ConnectionBackedHarness`: the same
situations, seeded as a legacy document + an effective Connection reading the Profile's blob + a
`migrated` marker (D14, D16 (a)). Consumers were not rewritten; the contract was not weakened.

# INVARIANT: every contract test is re-imported except the three named in `NOT_REIMPORTED`, and a
# test guards that set against a renamed or added contract test. The Profile-shaped stamp test and
# the api-key re-auth test have Connection-shaped twins below — the observables a migrated target
# changes on purpose.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_provider_access_resolve_contract as contract
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, Harness

from aigateway.core.profile_models import credential_name_for

NOT_REIMPORTED = {
    # WHY: a migrated target is stamped by the Connection it resolves to (`conn:` shape); the
    # Profile-shaped assertion is legacy-only; its twin below asserts the Connection shape.
    "test_an_authenticated_default_resolves_to_a_stored_target",
    # WHY: an api-key target that has a Connection names it, so the re-key replaces the row chat
    # reads (OME-1209 E1); its twin below asserts that exact URL.
    "test_an_api_key_profile_carries_the_api_key_reauth_url",
    # WHY: a fake-only witness that takes no harness; it is not a contract over a backing.
    "test_a_fake_that_retargets_fails_the_contract",
}

for _name, _test in vars(contract).items():
    if _name.startswith("test_") and _name not in NOT_REIMPORTED:
        globals()[_name] = _test


@pytest.fixture
def harness(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> Harness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def test_every_contract_test_is_re_run_or_named_here() -> None:
    contract_tests = {name for name in vars(contract) if name.startswith("test_")}
    re_run = {name for name in globals() if name.startswith("test_")}

    assert contract_tests - NOT_REIMPORTED <= re_run
    assert NOT_REIMPORTED <= contract_tests


def test_an_authenticated_default_resolves_to_the_effective_connection(harness: Harness) -> None:
    harness.seed_profile()

    target = harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, contract.DEFAULT, plugin=ANTHROPIC
    )

    assert target.kind == "stored"
    assert target.auth_type == "oauth"
    # INVARIANT (no re-entry): the target reads the blob the legacy Profile already addresses.
    assert target.credential_name == credential_name_for(harness.account_id, "default")
    assert target.reauth_url == "/v1/oauth/connections"
    assert target.context_stamp.startswith(f"acct:{harness.account_id}|conn:")
    assert ":active:" in target.context_stamp


def test_a_migrated_api_key_target_names_its_effective_connection(
    harness: ConnectionBackedHarness,
) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential="sk-1")

    target = harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, contract.WORK, plugin=ANTHROPIC
    )

    assert target.auth_type == "api_key"
    effective = harness.migrated["work"]
    assert target.reauth_url == f"/v1/oauth/connections/{effective}/api-key"
