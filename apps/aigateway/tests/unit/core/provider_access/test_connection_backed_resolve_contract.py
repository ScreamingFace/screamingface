"""Port contract — `resolve` over a MIGRATED pair (OME-1208, Stage B S2').

Re-runs `test_provider_access_resolve_contract` unchanged over `ConnectionBackedHarness`: the same
situations, seeded as an effective Connection reading the blob at the credential's name address +
a `migrated` marker (D14, D16 (a)). Consumers were not rewritten; the contract was not weakened.

# INVARIANT: every contract test is re-imported except the fake-only witness in `NOT_REIMPORTED`,
# and a test guards that set against a renamed or added contract test.
# FEATURE: OME-1138 close-out, L4a — the fake seeds the same effective Connection, so the stamp
# and api-key re-auth tests the Profile-shaped fake once kept apart now run on both witnesses.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_provider_access_resolve_contract as contract
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import Harness

NOT_REIMPORTED = {
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
