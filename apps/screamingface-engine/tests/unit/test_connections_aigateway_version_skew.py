"""A Local Engine against a gateway older than L7a (OME-1138 close-out, OME-1832).

FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3-§4 — L7b's version-skew
fallback selected the `screamingface` row for one Engine release when no listed row carried
`effective`. That release has shipped, so a listing without the field breaks the listing contract
like any other malformed listing: a bad response, before any write. The Engine selects only by
`effective`.
INVARIANT: choosing the effective row never reads the label (repair planning still does); a row
without the flag is never guessed at.
"""

from __future__ import annotations

import logging

import pytest
from aigateway_effective_support import ABSENT, OTHER_ID, SECRET, Gateway, provider, row

from screamingface_engine.connections.port import Caller, Connection, ConnectionBadResponse

pytestmark = pytest.mark.asyncio

ROWS_LOGGER = "screamingface_engine.connections.aigateway_rows"
BOTH = provider("openrouter", "OpenRouter", ("api_key", "oauth"))

# Listings as a gateway older than L7a serves them: no row carries the field.
_UNFLAGGED_LISTINGS = {
    "the labelled row alone": [row(effective=ABSENT)],
    "a user row beside the labelled one": [
        row(OTHER_ID, label="research", effective=ABSENT),
        row(effective=ABSENT),
    ],
    "one user row and no labelled one": [row(OTHER_ID, label="research", effective=ABSENT)],
}


async def _run(gateway: Gateway, operation: str) -> object:
    adapter = gateway.adapter()
    operations = {
        "list": lambda: adapter.list(Caller()),
        "connect": lambda: adapter.connect(Caller(), "openrouter", SECRET),
        "start_oauth": lambda: adapter.start_oauth(Caller(), "openrouter"),
        "disconnect": lambda: adapter.disconnect(Caller(), "openrouter"),
    }
    return await operations[operation]()


@pytest.mark.parametrize("listing", list(_UNFLAGGED_LISTINGS))
@pytest.mark.parametrize("operation", ["list", "connect", "start_oauth", "disconnect"])
async def test_a_listing_without_the_field_is_a_bad_response_before_any_write(
    operation: str, listing: str
) -> None:
    rows = [dict(listed) for listed in _UNFLAGGED_LISTINGS[listing]]
    gateway = Gateway(*rows, providers=(BOTH,), access={"openrouter": "connected"})

    with pytest.raises(ConnectionBadResponse):
        await _run(gateway, operation)

    assert gateway.writes() == []


async def test_a_listing_without_the_field_logs_no_fallback_notice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = Gateway(row(effective=ABSENT), access={"openrouter": "connected"})
    caplog.set_level(logging.DEBUG, logger=ROWS_LOGGER)

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())

    assert [record for record in caplog.records if record.name == ROWS_LOGGER] == []


async def test_a_listing_with_zero_rows_still_lists_the_gateway_status() -> None:
    # WHY: an empty listing carries no row to break the contract; the status is the gateway's.
    gateway = Gateway(access={"openrouter": "not_connected"})

    assert await gateway.adapter().list(Caller()) == (
        Connection("openrouter", "OpenRouter", ("api_key",), "not_connected"),
    )
