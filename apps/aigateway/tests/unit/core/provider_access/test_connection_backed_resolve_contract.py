"""Port contract — `defaults_for` and `resolve` over a MIGRATED pair (OME-1208, Stage B S2').

Re-runs `test_provider_access_resolve_contract` unchanged over `ConnectionBackedHarness`: the same
situations, seeded as a legacy document + an effective Connection reading the Profile's blob + a
`migrated` marker (D14, D16 (a)). Consumers were not rewritten; the contract was not weakened.

# INVARIANT: every contract test is re-imported except the two named in `NOT_REIMPORTED`, and a
# test guards that set against a renamed or added contract test. The Profile-shaped stamp test has
# a Connection-shaped twin below — the ONE observable a migrated target changes on purpose.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_provider_access_resolve_contract as contract
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, Harness

from aigateway.core.profile_models import ProfileDefaults, credential_name_for

NOT_REIMPORTED = {
    # WHY: a migrated target is stamped by the Connection it resolves to (`conn:` shape); the
    # Profile-shaped assertion is legacy-only; its twin below asserts the Connection shape.
    "test_an_authenticated_default_resolves_to_a_stored_target",
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
    harness.seed_profile(defaults=ProfileDefaults(system_prompt="be brief"))

    target = harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, contract.DEFAULT, plugin=ANTHROPIC
    )

    assert target.kind == "stored"
    assert target.auth_type == "oauth"
    # INVARIANT (no re-entry): the target reads the blob the legacy Profile already addresses.
    assert target.credential_name == credential_name_for(harness.account_id, "default")
    assert target.defaults.system_prompt == "be brief"
    assert target.reauth_url == f"/v1/auth/{PROVIDER}/profiles/default"
    assert target.context_stamp.startswith(f"acct:{harness.account_id}|conn:")
    assert ":active:" in target.context_stamp
