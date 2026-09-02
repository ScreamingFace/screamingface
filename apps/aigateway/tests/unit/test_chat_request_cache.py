"""Route-level tests for the GLOBAL request cache on /v1/chat/completions (OME-305).

FEATURE: one globally shared exact-request cache, consulted BEFORE any identity is
resolved. A hit needs no profile, no auth mode and no credential, so a second
account — or an account with no connection at all — is answered from the first
run's stored responses.

STORY: as a benchmark operator I re-run a suite from a second account and the
identical calls come back without a provider dispatch, and without the second
account's key being read.

AIDEV-NOTE — SUPERSESSION (OME-305 replaces the OME-479 v1 cache). This file was a
per-ACCOUNT, opt-IN, TTL-bearing cache's test suite, and several of its assertions
stated the exact opposite of the v2 contract. Nothing was deleted: every scenario
below is the reconstruction of a v1 scenario, and the ones whose EXPECTED OUTCOME
inverted say so at the test. The three inversions are:
  * opt-in became on-by-default (``cache: {"use-cache": true}`` was required; now
    saying nothing participates, and the control object exists only to opt OUT);
  * the account and profile dimensions were partitions and are now deliberately
    NOT — that inversion is the entire deliverable;
  * ``ttl``/``s-maxage``/``no-cache``/``no-store`` were honored controls and are now
    retired: they BYPASS rather than being silently ignored, because a caller who
    asks for a per-request TTL must not receive a permanent shared entry instead.

Provider-dimension isolation is proven at the key level
(test_global_cache_key.py): a route-level "different provider" request is the same
as a "different model prefix" request, which is covered here by the different-model
test.
"""

from __future__ import annotations

import json
import time
from functools import partial
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.request_cache.global_controls import (
    BYPASS_MALFORMED_CONTROLS,
    BYPASS_OPTED_OUT,
    BYPASS_UNSUPPORTED_CONTROL,
    UNSUPPORTED_CONTROL_FIELDS,
)
from aigateway.core.request_cache.global_eligibility import (
    BYPASS_DECLARED,
    BYPASS_STREAM,
)
from aigateway.core.request_cache.global_plan import BYPASS_DISABLED
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT_PATH = "/v1/chat/completions"
_PATCH_TARGET = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


async def _create_active_connection(account_id: str, *, label: str = "default"):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id,
        provider="anthropic",
        label=label,
        connection_id=uuid4(),
    )
    return await store.complete(connection, label=label, identity=None)


def _seed_connection_credentials(
    credential_blobs, account_id: str, connection_id, *, token: str = "tok"
) -> None:
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection_id)),
        "default",
        json.dumps(
            {
                "access_token": token,
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


def _arrange_account(
    client, credential_blobs, *, label: str = "default", token: str = "tok"
) -> str:
    account_id = _account_id(client)
    connection = client.portal.call(partial(_create_active_connection, account_id, label=label))
    _seed_connection_credentials(credential_blobs, account_id, connection.id, token=token)
    return account_id


class _DispatchCounter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    # Patched over the *class* method with an instance, which bypasses
    # function-descriptor binding — so only `body` arrives.
    async def __call__(self, body):
        self.calls.append(dict(body))
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{len(self.calls)}",
                "choices": [{"message": {"content": "SECRET-ANSWER"}, "finish_reason": "stop"}],
            }
        )


def _chat_body(**overrides) -> dict:
    # SUPERSEDED: the v1 baseline carried ``"cache": {"use-cache": True}`` because
    # caching was opt-in. The v2 baseline says nothing about caching at all, which is
    # the request an ordinary client actually sends — and it participates.
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
    }
    body.update(overrides)
    return body


@pytest.fixture
def _cache_env(monkeypatch):
    # Must run before the `client` fixture builds the app so Settings sees it.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_client(_cache_env, client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


# --- the operator gate -------------------------------------------------------


def test_cache_disabled_by_default_dispatches_twice(credential_blobs, authenticated_client) -> None:
    """The operator gate still defaults to OFF, and default-on caching does not change that.

    SUPERSEDED ASSERTION: the reason string was v1's ``"disabled"``; v2 publishes
    ``"disabled"`` from one closed vocabulary shared by every layer. The
    BEHAVIOUR — two dispatches, nothing stored — is unchanged and is why this test
    keeps its name: turning the cache on must remain a deliberate operator act, even
    though a caller no longer has to ask for it.
    """
    _arrange_account(authenticated_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        first = authenticated_client.post(_CHAT_PATH, json=_chat_body())
        second = authenticated_client.post(_CHAT_PATH, json=_chat_body())
    assert first.status_code == second.status_code == 200
    assert len(counter.calls) == 2
    assert first.headers["X-AIGW-Cache"] == "bypass"
    assert first.headers["X-AIGW-Cache-Reason"] == BYPASS_DISABLED
    # A disabled cache must not advertise a key it never looked up.
    assert "X-AIGW-Cache-Key" not in first.headers


# --- default-on participation (the v1 opt-in, inverted) ----------------------


def test_a_request_that_says_nothing_about_caching_participates_by_default(
    credential_blobs, cache_client
) -> None:
    """INVERTED from ``test_enabled_but_not_requested_dispatches_twice``.

    v1 required ``cache: {"use-cache": true}`` and reported ``not_requested`` for a
    request that omitted it — so the benchmark runs that most needed caching silently
    paid full price. v2 participates by default, so the SAME request that used to
    dispatch twice now dispatches once. The v1 expectation is reconstructed as its
    opposite rather than deleted, because "what happens when the caller says nothing"
    is exactly the question whose answer the ticket changes.
    """
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    body = _chat_body()
    assert "cache" not in body
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=body)
        second = cache_client.post(_CHAT_PATH, json=body)
    assert first.status_code == second.status_code == 200
    assert len(counter.calls) == 1
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert second.headers["X-AIGW-Cache"] == "hit"


def test_an_explicit_opt_in_still_participates(credential_blobs, cache_client) -> None:
    # The v1 spelling remains VALID, not merely tolerated: a client that already sends
    # it keeps working across the upgrade instead of starting to bypass.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    body = _chat_body(cache={"use-cache": True})
    with patch(_PATCH_TARGET, counter):
        cache_client.post(_CHAT_PATH, json=body)
        second = cache_client.post(_CHAT_PATH, json=body)
    assert len(counter.calls) == 1
    assert second.headers["X-AIGW-Cache"] == "hit"


def test_an_explicit_opt_out_neither_reads_nor_writes(credential_blobs, cache_client) -> None:
    """``use-cache: false`` is the only thing the v2 control object exists to say."""
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    opted_out = _chat_body(cache={"use-cache": False})
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=opted_out)
        second = cache_client.post(_CHAT_PATH, json=opted_out)
        # A plain request afterwards proves the opt-out did not FILL the entry either
        # — v2 has no read-only or write-only lane.
        third = cache_client.post(_CHAT_PATH, json=_chat_body())
    assert len(counter.calls) == 3
    assert first.headers["X-AIGW-Cache"] == "bypass"
    assert first.headers["X-AIGW-Cache-Reason"] == BYPASS_OPTED_OUT
    assert second.headers["X-AIGW-Cache"] == "bypass"
    assert third.headers["X-AIGW-Cache"] == "miss"


def test_the_cache_control_object_never_reaches_the_provider(
    credential_blobs, cache_client
) -> None:
    # INVARIANT: ``cache`` is popped UNCONDITIONALLY, including when malformed, so a
    # gateway control object can never be forwarded as a model parameter.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        cache_client.post(_CHAT_PATH, json=_chat_body(cache={"use-cache": True}))
        cache_client.post(_CHAT_PATH, json=_chat_body(cache="nonsense"))
    assert counter.calls, "the provider must have been dispatched at least once"
    for call in counter.calls:
        assert "cache" not in call


# --- the hit path ------------------------------------------------------------


def test_an_identical_second_request_is_served_without_a_provider_dispatch(
    credential_blobs, cache_client
) -> None:
    """RENAMED from ``test_opt_in_hit_skips_provider_dispatch`` — there is no opt-in.

    SUPERSEDED ASSERTION: v1 published the write result in
    ``X-AIGW-Cache-Reason: stored``, conflating "why this was not cached" with "what
    the write did". v2 splits them — ``X-AIGW-Cache-Write`` carries the write result
    and appears on a miss only, and ``Reason`` is empty when there is nothing to
    explain. The hit-skips-dispatch property itself is unchanged.
    """
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=_chat_body())
        second = cache_client.post(_CHAT_PATH, json=_chat_body())
    assert first.status_code == second.status_code == 200
    assert len(counter.calls) == 1, "second identical request must be served from cache"
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Reason"] == ""
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    # "What did the write do" is meaningless for a hit, so the header is absent.
    assert "X-AIGW-Cache-Write" not in second.headers
    first_body = first.json()
    second_body = second.json()
    assert {key: value for key, value in second_body.items() if key != "_aigw"} == {
        key: value for key, value in first_body.items() if key != "_aigw"
    }
    assert first_body["_aigw"]["usage_accounting"]["cache"]["status"] == "miss"
    assert second_body["_aigw"]["usage_accounting"]["cache"]["status"] == "hit"
    # The cache key header is hash-derived only, and truncated: the full digest of a
    # GLOBAL entry is a cross-tenant request fingerprint.
    assert "hi" not in second.headers.get("X-AIGW-Cache-Key", "")
    assert len(second.headers["X-AIGW-Cache-Key"]) == 12
    assert second.headers["X-AIGW-Cache-Key"] == first.headers["X-AIGW-Cache-Key"]


# --- identity is NOT a partition (the deliverable) ---------------------------


def test_a_second_account_hits_the_first_accounts_stored_response(
    credential_blobs, cache_client, provisioned_user_factory
) -> None:
    """INVERTED from ``test_different_account_misses`` — this inversion IS the ticket.

    v1 asserted "another account must never hit the first account's cache", because
    the v1 key was scoped to ``(account_id, profile_name)``. The v2 key is GLOBAL and
    contains no identity at all, so the same assertion now states the exact opposite:
    the second account must be served the first account's fill. Reconstructed rather
    than deleted, because the account dimension still needs a test — what changed is
    which answer is correct.
    """
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        cache_client.post(_CHAT_PATH, json=_chat_body())

        provisioned_user_factory("second-user")
        login = cache_client.post(
            "/v1/auth/login",
            json={"username": "second-user", "password": "test-user-password"},
        )
        assert login.status_code == 200
        other_headers = {"Authorization": f"Bearer {login.json()['token']}"}
        other_account = cache_client.get("/v1/auth/me", headers=other_headers).json()["id"]
        connection = cache_client.portal.call(_create_active_connection, other_account)
        _seed_connection_credentials(credential_blobs, other_account, connection.id)

        resp = cache_client.post(_CHAT_PATH, json=_chat_body(), headers=other_headers)
    assert resp.status_code == 200
    assert len(counter.calls) == 1, "the second account must be served from the first fill"
    assert resp.headers["X-AIGW-Cache"] == "hit"


def test_an_account_with_no_provider_connection_at_all_is_still_served_from_cache(
    credential_blobs, cache_client, provisioned_user_factory
) -> None:
    """The strongest form of the inversion: no credential exists to be read.

    WHY this is a separate test from the one above: seeding the second account's
    connection proves identity does not partition the key, but it leaves open whether
    the credential was read on the way. Here there is no connection and no credential
    blob at all, so a 200 hit is only possible if the cache stage genuinely runs
    BEFORE profile resolution — and the same request without a fill would fail.
    """
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        filled = cache_client.post(_CHAT_PATH, json=_chat_body())
        assert filled.headers["X-AIGW-Cache"] == "miss"

        provisioned_user_factory("unconnected-user")
        login = cache_client.post(
            "/v1/auth/login",
            json={"username": "unconnected-user", "password": "test-user-password"},
        )
        assert login.status_code == 200
        unconnected = {"Authorization": f"Bearer {login.json()['token']}"}

        # Control: a request this account CANNOT be served from cache fails, which is
        # what proves the hit above was not simply an unprotected route.
        uncached = cache_client.post(
            _CHAT_PATH,
            json=_chat_body(messages=[{"role": "user", "content": "never stored"}]),
            headers=unconnected,
        )
        hit = cache_client.post(_CHAT_PATH, json=_chat_body(), headers=unconnected)
    assert uncached.status_code >= 400, uncached.text
    assert hit.status_code == 200, hit.text
    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert len(counter.calls) == 1


def test_a_different_profile_hits_the_same_global_entry(credential_blobs, cache_client) -> None:
    """INVERTED from ``test_different_profile_misses``.

    v1 keyed on ``profile_name``, so ``X-Profile: work`` was a different cache entry.
    A profile selects a CREDENTIAL, and the v2 key deliberately cannot see one — two
    profiles pointing at the same provider and model are the same upstream call, so
    they share the entry.
    """
    account_id = _account_id(cache_client)
    for label in ("work", "personal"):
        connection = cache_client.portal.call(
            partial(_create_active_connection, account_id, label=label)
        )
        _seed_connection_credentials(credential_blobs, account_id, connection.id)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=_chat_body(), headers={"X-Profile": "work"})
        second = cache_client.post(_CHAT_PATH, json=_chat_body(), headers={"X-Profile": "personal"})
    assert first.status_code == second.status_code == 200
    assert len(counter.calls) == 1, "a different X-Profile shares the global entry"
    assert second.headers["X-AIGW-Cache"] == "hit"


# --- what still partitions ---------------------------------------------------


def test_different_model_misses(credential_blobs, cache_client) -> None:
    # The model IS in the key — it is the one thing that changes the upstream call.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=_chat_body())
        resp = cache_client.post(_CHAT_PATH, json=_chat_body(model="anthropic/claude-sonnet-4-6"))
    assert resp.status_code == 200
    assert len(counter.calls) == 2
    assert resp.headers["X-AIGW-Cache"] == "miss"
    assert resp.headers["X-AIGW-Cache-Key"] != first.headers["X-AIGW-Cache-Key"]


def test_a_different_prompt_misses(credential_blobs, cache_client) -> None:
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        cache_client.post(_CHAT_PATH, json=_chat_body())
        resp = cache_client.post(
            _CHAT_PATH, json=_chat_body(messages=[{"role": "user", "content": "different"}])
        )
    assert len(counter.calls) == 2
    assert resp.headers["X-AIGW-Cache"] == "miss"


# --- the retired v1 controls -------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("ttl", 60), ("s-maxage", 30), ("no-cache", True), ("no-store", True)],
)
def test_a_retired_v1_control_bypasses_instead_of_being_silently_ignored(
    credential_blobs, cache_client, field: str, value: object
) -> None:
    """RECONSTRUCTS ``test_no_cache_skips_lookup_but_stores``, ``test_no_store_prevents_storage``
    and ``test_expired_entry_dispatches_again`` as one contract.

    All three v1 tests asserted that a specific control was HONORED. v2 offers none
    of them — entries never expire and are shared by every caller — so honoring them
    is impossible and IGNORING them would be dishonest: a caller who asks for a
    60-second TTL would silently receive a permanent global entry. Bypassing is the
    only truthful answer, and the v1 property that survives is preserved exactly:
    nothing is read and nothing is stored.
    """
    assert field in UNSUPPORTED_CONTROL_FIELDS
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    body = _chat_body(cache={"use-cache": True, field: value})
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=body)
        second = cache_client.post(_CHAT_PATH, json=body)
        # PRESERVED from v1's no-store test: the bypassed request stored nothing, so a
        # plain request afterwards is still a miss rather than a hit on its response.
        third = cache_client.post(_CHAT_PATH, json=_chat_body())
    assert first.status_code == 200, first.text
    assert len(counter.calls) == 3
    assert first.headers["X-AIGW-Cache"] == "bypass"
    assert first.headers["X-AIGW-Cache-Reason"] == BYPASS_UNSUPPORTED_CONTROL
    assert second.headers["X-AIGW-Cache"] == "bypass"
    assert third.headers["X-AIGW-Cache"] == "miss"


def test_every_retired_v1_control_is_covered_by_the_bypass_table(request) -> None:
    """Anti-drift: a fifth retired control cannot be added without a case here.

    AIDEV-NOTE: the parametrize table above is the only place the retired names are
    asserted at the ROUTE level. Without this, adding a name to
    ``UNSUPPORTED_CONTROL_FIELDS`` would leave it unproven end-to-end.
    """
    covered = {
        case.callspec.params["field"]
        for case in request.session.items
        if case.originalname
        == "test_a_retired_v1_control_bypasses_instead_of_being_silently_ignored"
    }
    assert covered == set(UNSUPPORTED_CONTROL_FIELDS)


def test_an_unknown_control_field_bypasses(credential_blobs, cache_client) -> None:
    # A field this cache has never heard of is the same risk as a retired one: the
    # caller asked for something that will not happen.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(_CHAT_PATH, json=_chat_body(cache={"variant": "b"}))
    assert resp.status_code == 200
    assert len(counter.calls) == 1
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert resp.headers["X-AIGW-Cache-Reason"] == BYPASS_UNSUPPORTED_CONTROL


@pytest.mark.parametrize("controls", ["yes", 7, ["use-cache"], {"use-cache": "true"}])
def test_a_malformed_control_object_bypasses_rather_than_defaulting_on(
    credential_blobs, cache_client, controls: object
) -> None:
    # WHY not "treat malformed as absent": absent means participate, so a typo in an
    # opt-out would silently opt the caller back IN.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(_CHAT_PATH, json=_chat_body(cache=controls))
    assert resp.status_code == 200
    assert len(counter.calls) == 1
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert resp.headers["X-AIGW-Cache-Reason"] == BYPASS_MALFORMED_CONTROLS


# --- structural bypasses -----------------------------------------------------


def test_stream_bypasses_cache(credential_blobs, cache_client) -> None:
    """PRESERVED from v1, strengthened with the published reason.

    INVARIANT: a streamed response is assembled from chunks the gateway never stores,
    so streaming stays structurally ineligible even if a provider rule said otherwise.
    """
    _arrange_account(cache_client, credential_blobs)

    async def fake_stream(_self, body):
        from types import SimpleNamespace

        yield SimpleNamespace(model_dump=lambda: {"choices": [{"delta": {"content": "x"}}]})

    counter = _DispatchCounter()
    with (
        patch(_PATCH_TARGET, counter),
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion_stream",
            fake_stream,
        ),
    ):
        resp = cache_client.post(_CHAT_PATH, json=_chat_body(stream=True))
        resp2 = cache_client.post(_CHAT_PATH, json=_chat_body(stream=True))
    assert resp.status_code == resp2.status_code == 200
    assert len(counter.calls) == 0, "streaming must use the streaming path, never the cache"
    # SUPERSEDED: v1 hardcoded these headers on the streaming response with an
    # ``or "stream"`` fallback, so it could not tell streaming from a disabled cache.
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert resp.headers["X-AIGW-Cache-Reason"] == BYPASS_STREAM


def test_a_stream_false_request_still_participates(credential_blobs, cache_client) -> None:
    # INVARIANT (plan §2.5): ``stream: false`` means exactly what omission means, so
    # it must not cost the caller their entry.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        cache_client.post(_CHAT_PATH, json=_chat_body(stream=False))
        second = cache_client.post(_CHAT_PATH, json=_chat_body(stream=False))
    assert len(counter.calls) == 1
    assert second.headers["X-AIGW-Cache"] == "hit"


def test_a_tool_bearing_request_bypasses_on_an_unpromoted_provider(
    credential_blobs, cache_client
) -> None:
    # OME-782/OME-787: tool-bearing requests are no longer a STRUCTURAL bypass —
    # whether they key is now an ordinary per-provider ``cache_behavior`` choice
    # (default ``"bypass"``). Anthropic has not been promoted (only OpenRouter has,
    # OME-787), so this request still bypasses — but now for the ordinary
    # declared-bypass reason any other un-promoted rule gets, not a tools-specific one.
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    tools = [
        {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
        }
    ]
    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(_CHAT_PATH, json=_chat_body(tools=tools))
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert resp.headers["X-AIGW-Cache-Reason"] == BYPASS_DECLARED


def test_a_keyed_parameter_is_cached_under_its_value_and_still_reaches_dispatch(
    credential_blobs, cache_client
) -> None:
    """SUPERSEDED (OME-305, owner decision B) — the THIRD name this case has carried.

    Was ``test_a_declared_bypass_parameter_bypasses_the_global_cache`` (itself renamed
    from ``test_unsupported_field_bypasses``), asserting verbatim:
    ``assert first.headers["X-AIGW-Cache"] == "bypass"`` and
    ``assert second.headers["X-AIGW-Cache"] == "bypass"``.

    The history is worth keeping because each step narrowed the reason rather than
    changing the outcome, and decision B is the first step that changes the OUTCOME:

    * v1 reported ``unsupported_fields`` — its key builder accepted only
      ``model``/``messages``/``system`` and refused everything else structurally.
    * v2 asked the provider's RULE and got ``unsupported_fields`` — a reviewed
      provider decision rather than the key builder's ignorance.
    * decision B keys it. ``temperature`` changes the response, Anthropic implements
      ``global_cache_projection``, so the value belongs in the fingerprint. A cache
      that bypassed on ``temperature`` served only bare ``{model, messages}`` requests,
      which is close to no real client.

    AIDEV-NOTE: ``anthropic_provider/parameters.py`` cites THIS test as the evidence
    that ``temperature`` reaches the Anthropic dispatch body. That citation survives the
    supersession — the dispatch-body assertion below is still here and still load-
    bearing. Keep them together; if this case is ever renamed again, update the citation.
    """
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    body = _chat_body(temperature=0.7)
    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=body)
        second = cache_client.post(_CHAT_PATH, json=body)
        other = cache_client.post(_CHAT_PATH, json=_chat_body(temperature=0.2))
    # One dispatch per DISTINCT temperature: the repeat was served, the new value was not.
    assert len(counter.calls) == 2
    assert counter.calls[0]["temperature"] == 0.7, "temperature must reach the dispatch body"
    assert counter.calls[1]["temperature"] == 0.2
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert other.headers["X-AIGW-Cache"] == "miss", "a different temperature must not hit"
    assert first.headers["X-AIGW-Cache-Key"] != other.headers["X-AIGW-Cache-Key"]
    # SUPERSEDED (OME-305, owner decision B), was:
    #     assert first.headers["X-AIGW-Cache-Reason"] == BYPASS_DECLARED
    # A keyed parameter produces no reason at all: the header is present-but-empty
    # because there is nothing to explain. It stays asserted rather than dropped, so a
    # regression that reintroduced a bypass reason here would still be caught.
    assert first.headers["X-AIGW-Cache-Reason"] == ""


# --- leakage ------------------------------------------------------------------


def test_cache_headers_do_not_leak_content(credential_blobs, cache_client) -> None:
    _arrange_account(cache_client, credential_blobs)
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(
            _CHAT_PATH,
            json=_chat_body(messages=[{"role": "user", "content": "SECRET-PROMPT"}]),
        )
    header_blob = json.dumps(dict(resp.headers))
    assert "SECRET-PROMPT" not in header_blob
    assert "SECRET-ANSWER" not in header_blob
