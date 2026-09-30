"""The SDK names an Engine refusal by its top-level problem `code` (E14 RP-X2).

FEATURE: E14 reproducible submission — the Engine refuses a bad cache-version replay start with
`replay_grant_too_large`, `replay_grant_ambiguous` or `replay_unsupported`.
STORY: as a researcher whose replay start is refused, I catch the error by `error.code` and
see which refusal it was, not `about:blank`.

Contract: `docs/spec/2026-09-29-e14-reproducible-submission/contracts.md`, "Error bodies":
"The SDK maps the error by `code` first."
"""

from __future__ import annotations

import httpx
import pytest

from screamingface._engine.transport import _start_async, _start_sync
from screamingface.errors import ExecutionError

_PROBLEM = {"content-type": "application/problem+json"}

# The Engine's C1 refusals: (HTTP status, top-level `code`).
_C1_REFUSALS = [
    (431, "replay_grant_too_large"),
    (400, "replay_grant_ambiguous"),
    (503, "replay_unsupported"),
]


def _refusal(status: int, body: dict[str, object]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body, headers=_PROBLEM))


def _engine_body(status: int, code: str) -> dict[str, object]:
    # The Engine's shape: `type` stays `about:blank`; the refusal is the top-level `code`.
    return {
        "type": "about:blank",
        "title": "refused",
        "status": status,
        "detail": "d",
        "code": code,
    }


@pytest.mark.parametrize(("status", "code"), _C1_REFUSALS)
def test_a_c1_refusal_is_named_by_its_code(status: int, code: str) -> None:
    transport = _refusal(status, _engine_body(status, code))
    with httpx.Client(base_url="http://engine.test", transport=transport) as http:
        with pytest.raises(ExecutionError) as caught:
            _start_sync(http, "capability", "(@)!'hello'")

    assert caught.value.code == code
    assert caught.value.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "code"), _C1_REFUSALS)
async def test_async_a_c1_refusal_is_named_by_its_code(status: int, code: str) -> None:
    transport = _refusal(status, _engine_body(status, code))
    async with httpx.AsyncClient(base_url="http://engine.test", transport=transport) as http:
        with pytest.raises(ExecutionError) as caught:
            await _start_async(http, "capability", "(@)!'hello'")

    assert caught.value.code == code
    assert caught.value.status == status


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # INVARIANT: a problem with no `code` keeps the code it always had, taken from `type`.
        ({"type": "urn:sf:legacy", "detail": "d"}, "urn:sf:legacy"),
        ({"type": "about:blank", "detail": "d"}, "about:blank"),
        # A blank or non-string `code` is no code: fall back to `type`.
        ({"type": "about:blank", "detail": "d", "code": "  "}, "about:blank"),
        ({"type": "about:blank", "detail": "d", "code": 7}, "about:blank"),
    ],
)
def test_without_a_usable_code_the_type_is_still_the_code(
    body: dict[str, object], expected: str
) -> None:
    with httpx.Client(base_url="http://engine.test", transport=_refusal(422, body)) as http:
        with pytest.raises(ExecutionError) as caught:
            _start_sync(http, "capability", "(@)!'hello'")

    assert caught.value.code == expected


def test_a_replay_refusal_is_sent_once() -> None:
    # WHY: only a capacity 503 (problem+json WITH Retry-After) is waited out and re-sent.
    # `replay_unsupported` is also a 503 but is a refusal to carry a replay, not a full
    # runner, so it must surface at the first send.
    sends: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sends.append(1)
        return httpx.Response(503, json=_engine_body(503, "replay_unsupported"), headers=_PROBLEM)

    with httpx.Client(
        base_url="http://engine.test", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ExecutionError):
            _start_sync(http, "capability", "(@)!'hello'")

    assert len(sends) == 1
