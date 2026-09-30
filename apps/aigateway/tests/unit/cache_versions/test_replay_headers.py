"""Support: the response headers of a replay call (OME-1307, GW-replay).

FEATURE: OME-1307 (E14) - the engine reads `X-AIGW-Cache-Version` and the `key=` member of
`Cache-Status` to count version hits and repeated keys.
INVARIANT (ENG-replay C12): every 2xx answer to a call that carried a VALID grant has
`X-AIGW-Cache-Version: hit|miss` (a missing header counts as a version miss on the engine side).
INVARIANT: a call with no grant gets no replay header at all.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.ports import VersionHit
from aigateway.routes.chat_replay_stage import ReplayOutcome, replay_headers
from tests.unit.cache_versions.conftest import (
    BODY_H,
    BODY_NEW,
    frozen_version,
    mint_grant,
)
from tests.unit.test_chat_global_cache_route import _CHAT_PATH, _PATCH_TARGET, _DispatchCounter

_KEY = "0123456789abcdef" * 4
_GRANT_HEADER = "X-AIGW-Cache-Replay"


def test_replay_headers_of_a_call_without_a_grant_is_empty() -> None:
    assert replay_headers(None) == {}


def test_replay_headers_of_a_miss_is_the_version_header_only() -> None:
    keyed = ReplayOutcome(status="miss", key_hash=_KEY, hit=None)
    keyless = ReplayOutcome(status="miss", key_hash=None, hit=None)

    assert replay_headers(keyed) == {"X-AIGW-Cache-Version": "miss"}
    assert replay_headers(keyless) == {"X-AIGW-Cache-Version": "miss"}


def test_replay_headers_of_a_hit_has_the_quoted_key_member() -> None:
    outcome = ReplayOutcome(
        status="hit", key_hash=_KEY, hit=VersionHit(response={"a": 1}, metadata_json=None)
    )

    headers = replay_headers(outcome)

    assert headers == {
        "X-AIGW-Cache-Version": "hit",
        "Cache-Status": 'aigateway; hit; detail=version; key="0123456789ab"',
        "X-AIGW-Cache": "hit",
        "X-AIGW-Cache-Reason": "",
        "X-AIGW-Cache-Key": "0123456789ab",
    }
    # WHY quoted: `key` is an RFC 9211 String. The engine reads this member first, and a bare token
    # would give `key=None` there, so a repeated key would never be counted (RP-15).
    assert re.search(r'; key="[0-9a-f]{12}"$', headers["Cache-Status"])


def _plain(client: TestClient, body: dict[str, Any]) -> Any:
    with patch(_PATCH_TARGET, _DispatchCounter()):
        return client.post(_CHAT_PATH, json=body)


def test_a_call_without_a_grant_has_no_replay_header(
    replay_client: TestClient, credential_blobs: Any
) -> None:
    frozen_version(replay_client, credential_blobs)

    resp = _plain(replay_client, BODY_NEW)

    assert resp.status_code == 200, resp.text
    assert "X-AIGW-Cache-Version" not in resp.headers


def test_a_live_cache_hit_of_a_call_outside_the_version_is_a_version_miss(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    _plain(replay_client, BODY_NEW)  # fills the live cache; BODY_NEW is not in the version
    grant = mint_grant(grant_key, sub="admin", vid=version)

    with patch(_PATCH_TARGET, _DispatchCounter()):
        resp = replay_client.post(_CHAT_PATH, json=BODY_NEW, headers={_GRANT_HEADER: grant})

    assert resp.headers["X-AIGW-Cache"] == "hit"
    assert resp.headers["X-AIGW-Cache-Version"] == "miss"
    assert "detail=version" not in resp.headers.get("Cache-Status", "")


def test_a_streaming_call_with_a_grant_gets_a_version_miss(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    grant = mint_grant(grant_key, sub="admin", vid=version)

    async def _one_chunk(plugin: Any, body: dict[str, Any], *, provider: str) -> AsyncIterator[str]:
        yield 'data: {"choices": []}\n\n'

    with patch("aigateway.routes.chat._stream", _one_chunk):
        resp = replay_client.post(
            _CHAT_PATH, json={**BODY_H, "stream": True}, headers={_GRANT_HEADER: grant}
        )
        _ = resp.content

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache-Version"] == "miss"


def test_the_grant_header_never_reaches_the_provider(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    grant = mint_grant(grant_key, sub="admin", vid=version)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        replay_client.post(_CHAT_PATH, json=BODY_NEW, headers={_GRANT_HEADER: grant})

    assert len(counter.calls) == 1
    assert grant not in repr(counter.calls[0])
