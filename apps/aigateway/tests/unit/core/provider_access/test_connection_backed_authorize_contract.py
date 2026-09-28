"""Port contract — `authorize` and `record_dispatch_failure` over a MIGRATED pair (OME-1208, S2').

Re-runs `test_provider_access_authorize_contract` unchanged over `ConnectionBackedHarness`. The
writes the read path performs — error marking, strategy-cache eviction, session invalidation — land
on the pair's authority (its effective Connection) while the observable contract stays the one the
Profile-backed implementation honours (D14: one write owner per pair; facade HTTP unchanged).

# INVARIANT: every contract test is re-imported; a guard test pins that against additions.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_provider_access_authorize_contract as contract
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import Harness

for _name, _test in vars(contract).items():
    if _name.startswith("test_"):
        globals()[_name] = _test


@pytest.fixture
def harness(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> Harness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def test_every_authorize_contract_test_is_re_run() -> None:
    contract_tests = {name for name in vars(contract) if name.startswith("test_")}

    assert contract_tests <= {name for name in globals() if name.startswith("test_")}
