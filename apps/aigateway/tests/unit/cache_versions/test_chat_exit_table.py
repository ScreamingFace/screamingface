"""The chat route's exit table: one capture row and one header set per way a call can end.

FEATURE: OME-1307 (E14) - every exit of ``chat_completions`` says how the call was answered, and
the route records capture once at that exit. This table pins the observable result of each exit
(status, cache headers, the single capture row, whether the answer rides inline, the counters), so
the route's structure can change and the behaviour cannot.
INVARIANT (CV-3): a capture failure never changes the chat response.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheCaptureEntry
from aigateway.core.cache_versions.ports import CaptureRecord
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.routes.chat_cache_stage import KEY_PREFIX_LENGTH
from tests.unit.cache_versions.conftest import (
    BODY_B,
    BODY_NEW,
    BODY_S,
    frozen_version,
    mint_grant,
    traceparent,
)
from tests.unit.test_chat_global_cache_route import _CHAT_PATH, _PATCH_TARGET, _DispatchCounter

_GRANT_HEADER = "X-AIGW-Cache-Replay"
_CACHE_HEADERS = (
    "X-AIGW-Cache",
    "X-AIGW-Cache-Reason",
    "X-AIGW-Cache-Key",
    "X-AIGW-Cache-Write",
    "X-AIGW-Cache-Version",
    "Cache-Status",
)
_ORDERED_PREFIXES = ("x-aigw-", "cache-status")
_ANSWER = "PLAINTEXT-ANSWER-42"


def _state(client: TestClient) -> Any:
    app: Any = client.app
    return app.state


def _rows(client: Any, trace_id: str) -> list[CacheCaptureEntry]:
    async def _load() -> list[CacheCaptureEntry]:
        return await CacheCaptureEntry.filter(trace_id=trace_id).order_by("ordinal")

    return client.portal.call(_load)


def _delete_live_cache(client: Any) -> None:
    async def _delete() -> None:
        await RequestCacheEntry.all().delete()

    client.portal.call(_delete)


def _trace(index: int) -> str:
    return f"{0x20 + index:02x}" * 16


@dataclass
class _Env:
    client: TestClient
    version: UUID
    grant: str
    forged: str
    trace: str

    def post(
        self,
        body: dict[str, Any],
        *,
        grant: bool = False,
        traced: bool = True,
        forged: bool = False,
        counter: _DispatchCounter | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if traced:
            headers["traceparent"] = traceparent(self.trace)
        if grant:
            headers[_GRANT_HEADER] = self.grant
        if forged:
            headers[_GRANT_HEADER] = self.forged
        with patch(_PATCH_TARGET, counter or _DispatchCounter()):
            return self.client.post(_CHAT_PATH, json=body, headers=headers)


# --- the scenarios: one per exit of the route ---------------------------------------------------


def _x1_invalid_grant(env: _Env) -> Any:
    return env.post(BODY_NEW, forged=True)


def _x2_version_hit(env: _Env) -> Any:
    # WHY: with the live cache emptied only the frozen version can answer S.
    _delete_live_cache(env.client)
    return env.post(BODY_S, grant=True)


def _x3_global_hit(env: _Env) -> Any:
    env.post(BODY_NEW, traced=False)
    return env.post(BODY_NEW)


def _x3_global_hit_with_grant(env: _Env) -> Any:
    env.post(BODY_NEW, traced=False)
    return env.post(BODY_NEW, grant=True)


def _x4_stage_two_refusal(env: _Env) -> Any:
    # The token store is emptied, so credential resolution refuses the call AFTER capture began.
    async def _refuse(*args: Any, **kwargs: Any) -> None:
        raise HTTPException(status_code=409, detail="no usable connection")

    with patch("aigateway.routes.chat._resolve_credential_target", _refuse):
        return env.post(BODY_NEW)


def _x5_stream_with_grant(env: _Env) -> Any:
    async def _one_chunk(plugin: Any, body: dict[str, Any], *, provider: str) -> AsyncIterator[str]:
        yield 'data: {"choices": []}\n\n'

    streaming = {**BODY_NEW, "stream": True}
    with patch("aigateway.routes.chat._stream", _one_chunk):
        resp = env.post(streaming, grant=True)
        _ = resp.content
    return resp


def _x6_dispatch_failure(env: _Env) -> Any:
    async def _refuse(body: dict[str, Any]) -> None:
        raise HTTPException(status_code=418, detail="the provider refused")

    with patch(_PATCH_TARGET, _refuse):
        return env.client.post(
            _CHAT_PATH, json=BODY_NEW, headers={"traceparent": traceparent(env.trace)}
        )


def _x7a_stored(env: _Env) -> Any:
    return env.post(BODY_NEW)


def _x7a_stored_with_grant(env: _Env) -> Any:
    return env.post(BODY_NEW, grant=True)


def _x7b_unstored(env: _Env) -> Any:
    async def _lost_race(*args: Any, **kwargs: Any) -> str:
        return "race_lost"

    with patch("aigateway.routes.chat.store_global_response", _lost_race):
        return env.post(BODY_NEW)


def _x7c_bypass(env: _Env) -> Any:
    return env.post(BODY_B)


@dataclass(frozen=True)
class _Expect:
    status: int
    # Exact header values. ``"key"`` is the 12-character prefix of the row's key hash.
    headers: dict[str, str]
    outcome: str
    inline: bool
    key: bool = True
    replay_lookup: str | None = None


_VERSION_HIT_HEADERS = {
    "X-AIGW-Cache": "hit",
    "X-AIGW-Cache-Reason": "",
    "X-AIGW-Cache-Key": "key",
    "X-AIGW-Cache-Version": "hit",
    "Cache-Status": "key",
}

_CASES: list[Any] = [
    pytest.param(
        _x1_invalid_grant,
        _Expect(403, {}, "error", inline=False, replay_lookup="invalid_grant"),
        id="X1-invalid-grant",
    ),
    pytest.param(
        _x2_version_hit,
        _Expect(200, _VERSION_HIT_HEADERS, "version_hit", inline=True, replay_lookup="hit"),
        id="X2-version-hit",
    ),
    pytest.param(
        _x3_global_hit,
        _Expect(
            200,
            {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "", "X-AIGW-Cache-Key": "key"},
            "hit",
            inline=False,
        ),
        id="X3-global-hit",
    ),
    pytest.param(
        _x3_global_hit_with_grant,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "hit",
                "X-AIGW-Cache-Reason": "",
                "X-AIGW-Cache-Key": "key",
                "X-AIGW-Cache-Version": "miss",
            },
            "hit",
            inline=False,
            replay_lookup="miss",
        ),
        id="X3-global-hit-with-grant",
    ),
    pytest.param(
        _x4_stage_two_refusal,
        _Expect(409, {}, "error", inline=False),
        id="X4-stage-two-refusal",
    ),
    pytest.param(
        _x5_stream_with_grant,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "bypass",
                "X-AIGW-Cache-Reason": "stream",
                "X-AIGW-Cache-Version": "miss",
            },
            "bypass",
            inline=False,
            key=False,
            replay_lookup="miss",
        ),
        id="X5-stream-with-grant",
    ),
    pytest.param(
        _x6_dispatch_failure,
        _Expect(502, {}, "error", inline=False),
        id="X6-dispatch-failure",
    ),
    pytest.param(
        _x7a_stored,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "miss",
                "X-AIGW-Cache-Reason": "",
                "X-AIGW-Cache-Key": "key",
                "X-AIGW-Cache-Write": "stored",
            },
            "stored",
            inline=False,
        ),
        id="X7a-stored",
    ),
    pytest.param(
        _x7a_stored_with_grant,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "miss",
                "X-AIGW-Cache-Reason": "",
                "X-AIGW-Cache-Key": "key",
                "X-AIGW-Cache-Write": "stored",
                "X-AIGW-Cache-Version": "miss",
            },
            "stored",
            inline=False,
            replay_lookup="miss",
        ),
        id="X7a-stored-with-grant",
    ),
    pytest.param(
        _x7b_unstored,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "miss",
                "X-AIGW-Cache-Reason": "",
                "X-AIGW-Cache-Key": "key",
                "X-AIGW-Cache-Write": "race_lost",
            },
            "unstored",
            inline=True,
        ),
        id="X7b-unstored",
    ),
    pytest.param(
        _x7c_bypass,
        _Expect(
            200,
            {
                "X-AIGW-Cache": "bypass",
                "X-AIGW-Cache-Reason": "opted_out",
            },
            "bypass",
            inline=True,
        ),
        id="X7c-bypass",
    ),
]


@pytest.fixture
def env_factory(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> Callable[[int], _Env]:
    def _make(index: int) -> _Env:
        version = frozen_version(replay_client, credential_blobs)
        return _Env(
            client=replay_client,
            version=version,
            grant=mint_grant(grant_key, sub="admin", vid=version),
            forged=mint_grant(Ed25519PrivateKey.generate(), sub="admin", vid=version),
            trace=_trace(index),
        )

    return _make


@pytest.mark.parametrize(("scenario", "expect"), _CASES)
def test_each_exit_answers_with_one_row_and_its_headers(
    scenario: Callable[[_Env], Any], expect: _Expect, env_factory: Callable[[int], _Env]
) -> None:
    env = env_factory(len(_CASES))
    state = _state(env.client)
    before_rows = dict(state.capture_stats.rows)
    before_lookups = dict(state.capture_stats.replay_lookups)

    resp = scenario(env)

    assert resp.status_code == expect.status, resp.text
    rows = _rows(env.client, env.trace)
    assert [row.outcome for row in rows] == [expect.outcome]
    row = rows[0]
    assert (row.key_hash is not None) is expect.key
    assert (row.response_json is not None) is expect.inline
    prefix = row.key_hash[:KEY_PREFIX_LENGTH] if row.key_hash else None
    for name in _CACHE_HEADERS:
        if name in expect.headers:
            wanted = expect.headers[name]
            if wanted == "key":
                wanted = (
                    f'aigateway; hit; detail=version; key="{prefix}"'
                    if name == "Cache-Status"
                    else cast(str, prefix)
                )
            assert resp.headers.get(name) == wanted, name
        else:
            assert name not in resp.headers, name
    if expect.inline:
        inline = json.loads(cast(str, row.response_json))
        assert "_aigw" not in inline, "the stored body is the provider-compatible form"
        assert inline["choices"][0]["message"]["content"]
    after_rows = dict(state.capture_stats.rows)
    delta = {k: after_rows.get(k, 0) - before_rows.get(k, 0) for k in after_rows}
    assert {k: v for k, v in delta.items() if v} == {expect.outcome: 1}
    after_lookups = dict(state.capture_stats.replay_lookups)
    lookup_delta = {k: after_lookups.get(k, 0) - before_lookups.get(k, 0) for k in after_lookups}
    expected_lookups = {expect.replay_lookup: 1} if expect.replay_lookup else {}
    assert {k: v for k, v in lookup_delta.items() if v} == expected_lookups


def test_the_version_hit_row_holds_the_frozen_answer(env_factory: Callable[[int], _Env]) -> None:
    env = env_factory(len(_CASES) + 1)

    resp = _x2_version_hit(env)

    row = _rows(env.client, env.trace)[0]
    assert json.loads(cast(str, row.response_json))["choices"] == resp.json()["choices"]


def test_the_stored_row_is_the_clean_provider_body_while_the_reply_carries_metadata(
    env_factory: Callable[[int], _Env],
) -> None:
    env = env_factory(len(_CASES) + 2)

    resp = _x7b_unstored(env)

    inline = json.loads(cast(str, _rows(env.client, env.trace)[0].response_json))
    assert "_aigw" not in inline
    assert "_aigw" in resp.json(), "positive control: the reply does carry the metadata block"
    assert inline["choices"][0]["message"]["content"] == _ANSWER


# --- header order -------------------------------------------------------------------------------


def _ordered_names(resp: Any) -> list[str]:
    return [
        name
        for name, _ in resp.headers.multi_items()
        if name.lower().startswith(_ORDERED_PREFIXES) and name.lower() != "x-aigw-trace-id"
    ]


# Recorded from the route BEFORE the single-exit refactor. A change here is a header-order change.
_GLOBAL_HIT_ORDER = [
    "x-aigw-cache",
    "x-aigw-cache-reason",
    "x-aigw-cache-key",
    "x-aigw-cache-version",
]
_STORED_ORDER = [
    "x-aigw-cache",
    "x-aigw-cache-reason",
    "x-aigw-cache-key",
    "x-aigw-cache-write",
    "x-aigw-cache-version",
]


@pytest.mark.parametrize(
    ("scenario", "order"),
    [
        pytest.param(_x3_global_hit_with_grant, _GLOBAL_HIT_ORDER, id="global-hit-with-grant"),
        pytest.param(_x7a_stored_with_grant, _STORED_ORDER, id="stored-with-grant"),
    ],
)
def test_header_order_is_global_then_replay(
    scenario: Callable[[_Env], Any], order: list[str], env_factory: Callable[[int], _Env]
) -> None:
    env = env_factory(len(_CASES) + 3)

    resp = scenario(env)

    assert _ordered_names(resp) == order


# --- capture failure ----------------------------------------------------------------------------


class _RaisingSink:
    async def record(self, record: CaptureRecord) -> None:
        raise RuntimeError("the capture store is down")


def _normalised(resp: Any) -> tuple[int, list[tuple[str, str]], str]:
    """The response as sent, with the one per-call id (the gateway call id) masked."""
    text = re.sub(r"call_[0-9a-f]{32}", "call_<id>", resp.text)
    return resp.status_code, resp.headers.multi_items(), text


@pytest.mark.parametrize(
    "scenario", [_x2_version_hit, _x3_global_hit_with_grant], ids=["version", "global"]
)
def test_a_raising_sink_leaves_the_response_unchanged(
    scenario: Callable[[_Env], Any], env_factory: Callable[[int], _Env]
) -> None:
    env = env_factory(len(_CASES) + 4)
    state = _state(env.client)
    control = scenario(env)
    assert control.status_code == 200, control.text
    assert state.capture_stats.failures == 0

    state.capture_sink = _RaisingSink()
    failed = scenario(env)

    assert state.capture_stats.failures == 1
    assert _normalised(failed) == _normalised(control)
