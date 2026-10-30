"""A capture run can record a picture call as large as the gateway accepts (OME-1756).

FEATURE: OME-1307 frozen copy. One entry holds the request plus the response the caller received,
as compact JSON. The gateway accepts a request body of up to ``max_request_bytes`` (8 MiB).
INVARIANT: the default entry cap is that request cap plus a fixed response headroom, so a picture
call at the request cap fits one entry. Two calls still do not fit, and only their capture fails
(see ``FROZEN_COPY_RESPONSE_HEADROOM_BYTES``): a response over the headroom, and a request that
grows when re-serialised. Before this, the entry cap was a fixed 2,000,000 B and a picture
Case (MMMU, LAB-Bench FigQA and TableQA carry their pictures inline) was answered but never stored,
so its replay missed with ``frozen_copy_miss``.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.config import FROZEN_COPY_RESPONSE_HEADROOM_BYTES, Settings
from aigateway.core.frozen_copy.store import FrozenCopyEntryTooLarge, FrozenCopyStore
from tests.unit.test_frozen_copy_support import (
    CAPTURE_HEADER,
    CHAT_PATH,
    COPY_HEADER,
    PATCH_TARGET,
    DispatchCounter,
    account_id_of,
    arrange_provider,
    call_key,
    chat_body,
    chat_response,
    run_async,
    seal_copy,
    seed_copy,
    stored_entries,
)

_REQUEST_CAP_ENV = "AIGW_MAX_REQUEST_BYTES"
_ENTRY_CAP_ENV = "AIGW_FROZEN_COPY_MAX_ENTRY_BYTES"
_DEFAULT_REQUEST_CAP = 8 * 1024 * 1024


@pytest.fixture
def _default_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both caps at their code defaults, whatever the shell exports. List BEFORE a client."""
    monkeypatch.delenv(_REQUEST_CAP_ENV, raising=False)
    monkeypatch.delenv(_ENTRY_CAP_ENV, raising=False)


def _picture_chat_body(total_wire_bytes: int) -> dict[str, Any]:
    """A one-picture chat body whose compact JSON is exactly ``total_wire_bytes`` long.

    The picture is a PNG data URI the way the engine sends a picture Case: base64 inline.
    """
    prefix = "data:image/png;base64,"

    def _body(payload: str, text: str) -> dict[str, Any]:
        picture = {"type": "image_url", "image_url": {"url": prefix + payload}}
        question = {"type": "text", "text": text}
        return chat_body(messages=[{"role": "user", "content": [question, picture]}])

    envelope = _wire_bytes(_body("", ""))
    # Base64 comes in 4-character groups; the 0-3 bytes left over go into the question text.
    payload = "A" * ((total_wire_bytes - envelope) // 4 * 4)
    text = "x" * (total_wire_bytes - _wire_bytes(_body(payload, "")))
    body = _body(payload, text)
    assert _wire_bytes(body) == total_wire_bytes
    assert base64.b64decode(payload, validate=True)
    return body


def _wire_bytes(value: Any) -> int:
    """The bytes of ``value`` as the store counts them: compact JSON, UTF-8."""
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


# --- 1. the default entry cap is derived from the request cap ---------------------------------


def test_the_default_entry_cap_is_the_request_cap_plus_the_response_headroom(
    _default_caps: None,
) -> None:
    """Fails if the entry cap is set back to a fixed number below the request cap."""
    settings = Settings()

    assert settings.max_request_bytes == _DEFAULT_REQUEST_CAP
    assert settings.frozen_copy_max_entry_bytes == (
        settings.max_request_bytes + FROZEN_COPY_RESPONSE_HEADROOM_BYTES
    )
    assert settings.frozen_copy_max_entry_bytes > settings.max_request_bytes
    assert FROZEN_COPY_RESPONSE_HEADROOM_BYTES > 0


def test_raising_the_request_cap_raises_the_entry_cap_with_it(
    _default_caps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator who lets in 16 MiB calls must not silently lose their capture."""
    monkeypatch.setenv(_REQUEST_CAP_ENV, str(16 * 1024 * 1024))

    settings = Settings()

    assert settings.frozen_copy_max_entry_bytes == (
        16 * 1024 * 1024 + FROZEN_COPY_RESPONSE_HEADROOM_BYTES
    )


def test_an_explicit_entry_cap_still_wins(
    _default_caps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The setting stays an operator's override; the size-cap tests rely on a small one."""
    monkeypatch.setenv(_ENTRY_CAP_ENV, "300")

    assert Settings().frozen_copy_max_entry_bytes == 300


# --- 2. the store records an entry as large as the gateway accepts ----------------------------


def test_an_entry_at_the_request_cap_is_stored_and_read_back_unchanged(
    _default_caps: None, authenticated_client: TestClient
) -> None:
    client = authenticated_client
    settings = Settings()
    request = _picture_chat_body(settings.max_request_bytes)
    response = chat_response("picture-answer")
    store = FrozenCopyStore(max_entry_bytes=settings.frozen_copy_max_entry_bytes)
    owner = account_id_of(client)

    async def _capture_then_find() -> tuple[Any, Any]:
        copy = await store.open(owner)
        await store.capture(copy, "chat", request, response, 200, case_key="", occurrence=0)
        entry = await store.find(copy, "chat", request, None, "", 0)
        assert entry is not None
        return entry.request_json, entry.response_json

    stored_request, stored_response = run_async(client, _capture_then_find)

    assert _wire_bytes(stored_request) == _wire_bytes(request)
    assert stored_request == request
    assert stored_response == response


def test_an_entry_one_byte_over_the_derived_cap_is_still_refused(
    _default_caps: None, authenticated_client: TestClient
) -> None:
    """The cap moved; it did not go away."""
    client = authenticated_client
    cap = Settings().frozen_copy_max_entry_bytes
    response = chat_response("picture-answer")
    request = _picture_chat_body(cap - _wire_bytes(response) + 1)
    store = FrozenCopyStore(max_entry_bytes=cap)
    owner = account_id_of(client)

    async def _capture() -> None:
        copy = await store.open(owner)
        with pytest.raises(FrozenCopyEntryTooLarge):
            await store.capture(copy, "chat", request, response, 200, case_key="", occurrence=0)

    run_async(client, _capture)


# --- 3. the whole path: a picture call at the request cap captures and replays ----------------


@pytest.fixture
def default_cap_capture_client(
    _default_caps: None, authenticated_client: TestClient, credential_blobs, monkeypatch
) -> TestClient:
    """A signed-in client on the default caps whose provider call is a stand-in counter."""
    arrange_provider(authenticated_client, credential_blobs)
    monkeypatch.setattr(PATCH_TARGET, DispatchCounter())
    return authenticated_client


def test_a_picture_call_at_the_request_cap_is_stored_and_replays(
    default_cap_capture_client: TestClient,
) -> None:
    """The largest body the gateway accepts: exactly ``max_request_bytes`` on the wire."""
    client = default_cap_capture_client
    request_cap = Settings().max_request_bytes
    body = _picture_chat_body(request_cap)
    # WHY send our own bytes: the request cap counts the bytes on the wire, so the test fixes them
    # itself rather than trusting the HTTP client's JSON spacing.
    wire = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert len(wire) == request_cap
    copy_id = seed_copy(client, account_id_of(client), [], seal=False)

    live = client.post(
        CHAT_PATH,
        content=wire,
        headers={"content-type": "application/json", COPY_HEADER: copy_id, **call_key()},
    )

    assert live.status_code == 200, live.text
    assert live.headers[CAPTURE_HEADER] == "stored"
    (entry,) = stored_entries(client, copy_id)
    assert entry["request"] == body
    assert entry["response"] == live.json()

    seal_copy(client, copy_id)
    replay = client.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions", json=body, headers=call_key()
    )

    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == live.json()["id"]
    assert replay.json()["choices"] == live.json()["choices"]
