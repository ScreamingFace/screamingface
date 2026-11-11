"""A Run state that is not a string is a malformed answer (E5 P1 spec D7, §4.1; plan C1).

FEATURE: first-class Runs (OME-1785). INVARIANT (D7): any malformed `POST /runs` answer is one
`Unavailable`, never an exception; a malformed read is `engine_contract_error`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_runs_wire import _SPEC, RUN_ID, _async_request, _record, _request

from screamingface._engine import runs as wire
from screamingface.errors import ExecutionError


def _candidate_state(state: object) -> dict[str, Any]:
    record = _record()
    record["candidates"][0]["state"] = state
    return record


# WHY lists and objects: they are unhashable, so a set lookup on them raises TypeError.
_BODIES = [
    _record(state=[]),
    _record(state={"running": True}),
    _candidate_state([]),
    _candidate_state({"state": "succeeded"}),
]
_IDS = ["run-list", "run-object", "candidate-list", "candidate-object"]


@pytest.mark.parametrize("body", _BODIES, ids=_IDS)
def test_a_registration_with_an_unhashable_state_is_unavailable(body: object) -> None:
    answer = httpx.Response(201, json=body)

    assert isinstance(wire.create_sync(_request(lambda _r: answer, []), _SPEC), wire.Unavailable)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", _BODIES, ids=_IDS)
async def test_an_async_registration_with_an_unhashable_state_is_unavailable(
    body: object,
) -> None:
    request = _async_request(lambda _r: httpx.Response(201, json=body))

    assert isinstance(await wire.create_async(request, _SPEC), wire.Unavailable)


@pytest.mark.parametrize("body", _BODIES, ids=_IDS)
def test_a_read_with_an_unhashable_state_is_a_contract_error(body: object) -> None:
    with pytest.raises(ExecutionError) as caught:
        wire.get_sync(_request(lambda _r: httpx.Response(200, json=body), []), RUN_ID)

    assert caught.value.code == "engine_contract_error"
