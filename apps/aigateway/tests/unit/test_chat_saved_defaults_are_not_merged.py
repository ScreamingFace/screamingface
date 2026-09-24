"""OME-1323 Stage C (D2): request parameters are the caller's; a saved default never applies.

FEATURE: one globally shared exact-request cache (OME-305), keyed on the caller's hardened body.

STORY: as a caller I send every parameter I want with each request (and system instructions as
system-role messages). A historical Profile default, still stored during the compatibility
window, neither changes my request nor my cache key, and cannot refuse my request.

INVARIANT: the chat route reads no Profile before the cache and merges nothing. A request keys on
what the caller sent — so two Profiles with different historical defaults share one row for the
same bare body, and that row is the N2 bare digest (`test_chat_global_cache_key_parity.py`).

AIDEV-NOTE: the tests marked RED here failed on the pre-change code (`a1719014`) for the reason in
their docstring; N1b is a baseline that passed before and after. Never "fix" a failure here by
bumping a cache revision — stop and ask the owner.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.cache_ports import CACHE_UNAVAILABLE_REASON
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.request_cache import RequestCacheWrite
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.codex_provider.auth import (
    credential_service_for as codex_credential_service_for,
)

_CHAT_PATH = "/v1/chat/completions"
_MODEL = "anthropic/claude-haiku-4-5"
_ANTHROPIC_PLUGIN = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin"
_CODEX_PLUGIN = "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin"
# WHY a literal: the full bare digest pinned by N2. A Profile's historical defaults must not move a
# bare request off it; the response header carries the first 12 characters.
_BARE_DIGEST = "e8a63c0715d7a9ff8a8f202bc3f5f37b4d135df5750d5c0dd57e3c33cc2b3ef2"
_EVERY_SAVED_FIELD = ProfileDefaults(
    system_prompt="you are a pirate",
    max_tokens=64,
    temperature=0.2,
    timeout_seconds=9.0,
    reasoning_effort="high",
)
_SAVED_PATHS = ("temperature", "max_tokens", "timeout", "reasoning_effort", "thinking", "system")


# --- arrangement --------------------------------------------------------------


def _token_blob() -> str:
    return json.dumps(
        {
            "access_token": "sk-ant-oat01-subscription-token",
            "refresh_token": "rt",
            "id_token": "id",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
            "token_type": "Bearer",
        }
    )


def _seed(
    credential_blobs,
    account_id: str,
    *,
    name: str,
    defaults: ProfileDefaults,
    provider: str = "anthropic",
) -> None:
    """A dispatchable Profile holding HISTORICAL defaults, written straight into the index.

    WHY directly: after Stage C no writer accepts `defaults`, but documents written before it
    still carry them for the compatibility window.
    """
    service_for = (
        credential_service_for if provider == "anthropic" else codex_credential_service_for
    )
    credential_blobs.write(
        service_for(credential_name_for(account_id, name)), "default", _token_blob()
    )

    async def _upsert() -> None:
        await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
            Profile(
                id=profile_id_for(account_id, provider, name),
                account_id=account_id,
                provider=provider,
                name=name,
                state=ProfileState.AUTHENTICATED,
                defaults=defaults,
            )
        )

    asyncio.run(_upsert())


def _body(*, system: str | None = None, **extra: Any) -> dict[str, Any]:
    messages: list[dict[str, str]] = [
        {"role": "user", "content": "how many primes below one hundred?"}
    ]
    if system is not None:
        messages.insert(0, {"role": "system", "content": system})
    return {"model": _MODEL, "messages": messages, **extra}


def _system_contents(body: dict[str, Any]) -> list[str]:
    return [m["content"] for m in body.get("messages", []) if m.get("role") == "system"]


def _carries_nothing_saved(body: dict[str, Any]) -> bool:
    return not set(_SAVED_PATHS) & set(body) and _system_contents(body) == []


class _Dispatch:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> Any:
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        n = len(self.bodies)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{n}",
                "choices": [{"message": {"content": f"ANSWER-{n}"}, "finish_reason": "stop"}],
            }
        )


class _Store:
    """The frozen store contract, in memory; every lookup is logged into ``events``."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.events = events if events is not None else []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        self.events.append("cache.get")
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> str:
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


@pytest.fixture
def cache_client(monkeypatch, client: TestClient) -> TestClient:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def _install(client: TestClient, store: _Store) -> _Store:
    cast(Any, client.app).state.request_cache_store = store
    return store


def _post(client: TestClient, body: dict[str, Any], *, profile: str):
    return client.post(_CHAT_PATH, json=body, headers={"X-Profile": profile})


# --- N1a (RED): historical defaults neither key nor dispatch -----------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("pirate", _EVERY_SAVED_FIELD), ("legal", ProfileDefaults(system_prompt="be formal"))),
        (("plain", ProfileDefaults()), ("pirate", _EVERY_SAVED_FIELD)),
    ],
    ids=["two-different-saved-sets", "empty-then-saved"],
)
def test_two_profiles_with_different_historical_defaults_share_one_bare_key(
    credential_blobs,
    cache_client,
    first: tuple[str, ProfileDefaults],
    second: tuple[str, ProfileDefaults],
) -> None:
    """RED before Stage C: the merge ran before the key, so the second request MISSED."""
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    for name, defaults in (first, second):
        _seed(credential_blobs, account_id, name=name, defaults=defaults)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(f"{_ANTHROPIC_PLUGIN}.chat_completion", new=dispatch):
        filled = _post(cache_client, _body(), profile=first[0])
        served = _post(cache_client, _body(), profile=second[0])

    assert (filled.status_code, served.status_code) == (200, 200), (filled.text, served.text)
    assert (filled.headers["X-AIGW-Cache"], served.headers["X-AIGW-Cache"]) == ("miss", "hit")
    assert filled.headers["X-AIGW-Cache-Key"] == served.headers["X-AIGW-Cache-Key"]
    assert served.headers["X-AIGW-Cache-Key"] == _BARE_DIGEST[:12]
    assert list(store.rows) == [_BARE_DIGEST]
    assert len(dispatch.bodies) == 1
    assert _carries_nothing_saved(dispatch.bodies[0]), dispatch.bodies[0]
    assert served.json()["choices"][0]["message"]["content"] == "ANSWER-1"


# --- N1b (baseline): the caller's own system messages key and dispatch -------


def test_explicit_system_messages_key_distinctly_and_dispatch_only_the_callers_own(
    credential_blobs, cache_client
) -> None:
    """GREEN before and after: a caller's system message always won over a stored prompt."""
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed(
        credential_blobs, account_id, name="pirate", defaults=ProfileDefaults(system_prompt="arr")
    )
    _seed(credential_blobs, account_id, name="plain", defaults=ProfileDefaults())
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(f"{_ANTHROPIC_PLUGIN}.chat_completion", new=dispatch):
        terse = _post(cache_client, _body(system="be terse"), profile="pirate")
        verbose = _post(cache_client, _body(system="be verbose"), profile="pirate")
        shared = _post(cache_client, _body(system="be terse"), profile="plain")

    assert [r.headers["X-AIGW-Cache"] for r in (terse, verbose, shared)] == ["miss", "miss", "hit"]
    assert terse.headers["X-AIGW-Cache-Key"] != verbose.headers["X-AIGW-Cache-Key"]
    assert terse.headers["X-AIGW-Cache-Key"] == shared.headers["X-AIGW-Cache-Key"]
    assert len(store.rows) == 2
    assert [_system_contents(b) for b in dispatch.bodies] == [["be terse"], ["be verbose"]]


# --- N1c (RED): the streaming path merges nothing either ---------------------


def test_a_stream_on_a_profile_with_historical_defaults_carries_none_of_them(
    credential_blobs, cache_client
) -> None:
    """RED before Stage C: the merge ran before the stream/cache split, so it reached the stream."""
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed(credential_blobs, account_id, name="pirate", defaults=_EVERY_SAVED_FIELD)
    store = _install(cache_client, _Store())
    streamed: list[dict[str, Any]] = []

    async def _fake_stream(_self, body):
        streamed.append(json.loads(json.dumps(body, default=str)))
        yield SimpleNamespace(model_dump=lambda: {"choices": [{"delta": {"content": "hi"}}]})

    with patch(f"{_ANTHROPIC_PLUGIN}.chat_completion_stream", _fake_stream):
        responses = [_post(cache_client, _body(stream=True), profile="pirate") for _ in range(2)]

    for response in responses:
        assert response.status_code == 200, response.text
        assert response.headers["X-AIGW-Cache"] == "bypass"
        assert response.headers["X-AIGW-Cache-Reason"] == "stream"
        assert "data: [DONE]" in response.text
    assert store.rows == {}
    assert len(streamed) == 2
    for body in streamed:
        assert _carries_nothing_saved(body), body


# --- N3 (RED): an index that cannot be read before planning costs nothing -----


def test_an_index_unreadable_before_planning_causes_no_bypass_and_no_wrong_hit(
    credential_blobs, cache_client
) -> None:
    """RED before Stage C: the pre-cache defaults read failed, so the request BYPASSED.

    The fault model: in each request, the first profile-index read that happens before the
    request's cache lookup fails (a transient decode fault at planning time); later reads work.
    Stage C performs no such read, so the documented availability change is that an index fault
    no longer costs a cache hit. The index is still read AFTER the lookup, by credential
    resolution on a miss, and never on a hit.
    """
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed(credential_blobs, account_id, name="plain", defaults=ProfileDefaults())
    _seed(credential_blobs, account_id, name="pirate", defaults=_EVERY_SAVED_FIELD)
    events: list[str] = []
    store = _install(cache_client, _Store(events))
    dispatch = _Dispatch()
    real_get = ProfileIndexStore.get

    async def _unreadable_before_planning(self, *args: Any, **kwargs: Any):
        if "cache.get" not in events and "index.fault" not in events:
            events.append("index.fault")
            raise RuntimeError("the profile index could not be decoded")
        events.append("index.get")
        return await real_get(self, *args, **kwargs)

    def _send(body: dict[str, Any], profile: str) -> tuple[Any, list[str]]:
        events.clear()
        return _post(cache_client, body, profile=profile), list(events)

    with (
        patch(f"{_ANTHROPIC_PLUGIN}.chat_completion", new=dispatch),
        patch.object(ProfileIndexStore, "get", _unreadable_before_planning),
    ):
        filled, _ = _send(_body(), "plain")
        served, served_events = _send(_body(), "pirate")
        other, _ = _send(_body(system="you are a pirate"), "pirate")

    for response in (filled, served, other):
        assert response.status_code == 200, response.text
        assert response.headers.get("X-AIGW-Cache-Reason") != CACHE_UNAVAILABLE_REASON
    assert [r.headers["X-AIGW-Cache"] for r in (filled, served, other)] == ["miss", "hit", "miss"]
    # INVARIANT: a hit reads no profile index at all — not even the one decryption §57 cost.
    assert not {"index.get", "index.fault"} & set(served_events), served_events
    # INVARIANT (no wrong hit): a different request from the Profile keys apart and dispatches
    # exactly what the caller sent.
    assert other.headers["X-AIGW-Cache-Key"] != filled.headers["X-AIGW-Cache-Key"]
    assert len(store.rows) == 2
    assert [_system_contents(b) for b in dispatch.bodies] == [[], ["you are a pirate"]]


# --- N4 (RED): an invalid historical default no longer refuses ---------------


@pytest.mark.parametrize(
    ("provider", "model", "defaults", "never_dispatched"),
    [
        ("codex", "codex/gpt-5.4-mini", ProfileDefaults(temperature=0.5), ("temperature",)),
        ("anthropic", _MODEL, ProfileDefaults(temperature=1.5), ("temperature",)),
        (
            "codex",
            "codex/gpt-5.4-mini",
            ProfileDefaults(reasoning_effort="extreme"),
            ("reasoning_effort", "reasoning"),
        ),
    ],
    ids=["codex-temperature-not-enabled", "anthropic-temperature-out-of-range", "effort-enum"],
)
def test_an_invalid_historical_default_neither_refuses_nor_reaches_the_provider(
    credential_blobs,
    authenticated_client,
    provider: str,
    model: str,
    defaults: ProfileDefaults,
    never_dispatched: tuple[str, ...],
) -> None:
    """RED before Stage C: 400 `invalid_profile_defaults` for a value the caller never sent."""
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    _seed(credential_blobs, account_id, name="default", defaults=defaults, provider=provider)
    captured: list[dict[str, Any]] = []

    async def _capture(_self, body):
        captured.append(dict(body))
        return SimpleNamespace(model_dump=lambda: {"id": "x", "choices": [{"message": {}}]})

    plugin = _ANTHROPIC_PLUGIN if provider == "anthropic" else _CODEX_PLUGIN
    with patch(f"{plugin}.chat_completion", _capture):
        response = authenticated_client.post(
            _CHAT_PATH, json={"model": model, "messages": [{"role": "user", "content": "hi"}]}
        )

    assert response.status_code == 200, response.text
    assert len(captured) == 1
    assert not set(never_dispatched) & set(captured[0]), captured[0]
