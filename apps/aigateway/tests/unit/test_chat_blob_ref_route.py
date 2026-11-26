"""`POST /v1/chat/completions` by blob reference, end to end through the real app (OME-1970, PR 5).

FEATURE: Case files by blob reference. The Engine uploads a Case file once per run through the
real upload route (`PUT /v1/blobs/sha256/{digest}`, PR 4), then sends each model call with a
**reference part** (``blob:sha256/<64 hex>`` plus ``x_media_type`` and ``x_size``) and the run's
token in ``X-AIGW-Run-Token``.

INVARIANT under test:
- decision 2: a reference call and the same call inline share ONE key in the response cache
  and in the frozen copy (pinned cache), so no cached answer or pinned copy is lost;
- decision 3: the scope check runs before the cache lookup, so another run's token, or none,
  gets ``blob_unknown`` even when a cached answer for the same file exists;
- the provider receives exactly the inline request, the swap happening inside the upstream slot,
  and a file the store dropped by then is ``blob_unknown`` with zero upstream calls.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.store import request_digest
from aigateway.core.media_store import BlobScope, MediaStore, StoredMedia
from aigateway.routes import chat as chat_route
from tests.unit.test_frozen_copy_support import (
    CAPTURE_HEADER,
    CASE_A,
    CHAT_PATH,
    COPY_HEADER,
    PATCH_TARGET,
    DispatchCounter,
    account_id_of,
    arrange_provider,
    call_key,
    chat_response,
    seed_copy,
    seed_keyed_copy,
    stored_entries,
)

# A real PNG signature, so the upload route stores it as `image/png` by its leading bytes.
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PNG_SHA = hashlib.sha256(PNG).hexdigest()
PNG_B64 = base64.b64encode(PNG).decode("ascii")
# Stand-ins for two runs' random tokens (the Engine mints `secrets.token_urlsafe(32)`).
RUN_1 = "run1-" + "A" * 38
RUN_2 = "run2-" + "B" * 38
RUN_TOKEN_HEADER = "X-AIGW-Run-Token"
CACHE_HEADER = "X-AIGW-Cache"
KEY_HEADER = "X-AIGW-Cache-Key"


def _messages(picture: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [{"type": "text", "text": "What does the figure show?"}, picture],
        }
    ]


def _inline_body() -> dict[str, Any]:
    """Today's call: the picture's base64 inside the request."""
    picture = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}}
    return {"model": "anthropic/claude-haiku-4-5", "messages": _messages(picture)}


def _reference_body(**extra: Any) -> dict[str, Any]:
    """The same call with the picture by reference, as the Engine sends it after an upload."""
    picture = {
        "type": "image_url",
        "image_url": {"url": f"blob:sha256/{PNG_SHA}"},
        "x_media_type": "image/png",
        "x_size": len(PNG),
    }
    return {"model": "anthropic/claude-haiku-4-5", "messages": _messages(picture), **extra}


def _upload(client: TestClient, token: str = RUN_1) -> None:
    response = client.put(
        f"/v1/blobs/sha256/{PNG_SHA}", content=PNG, headers={RUN_TOKEN_HEADER: token}
    )
    assert response.status_code == 201, response.text
    assert response.json()["media_type"] == "image/png"


def _chat(
    client: TestClient, body: dict[str, Any], *, token: str | None = RUN_1, **headers: str
) -> Any:
    sent: dict[str, str] = dict(headers)
    if token is not None:
        sent[RUN_TOKEN_HEADER] = token
    return client.post(CHAT_PATH, json=body, headers=sent)


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> DispatchCounter:
    """Stands in for the Anthropic provider call; records every body it is handed."""
    stub = DispatchCounter()
    monkeypatch.setattr(PATCH_TARGET, stub)
    return stub


@pytest.fixture
def ref_client(
    authenticated_client: TestClient, credential_blobs: Any, counter: DispatchCounter
) -> TestClient:
    arrange_provider(authenticated_client, credential_blobs)
    return authenticated_client


@pytest.fixture
def _cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read at app creation, so a test using it lists it BEFORE the client fixture.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_client(_cache_env: None, ref_client: TestClient) -> TestClient:
    return ref_client


def _blob_unknown(response: Any) -> None:
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "blob_unknown"
    # INVARIANT: neither the token nor the file's bytes travel back in the refusal.
    assert RUN_1 not in response.text and RUN_2 not in response.text
    assert PNG_B64[:40] not in response.text


# --- decision 2: one key, both ways ------------------------------------------------------------


def test_a_reference_call_is_served_the_inline_calls_cached_answer_under_the_same_key(
    cache_client: TestClient, counter: DispatchCounter
) -> None:
    inline = _chat(cache_client, _inline_body(), token=None)
    assert inline.status_code == 200, inline.text
    assert inline.headers[CACHE_HEADER] == "miss"
    _upload(cache_client)

    by_reference = _chat(cache_client, _reference_body())

    assert by_reference.status_code == 200, by_reference.text
    assert by_reference.headers[CACHE_HEADER] == "hit"
    assert by_reference.headers[KEY_HEADER] == inline.headers[KEY_HEADER]
    assert by_reference.json()["id"] == inline.json()["id"]
    assert len(counter.calls) == 1, "the hit spent nothing upstream"


def test_an_inline_call_is_served_the_reference_calls_cached_answer(
    cache_client: TestClient, counter: DispatchCounter
) -> None:
    _upload(cache_client)
    first = _chat(cache_client, _reference_body())
    assert first.status_code == 200, first.text
    assert first.headers[CACHE_HEADER] == "miss"

    inline = _chat(cache_client, _inline_body(), token=None)

    assert inline.headers[CACHE_HEADER] == "hit"
    assert inline.headers[KEY_HEADER] == first.headers[KEY_HEADER]
    assert len(counter.calls) == 1


def test_the_provider_receives_exactly_the_inline_request(
    ref_client: TestClient, counter: DispatchCounter
) -> None:
    assert _chat(ref_client, _inline_body(), token=None).status_code == 200
    _upload(ref_client)

    response = _chat(ref_client, _reference_body())

    assert response.status_code == 200, response.text
    inline_sent, reference_sent = counter.calls
    assert reference_sent == inline_sent
    assert f"blob:sha256/{PNG_SHA}" not in str(reference_sent)
    assert "x_media_type" not in str(reference_sent)


def test_a_captured_reference_call_is_stored_in_reference_form_under_the_inline_digest(
    ref_client: TestClient,
) -> None:
    copy_id = seed_copy(ref_client, account_id_of(ref_client), [], seal=False)
    _upload(ref_client)

    response = _chat(ref_client, _reference_body(), **{COPY_HEADER: copy_id}, **call_key(CASE_A))

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "stored"
    (entry,) = stored_entries(ref_client, copy_id)
    # The inline call's pinned digest is the one a published run's replay looks up.
    assert entry["digest"] == request_digest("chat", _inline_body())
    # WHY reference form: the row stays a few KB; it never holds the file, the token or `x_` keys.
    picture = entry["request"]["messages"][0]["content"][1]
    assert picture == {"type": "image_url", "image_url": {"url": f"blob:sha256/{PNG_SHA}"}}
    assert RUN_1 not in str(entry["request"])


# --- decision 3: the scope check, before the cache lookup --------------------------------------


def test_another_runs_token_gets_blob_unknown_even_with_a_cached_answer(
    cache_client: TestClient, counter: DispatchCounter
) -> None:
    assert _chat(cache_client, _inline_body(), token=None).status_code == 200
    _upload(cache_client, token=RUN_1)

    _blob_unknown(_chat(cache_client, _reference_body(), token=RUN_2))
    assert len(counter.calls) == 1, "nothing was sent upstream for the refused call"


def test_a_call_with_no_token_gets_blob_unknown_even_with_a_cached_answer(
    cache_client: TestClient, counter: DispatchCounter
) -> None:
    assert _chat(cache_client, _inline_body(), token=None).status_code == 200
    _upload(cache_client)

    _blob_unknown(_chat(cache_client, _reference_body(), token=None))
    assert len(counter.calls) == 1


def test_a_file_never_uploaded_gets_blob_unknown(
    ref_client: TestClient, counter: DispatchCounter
) -> None:
    _blob_unknown(_chat(ref_client, _reference_body()))
    assert counter.calls == []


# --- inside the upstream slot ------------------------------------------------------------------


def test_a_file_dropped_before_the_slot_gets_blob_unknown_with_no_upstream_call(
    ref_client: TestClient, counter: DispatchCounter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upload(ref_client)
    store: MediaStore = cast(Any, ref_client.app).state.media_store
    real_lookup: Callable[..., Awaitable[Any]] = chat_route.look_up_global_cache

    async def lookup_then_drop(*args: Any, **kwargs: Any) -> Any:
        """The cache lookup, after which the store drops every file (room, or a restart)."""
        outcome = await real_lookup(*args, **kwargs)
        monkeypatch.setattr(store, "get", _nothing_held)
        return outcome

    monkeypatch.setattr(chat_route, "look_up_global_cache", lookup_then_drop)

    _blob_unknown(_chat(ref_client, _reference_body()))
    assert counter.calls == [], "no upstream spend for a file the gateway no longer holds"


def _nothing_held(scope: BlobScope | None, digest: str) -> StoredMedia | None:
    """Stands in for `MediaStore.get` once the store holds nothing."""
    return None


def test_a_streaming_request_with_a_reference_is_refused_with_a_typed_422(
    ref_client: TestClient, counter: DispatchCounter
) -> None:
    _upload(ref_client)

    response = _chat(ref_client, _reference_body(stream=True))

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "unsupported_content_part"
    assert response.json()["detail"]["reason"] == "blob_reference_streaming"
    assert counter.calls == []


def test_a_reference_to_another_callers_upload_gets_blob_unknown(
    ref_client: TestClient, counter: DispatchCounter
) -> None:
    store: MediaStore = cast(Any, ref_client.app).state.media_store
    other = BlobScope.of("00000000-0000-0000-0000-000000000000", RUN_1)
    assert other is not None
    store.put(
        other,
        PNG_SHA,
        StoredMedia(media_type="image/png", size_bytes=len(PNG), base64_text=PNG_B64),
    )

    _blob_unknown(_chat(ref_client, _reference_body()))
    assert counter.calls == []


# --- the pinned replay of a published run ------------------------------------------------------


def _replay(client: TestClient, copy_id: str, body: dict[str, Any], token: str | None) -> Any:
    headers: dict[str, str] = call_key(CASE_A)
    if token is not None:
        headers[RUN_TOKEN_HEADER] = token
    return client.post(f"/v1/frozen-copies/{copy_id}/chat/completions", json=body, headers=headers)


def test_a_reference_replay_finds_the_answer_a_published_run_pinned_inline(
    ref_client: TestClient, counter: DispatchCounter
) -> None:
    # WHY (decision 2): every copy pinned before references existed holds inline digests; a run
    # replayed by reference must still find them.
    pinned = chat_response("pinned-inline")
    copy_id = seed_keyed_copy(
        ref_client, account_id_of(ref_client), [(CASE_A, 0, _inline_body(), pinned, 200)]
    )
    _upload(ref_client)

    response = _replay(ref_client, copy_id, _reference_body(), RUN_1)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "pinned-inline"
    assert counter.calls == [], "a replay never calls a provider"


def test_a_reference_replay_without_this_runs_file_gets_blob_unknown(
    ref_client: TestClient,
) -> None:
    copy_id = seed_keyed_copy(
        ref_client,
        account_id_of(ref_client),
        [(CASE_A, 0, _inline_body(), chat_response("pinned-inline"), 200)],
    )
    _upload(ref_client, token=RUN_1)

    _blob_unknown(_replay(ref_client, copy_id, _reference_body(), RUN_2))
