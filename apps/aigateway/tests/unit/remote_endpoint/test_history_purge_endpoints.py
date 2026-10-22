"""The history purge and configured endpoints: an endpoint's key stays (OME-1138 Stage E, E5b).

# FEATURE: hosted BYOM Unit 0 meets the Stage E history cleanup — a configured endpoint is a
# provider like a bundled one, so the purge resolves its Connections through its strategy, keeps
# the key each one addresses, and does not skip its accounts as unresolvable.
# WHY the real CLI entry: it composes its OWN registry; the bundled plugins alone do not know the
# configured instances, and every endpoint Connection would then be unresolvable.
"""

from __future__ import annotations

import asyncio

from aigateway import purge_profile_history
from aigateway.config import Settings

from .conftest import Harness, put_key
from .fixtures import ACCOUNT_A, ACCOUNT_B, ENDPOINT_A, ENDPOINT_B, two_endpoint_document


def test_the_purge_keeps_every_configured_endpoint_key(byom: Harness) -> None:
    pairs = [(ACCOUNT_A, ENDPOINT_A), (ACCOUNT_B, ENDPOINT_A), (ACCOUNT_A, ENDPOINT_B)]
    with byom.start(two_endpoint_document()) as client:
        for account, provider in pairs:
            assert put_key(
                client, account, provider, f"key-{account[:4]}-{provider[-4:]}"
            ).is_success

    report = asyncio.run(
        purge_profile_history.run(Settings(), mode="apply", account=None, journal=None)
    )

    assert {result.account_id: result.skipped for result in report.accounts if result.skipped} == {}
    assert {ACCOUNT_A, ACCOUNT_B} <= {result.account_id for result in report.accounts}
    for account, provider in pairs:
        assert byom.stored_key(account, provider) == f"key-{account[:4]}-{provider[-4:]}"
    assert report.counts()["uuid_shaped_blobs"] == 0
