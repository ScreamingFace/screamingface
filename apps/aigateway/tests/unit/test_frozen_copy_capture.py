"""Capture on POST /v1/chat/completions (OME-1307, design §4.2 and §9)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from litellm.exceptions import BadRequestError

from aigateway.core.frozen_copy.models import FrozenCopyEntry
from aigateway.core.frozen_copy.store import (
    FrozenCopyEntryTooLarge,
    FrozenCopyStore,
    request_digest,
)
from tests.unit.test_frozen_copy_support import (
    CAPTURE_HEADER,
    CHAT_PATH,
    COPY_HEADER,
    PATCH_TARGET,
    DispatchCounter,
    ScriptedDispatch,
    account_id_of,
    arrange_provider,
    chat_body,
    run_async,
    seal_copy,
    seed_copy,
    stored_entries,
)


def _replay_path(copy_id: str) -> str:
    return f"/v1/frozen-copies/{copy_id}/chat/completions"


@pytest.fixture
def capture_client(authenticated_client: TestClient, credential_blobs, monkeypatch):
    """A signed-in client whose account has a provider; the provider call is counted."""
    arrange_provider(authenticated_client, credential_blobs)
    monkeypatch.setattr(PATCH_TARGET, DispatchCounter())
    return authenticated_client


@pytest.fixture
def _cache_env(monkeypatch):
    # Read at app creation, so a test using it must list it BEFORE the client fixture.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_capture_client(_cache_env, capture_client: TestClient) -> TestClient:
    return capture_client


@pytest.fixture
def _small_cap_env(monkeypatch):
    monkeypatch.setenv("AIGW_FROZEN_COPY_MAX_ENTRY_BYTES", "300")


@pytest.fixture
def small_cap_client(_small_cap_env, capture_client: TestClient) -> TestClient:
    return capture_client


@pytest.fixture
def open_copy(capture_client: TestClient) -> str:
    return seed_copy(capture_client, account_id_of(capture_client), [], seal=False)


def _chat(client: TestClient, copy_id: str | None, body: dict[str, Any] | None = None):
    headers = {} if copy_id is None else {COPY_HEADER: copy_id}
    return client.post(CHAT_PATH, json=chat_body() if body is None else body, headers=headers)


# --- 2. the digest is the same on both routes ----------------------------------------------

_CACHE_OFF = {"cache": {"use-cache": False}}
_CONTROLS = {"api_base": "http://example.invalid", "fallbacks": ["other/model"]}


@pytest.mark.parametrize(
    ("captured", "replayed"),
    [
        pytest.param(chat_body(), chat_body(), id="plain"),
        pytest.param(chat_body(**_CACHE_OFF), chat_body(), id="cache-control-on-capture-only"),
        pytest.param(chat_body(), chat_body(**_CACHE_OFF), id="cache-control-on-replay-only"),
        pytest.param(chat_body(**_CONTROLS), chat_body(), id="dispatch-controls-on-capture-only"),
        pytest.param(chat_body(), chat_body(**_CONTROLS), id="dispatch-controls-on-replay-only"),
        pytest.param(
            chat_body(temperature=0.2, **_CACHE_OFF, **_CONTROLS),
            chat_body(**_CONTROLS, temperature=0.2, **_CACHE_OFF),
            id="both-controls-reordered-keys",
        ),
    ],
)
def test_capture_and_replay_digest_match_for_the_same_body(
    capture_client: TestClient, open_copy: str, captured: dict, replayed: dict
) -> None:
    """Cache and dispatch controls are not part of the request: both routes drop them first."""
    live = _chat(capture_client, open_copy, captured)
    assert live.status_code == 200, live.text
    assert live.headers[CAPTURE_HEADER] == "stored"
    seal_copy(capture_client, open_copy)

    replay = capture_client.post(_replay_path(open_copy), json=replayed)

    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == live.json()["id"]
    (entry,) = stored_entries(capture_client, open_copy)
    assert entry["digest"] == request_digest("chat", entry["request"])
    assert "cache" not in entry["request"]
    assert not set(entry["request"]) & set(_CONTROLS)


# --- 3. a cache hit and a live success are stored alike ----------------------------------


def test_capture_stores_a_cache_hit_and_a_live_success_identically_shaped(
    cache_capture_client: TestClient,
) -> None:
    client = cache_capture_client
    copy_id = seed_copy(client, account_id_of(client), [], seal=False)

    live = _chat(client, copy_id)
    hit = _chat(client, copy_id)

    assert live.headers["X-AIGW-Cache"] == "miss"
    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert [live.headers[CAPTURE_HEADER], hit.headers[CAPTURE_HEADER]] == ["stored", "stored"]
    first, second = stored_entries(client, copy_id)
    assert first["digest"] == second["digest"]
    assert first["request"] == second["request"]
    assert (first["status_code"], second["status_code"]) == (200, 200)
    # The body is stored exactly as the caller received it, on both paths.
    assert first["response"] == live.json()
    assert second["response"] == hit.json()
    assert set(first["response"]) == set(second["response"])
    assert set(first["response"]["_aigw"]) == set(second["response"]["_aigw"])
    assert first["response"]["choices"] == second["response"]["choices"]


# --- 4. a capture failure never fails the call ---------------------------------------------


def test_capture_failure_never_fails_the_call(
    capture_client: TestClient, open_copy: str, monkeypatch, caplog
) -> None:
    async def _boom(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("PROMPT-LEAK-MARKER")

    monkeypatch.setattr(FrozenCopyStore, "capture", _boom)

    with caplog.at_level(logging.WARNING, logger="aigateway.core.frozen_copy.store"):
        response = _chat(capture_client, open_copy, chat_body())

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "failed"
    assert response.json()["choices"][0]["finish_reason"] == "stop"
    lines = [r.getMessage() for r in caplog.records if "frozen copy capture" in r.getMessage()]
    assert len(lines) == 1
    digest = request_digest("chat", chat_body())
    assert open_copy in lines[0]
    assert digest[:12] in lines[0]
    assert digest[:13] not in lines[0]
    assert "chat" in lines[0]
    # Never the prompt, and never the exception message (which may carry it).
    assert "PROMPT-LEAK-MARKER" not in caplog.text
    assert chat_body()["messages"][0]["content"] not in caplog.text


def test_a_copy_lookup_failure_is_a_failed_capture_not_a_failed_call(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    async def _boom(self, copy_id: Any) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(FrozenCopyStore, "get", _boom)

    response = _chat(capture_client, open_copy)

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "failed"


def test_a_failing_store_does_not_change_a_provider_error(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    async def _boom(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(FrozenCopyStore, "capture", _boom)
    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request()))

    response = _chat(capture_client, open_copy)

    assert response.status_code == 400
    assert response.headers[CAPTURE_HEADER] == "failed"


# --- 5. refused: unknown, malformed, foreign or sealed copy, and a stream ------------------


async def _fake_stream(plugin: Any, body: dict[str, Any], *, provider: str | None = None):
    yield b"data: [DONE]\n\n"


def _entry_count(client: TestClient) -> int:
    async def _count() -> int:
        return await FrozenCopyEntry.all().count()

    return run_async(client, _count)


def test_capture_refused_for_an_unknown_copy(capture_client: TestClient) -> None:
    response = _chat(capture_client, str(uuid4()))

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "refused"
    assert _entry_count(capture_client) == 0


def test_capture_refused_for_a_malformed_copy_id(capture_client: TestClient) -> None:
    response = _chat(capture_client, "not-a-uuid")

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "refused"


def test_capture_refused_for_another_accounts_copy(
    capture_client: TestClient, provisioned_user_factory
) -> None:
    other = provisioned_user_factory("someone-else")
    foreign = seed_copy(capture_client, UUID(other["id"]), [], seal=False)

    response = _chat(capture_client, foreign)

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "refused"
    assert stored_entries(capture_client, foreign) == []


def test_capture_refused_for_a_sealed_copy(capture_client: TestClient) -> None:
    sealed = seed_copy(capture_client, account_id_of(capture_client), [], seal=True)

    response = _chat(capture_client, sealed)

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "refused"
    assert stored_entries(capture_client, sealed) == []


def test_capture_refused_for_a_stream(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    monkeypatch.setattr("aigateway.routes.chat._stream", _fake_stream)

    response = _chat(capture_client, open_copy, chat_body(stream=True))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers[CAPTURE_HEADER] == "refused"
    assert stored_entries(capture_client, open_copy) == []


def test_a_refused_copy_still_gets_the_header_on_an_error_response(
    capture_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request()))

    response = _chat(capture_client, str(uuid4()))

    assert response.status_code == 400
    assert response.headers[CAPTURE_HEADER] == "refused"


# --- 6. a provider error is captured and replayed the same way -----------------------------


def _bad_request() -> BadRequestError:
    return BadRequestError(
        message="provider says no",
        model="claude-haiku-4-5",
        llm_provider="anthropic",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.invalid")),
    )


def test_provider_error_is_captured_and_replayed_with_the_same_status_and_detail(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request()))

    failed = _chat(capture_client, open_copy)

    assert failed.status_code == 400
    assert failed.headers[CAPTURE_HEADER] == "stored"
    (entry,) = stored_entries(capture_client, open_copy)
    assert entry["status_code"] == 400
    assert entry["response"] == {"detail": failed.json()["detail"]}
    seal_copy(capture_client, open_copy)

    replay = capture_client.post(_replay_path(open_copy), json=chat_body())

    assert replay.status_code == 400
    assert replay.json()["detail"] == failed.json()["detail"]
    assert replay.headers["X-AIGW-Replay"] == "error"


def test_every_attempt_is_captured_and_replay_returns_the_success(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    from tests.unit.test_frozen_copy_support import chat_response

    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request(), chat_response("second-try")))

    first = _chat(capture_client, open_copy)
    second = _chat(capture_client, open_copy)

    assert (first.status_code, second.status_code) == (400, 200)
    assert [e["status_code"] for e in stored_entries(capture_client, open_copy)] == [400, 200]
    seal_copy(capture_client, open_copy)
    replay = capture_client.post(_replay_path(open_copy), json=chat_body())
    assert replay.status_code == 200
    assert replay.json()["id"] == "second-try"


def test_a_refusal_after_the_copy_check_is_captured_too(
    authenticated_client: TestClient,
) -> None:
    """No provider connection: credential resolution refuses AFTER the copy check."""
    copy_id = seed_copy(authenticated_client, account_id_of(authenticated_client), [], seal=False)

    failed = _chat(authenticated_client, copy_id)

    assert failed.status_code >= 400
    assert failed.headers[CAPTURE_HEADER] == "stored"
    seal_copy(authenticated_client, copy_id)
    replay = authenticated_client.post(_replay_path(copy_id), json=chat_body())
    assert replay.status_code == failed.status_code
    assert replay.json()["detail"] == failed.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"model": "anthropic/claude-haiku-4-5"}, id="bad-shape"),
        pytest.param(chat_body(model="ghost/model"), id="unknown-provider"),
        pytest.param(chat_body(model="no-provider-prefix"), id="no-provider-prefix"),
    ],
)
def test_refusals_before_the_copy_check_are_not_captured(
    capture_client: TestClient, open_copy: str, body: dict[str, Any]
) -> None:
    response = _chat(capture_client, open_copy, body)

    assert response.status_code == 400
    assert stored_entries(capture_client, open_copy) == []


# --- 12. the size cap -----------------------------------------------------------------------


def test_entry_over_the_size_cap_is_failed_not_stored(small_cap_client: TestClient) -> None:
    client = small_cap_client
    copy_id = seed_copy(client, account_id_of(client), [], seal=False)

    response = _chat(client, copy_id, chat_body(messages=[{"role": "user", "content": "x" * 400}]))

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "failed"
    assert stored_entries(client, copy_id) == []


def test_the_size_cap_counts_request_plus_response_and_includes_the_boundary(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    request, response = {"q": "a" * 10}, {"a": "b" * 10}
    size = len('{"q":"aaaaaaaaaa"}') + len('{"a":"bbbbbbbbbb"}')

    async def _run() -> None:
        store = FrozenCopyStore(max_entry_bytes=size)
        copy = await store.open(account_id_of_sync)
        await store.capture(copy, "tool", request, response, 200)
        with pytest.raises(FrozenCopyEntryTooLarge):
            await FrozenCopyStore(max_entry_bytes=size - 1).capture(
                copy, "tool", request, response, 200
            )

    account_id_of_sync = account_id_of(client)
    run_async(client, _run)


# --- 13. without the header nothing changes -------------------------------------------------


def test_no_capture_without_the_header(cache_capture_client: TestClient, monkeypatch) -> None:
    client = cache_capture_client
    live = _chat(client, None)
    hit = _chat(client, None)
    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request()))
    failed = _chat(client, None, chat_body(messages=[{"role": "user", "content": "other"}]))
    monkeypatch.setattr("aigateway.routes.chat._stream", _fake_stream)
    streamed = _chat(client, None, chat_body(stream=True))

    assert [live.status_code, hit.status_code, failed.status_code] == [200, 200, 400]
    assert streamed.status_code == 200
    for response in (live, hit, failed, streamed):
        assert CAPTURE_HEADER not in response.headers
    assert _entry_count(client) == 0


# --- review round: every ending of a captured call is captured -----------------------------


def test_a_non_dict_success_is_failed_and_still_stamped(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    async def _not_a_dict(*_args: Any, **_kwargs: Any) -> str:
        return "plain text"

    monkeypatch.setattr("aigateway.routes.chat._dispatch_and_finalize_accounting", _not_a_dict)

    response = _chat(capture_client, open_copy)

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "failed"
    assert stored_entries(capture_client, open_copy) == []


def test_a_mutation_conflict_is_captured_as_the_503_the_app_renders(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    from aigateway.core.credential_blob.store import CredentialBlobMutationConflict

    async def _conflict(*_args: Any, **_kwargs: Any) -> None:
        raise CredentialBlobMutationConflict

    monkeypatch.setattr("aigateway.routes.chat._resolve_credential_target", _conflict)

    live = _chat(capture_client, open_copy)

    assert live.status_code == 503
    assert live.json()["detail"]["code"] == "profile_index_conflict"
    assert live.headers[CAPTURE_HEADER] == "stored"
    (entry,) = stored_entries(capture_client, open_copy)
    assert entry["status_code"] == 503
    # INVARIANT: the stored detail IS the body the app handler renders (drift guard).
    assert entry["response"] == {"detail": live.json()["detail"]}
    seal_copy(capture_client, open_copy)
    replay = capture_client.post(_replay_path(open_copy), json=chat_body())
    assert replay.status_code == 503
    assert replay.json()["detail"] == live.json()["detail"]


def test_an_unexpected_exception_is_captured_as_a_generic_500_and_not_swallowed(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    from tests.unit.test_frozen_copy_support import server_errors_as_responses

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("PROMPT-LEAK-MARKER")

    monkeypatch.setattr("aigateway.routes.chat._resolve_credential_target", _boom)

    with server_errors_as_responses(capture_client):
        live = _chat(capture_client, open_copy)

    assert live.status_code == 500
    assert live.headers[CAPTURE_HEADER] == "stored"
    (entry,) = stored_entries(capture_client, open_copy)
    assert entry["status_code"] == 500
    assert entry["response"]["detail"]["code"] == "gateway_internal_error"
    assert "PROMPT-LEAK-MARKER" not in str(entry["response"])
    seal_copy(capture_client, open_copy)
    replay = capture_client.post(_replay_path(open_copy), json=chat_body())
    assert replay.status_code == 500
    assert replay.json()["detail"]["code"] == "gateway_internal_error"


def test_an_unexpected_exception_without_the_header_has_no_capture_header(
    capture_client: TestClient, monkeypatch
) -> None:
    from tests.unit.test_frozen_copy_support import server_errors_as_responses

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("aigateway.routes.chat._resolve_credential_target", _boom)

    with server_errors_as_responses(capture_client):
        response = _chat(capture_client, None)

    assert response.status_code == 500
    assert CAPTURE_HEADER not in response.headers


def test_an_empty_copy_header_is_refused(capture_client: TestClient) -> None:
    response = capture_client.post(CHAT_PATH, json=chat_body(), headers={COPY_HEADER: ""})

    assert response.status_code == 200, response.text
    assert response.headers[CAPTURE_HEADER] == "refused"


def test_a_replayed_error_has_the_body_shape_of_a_live_error(
    capture_client: TestClient, open_copy: str, monkeypatch
) -> None:
    monkeypatch.setattr(PATCH_TARGET, ScriptedDispatch(_bad_request()))
    live = _chat(capture_client, open_copy)
    seal_copy(capture_client, open_copy)

    replay = capture_client.post(_replay_path(open_copy), json=chat_body())

    assert live.status_code == replay.status_code == 400
    assert set(live.json()) == set(replay.json()) == {"detail", "_aigw"}
    assert replay.json()["detail"] == live.json()["detail"]
    aigw = replay.json()["_aigw"]
    assert aigw["frozen_copy_replay"] is True
    assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"
    assert aigw["request_economics"]["known_direct_cost_subtotals"] == []
    assert aigw["usage_accounting"]["cache"]["status"] == "hit"
    assert set(aigw) == set(live.json()["_aigw"]) | {"frozen_copy_replay"}
