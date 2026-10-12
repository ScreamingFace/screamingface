"""OME-1458 — each Attempt of a Case gets its own global cache entry.

FEATURE: a Benchmark may ask each Case N times and mark a Check met if any Attempt met it
(ARC-AGI-2 gives two Attempts per test grid). The global cache keys on the exact request, so
Attempt 2 — the identical request — would be served Attempt 1's stored reply and the score
would silently be first-Attempt only. The Engine sends Attempt 2..N with
``cache: {"attempt": i}``; the gateway keys the reply on the request plus that number and
strips the control before the provider.

STORY: as a researcher I run a two-Attempt Benchmark. Attempt 1 answers 41 and is stored;
Attempt 2 is asked afresh and answers 42. When I rerun the Benchmark, both Attempts are
served from the cache: the rerun is free and returns the same answers.

INVARIANT under test: a request without an Attempt number keys byte-identically to before
(the pinned digests in ``test_chat_global_cache_key_parity.py`` stay green, unmodified).
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.request_cache import global_keys
from aigateway.core.request_cache.canonical import canonical_digest
from aigateway.core.request_cache.global_controls import (
    BYPASS_MALFORMED_CONTROLS,
    BYPASS_OPTED_OUT,
    CONTROL_FIELD,
    parse_global_cache_controls,
)
from tests.unit.test_chat_global_cache_key_parity import (
    _BASE_MATERIAL,
    _CHAT_PATH,
    _DISPATCH_TARGET,
    _body,
    _Dispatch,
    _seed_empty_default_profile,
    _Store,
)

# The bare request's pinned digest (the parity test's "bare" case) and Attempt 2's, both
# recomputable with nothing but hashlib and json from the literal material.
_BARE_DIGEST = "e8a63c0715d7a9ff8a8f202bc3f5f37b4d135df5750d5c0dd57e3c33cc2b3ef2"
_ATTEMPT_TWO_DIGEST = "7c2a8952f7364f92ecc13bb45126d5eeef11a42d9ac86a47509857cb9a01bbf8"


@pytest.fixture
def cache_client(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> TestClient:
    """A logged-in client with the global cache switched on (the parity test's arrangement)."""

    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def _controls_body(cache: object) -> dict[str, Any]:
    """A chat body carrying the given ``cache`` control object."""

    return {"model": "fake/m", "messages": [{"role": "user", "content": "hi"}], "cache": cache}


# --- the control grammar --------------------------------------------------------------


def test_an_attempt_number_participates_and_is_carried() -> None:
    controls = parse_global_cache_controls(_controls_body({"attempt": 2}))

    assert controls.participate is True
    assert controls.attempt == 2


def test_a_request_without_an_attempt_carries_none() -> None:
    assert parse_global_cache_controls(_controls_body({"use-cache": True})).attempt is None
    assert parse_global_cache_controls(_controls_body(None)).attempt is None


@pytest.mark.parametrize("value", [1, 0, -2, "2", 2.0, True, None])
def test_a_malformed_attempt_bypasses(value: object) -> None:
    # WHY Attempt 1 is malformed: it is spelled by absence, so one request can never key two
    # entries. A bool or a float would let two spellings share or split one entry.
    controls = parse_global_cache_controls(_controls_body({"attempt": value}))

    assert controls.participate is False
    assert controls.bypass_reason == BYPASS_MALFORMED_CONTROLS


def test_attempt_combines_with_an_opt_out() -> None:
    # WHY: an operator measuring cold latency opts out of every Attempt alike.
    controls = parse_global_cache_controls(_controls_body({"use-cache": False, "attempt": 2}))

    assert controls.participate is False
    assert controls.bypass_reason == BYPASS_OPTED_OUT


def test_the_cache_object_is_still_stripped_with_an_attempt() -> None:
    body = _controls_body({"attempt": 2})
    parse_global_cache_controls(body)

    assert CONTROL_FIELD not in body


# --- the key ----------------------------------------------------------------------------


def test_attempt_two_keys_a_different_entry_than_the_bare_request() -> None:
    assert canonical_digest(_BASE_MATERIAL) == _BARE_DIGEST
    assert canonical_digest({**_BASE_MATERIAL, "attempt": 2}) == _ATTEMPT_TWO_DIGEST
    assert _ATTEMPT_TWO_DIGEST != _BARE_DIGEST


def test_the_attempt_member_is_absent_from_the_material_when_unset() -> None:
    # INVARIANT: no member at all, not a null one, so every ordinary key is unchanged.
    base: dict[str, Any] = _BASE_MATERIAL
    dto = global_keys.GlobalChatCacheKey(
        provider=base["provider"],
        requested_model=base["requested_model"],
        resolved_model=base["resolved_model"],
        messages=base["messages"],
        system=global_keys.ABSENT,
        keyed_parameters=base["keyed_parameters"],
        prepared_request=base["prepared_request"],
        parameter_contract_revision=base["parameter_contract_revision"],
        provider_adapter_revision=base["provider_adapter_revision"],
    )

    assert "attempt" not in global_keys._canonical_mapping(dto)
    assert global_keys._canonical_mapping(dto) == _BASE_MATERIAL


# --- through the route ------------------------------------------------------------------


def _post(client: TestClient, attempt: int | None) -> Any:
    """Ask the bare question once, as Attempt ``attempt`` (None = Attempt 1)."""

    extra: dict[str, Any] = {} if attempt is None else {"cache": {"attempt": attempt}}
    return client.post(_CHAT_PATH, json=_body(extra))


def test_attempt_two_is_not_served_attempt_ones_stored_reply(
    credential_blobs: Any, cache_client: TestClient
) -> None:
    # Spec acceptance 4: Attempt 1 is answered and stored; Attempt 2 goes to the model.
    _seed_empty_default_profile(credential_blobs, cache_client)
    store = _Store()
    cast(Any, cache_client.app).state.request_cache_store = store
    dispatch = _Dispatch()

    with patch(_DISPATCH_TARGET, new=dispatch):
        first = _post(cache_client, None)
        second = _post(cache_client, 2)

    assert (first.headers["X-AIGW-Cache"], second.headers["X-AIGW-Cache"]) == ("miss", "miss")
    assert len(dispatch.bodies) == 2
    assert second.json()["choices"][0]["message"]["content"] == "ANSWER-2"
    assert list(store.rows) == [_BARE_DIGEST, _ATTEMPT_TWO_DIGEST]


def test_a_rerun_serves_every_attempt_its_own_stored_reply(
    credential_blobs: Any, cache_client: TestClient
) -> None:
    # Spec acceptance 5: the second run of a two-Attempt Benchmark makes zero model calls and
    # each Attempt gets back exactly the answer it gave the first time.
    _seed_empty_default_profile(credential_blobs, cache_client)
    cast(Any, cache_client.app).state.request_cache_store = _Store()
    dispatch = _Dispatch()

    with patch(_DISPATCH_TARGET, new=dispatch):
        first_run = [_post(cache_client, None), _post(cache_client, 2)]
        rerun = [_post(cache_client, None), _post(cache_client, 2)]

    assert len(dispatch.bodies) == 2
    assert [reply.headers["X-AIGW-Cache"] for reply in rerun] == ["hit", "hit"]
    answers = [
        [reply.json()["choices"][0]["message"]["content"] for reply in run]
        for run in (first_run, rerun)
    ]
    assert answers == [["ANSWER-1", "ANSWER-2"], ["ANSWER-1", "ANSWER-2"]]


def test_the_provider_never_sees_the_cache_object(
    credential_blobs: Any, cache_client: TestClient
) -> None:
    _seed_empty_default_profile(credential_blobs, cache_client)
    cast(Any, cache_client.app).state.request_cache_store = _Store()
    dispatch = _Dispatch()

    with patch(_DISPATCH_TARGET, new=dispatch):
        _post(cache_client, 2)

    assert CONTROL_FIELD not in dispatch.bodies[0]
    assert "attempt" not in dispatch.bodies[0]
