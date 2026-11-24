"""Frozen-copy chat replay answers carry `X-AIGW-Upstream-Attempts: 0` (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — a replay answers from a sealed copy and sends nothing
# upstream, so a hit, a replayed error, a miss and an unavailable copy all carry `0`.
# INVARIANT: the header is this request's own count, never the count of the captured call; the
# evidence stored in the copy is untouched. The classification replay route arrives with Unit 6
# (C9), which adds its own hit, miss and unavailable cases.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.unit.test_frozen_copy_support import CAPTURE_HEADER, COPY_HEADER, call_key

from .conftest import CHAT, HEADER, chat_body, connect, login, ok, respond
from .litellm_seam import OPENAI_COMPLETION, FakeTransport, connect_error_then

REPLAY_HEADER = "x-aigw-replay"


@pytest.fixture
def gateway(seam: FakeTransport, client: TestClient) -> TestClient:
    del seam
    return connect(login(client))


def _open(gateway: TestClient) -> str:
    response = gateway.post("/v1/frozen-copies")
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seal(gateway: TestClient, copy_id: str) -> None:
    response = gateway.post(f"/v1/frozen-copies/{copy_id}/seal")
    assert response.status_code == 200, response.text


def _captured(gateway: TestClient, body: dict[str, Any]) -> tuple[str, httpx.Response]:
    """A sealed copy holding the answer to one live call, and that live answer."""
    copy_id = _open(gateway)
    live = gateway.post(CHAT, json=body, headers={COPY_HEADER: copy_id, **call_key()})
    assert live.headers[CAPTURE_HEADER] == "stored", live.text
    _seal(gateway, copy_id)
    return copy_id, live


def _replay(gateway: TestClient, copy_id: str, body: dict[str, Any]) -> httpx.Response:
    return gateway.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions", json=body, headers=call_key()
    )


def test_a_replayed_hit_is_zero_whatever_the_capture_sent(
    gateway: TestClient, seam: FakeTransport
) -> None:
    seam.respond = connect_error_then(OPENAI_COMPLETION)
    body = chat_body("huggingface")
    copy_id, live = _captured(gateway, body)
    assert live.status_code == 200, live.text
    assert live.headers[HEADER] == "2"

    replay = _replay(gateway, copy_id, body)

    assert replay.status_code == 200, replay.text
    assert replay.headers[REPLAY_HEADER] == "hit"
    assert len(seam.sent) == 2
    assert replay.headers[HEADER] == "0"


def test_a_replayed_error_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    respond(seam, lambda _request: httpx.Response(400, json={"error": {"message": "bad"}}))
    body = chat_body("huggingface")
    copy_id, live = _captured(gateway, body)
    assert live.status_code >= 400, live.text
    assert live.headers[HEADER] == "1"

    replay = _replay(gateway, copy_id, body)

    assert replay.status_code == live.status_code, replay.text
    assert replay.headers[REPLAY_HEADER] == "error"
    assert len(seam.sent) == 1
    assert replay.headers[HEADER] == "0"


def test_a_miss_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    respond(seam, ok(OPENAI_COMPLETION))
    copy_id, _live = _captured(gateway, chat_body("huggingface"))

    replay = _replay(gateway, copy_id, chat_body("huggingface", temperature=0.7))

    assert replay.status_code == 404, replay.text
    assert replay.json()["detail"]["code"] == "frozen_copy_miss"
    assert len(seam.sent) == 1
    assert replay.headers[HEADER] == "0"


@pytest.mark.parametrize("copy", ["open", "unknown", "malformed"])
def test_an_unavailable_copy_is_zero(gateway: TestClient, seam: FakeTransport, copy: str) -> None:
    if copy == "open":
        copy_id = _open(gateway)
    else:
        copy_id = str(uuid4()) if copy == "unknown" else "not-a-copy-id"

    replay = _replay(gateway, copy_id, chat_body("huggingface"))

    assert replay.status_code == 404, replay.text
    assert replay.json()["detail"]["code"] == "frozen_copy_unavailable"
    assert seam.sent == []
    assert replay.headers[HEADER] == "0"
