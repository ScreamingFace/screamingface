"""OME-884 — direct OpenAI through the global exact-request cache, at the ROUTE.

FEATURE: `openai/*` traffic participates in the one globally shared exact-request cache.
Two callers whose EFFECTIVE requests are identical share one stored OpenAI response; two
whose are not, never do.

STORY: as a benchmark operator I re-run a suite and the identical calls are served from
the first run's responses — including for a model I addressed directly without seeding it.

INVARIANT under test (owner-approved MVP): ``default_models`` is the BOOTSTRAP CATALOG,
not an allowlist. Publication governs ``/v1/models`` and nothing else — an unlisted
route-valid model dispatches and caches exactly like a published one, and unpublishing a
model neither refuses a direct call nor destroys a stored row.

AIDEV-NOTE: these are the ROUTE proofs, and only those. The pure key material lives in
``test_openai_global_cache_projection.py`` and the wire in ``test_openai_dispatch_wire.py``;
nothing here asserts on a projection dict or an HTTP payload, and nothing there builds an
app. Split from ``test_openai_gateway_acceptance.py`` — that file owns the catalog and
pre-credential rejection contract, a different responsibility.

Scope of THIS file: the ordinary lane (miss, store, replay) and the refusals that must
neither read nor fill a row. Siblings:
  ``test_openai_route_global_cache_key_material.py`` — profile defaults in, identity out.
  ``test_openai_route_global_cache_modifier.py``     — the ambient modifier end to end.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import httpx
from litellm.exceptions import NotFoundError

from aigateway.core.request_cache.global_controls import BYPASS_OPTED_OUT

from .route_harness import PUBLISHED as _PUBLISHED
from .route_harness import UNLISTED as _UNLISTED

# The route arrangement is shared with the sibling suites; see ``route_harness``. Bound
# to the original private names so every relocated test body below reads unchanged.
from .route_harness import Dispatch as _Dispatch
from .route_harness import Store as _Store
from .route_harness import body as _body
from .route_harness import dispatching as _dispatching
from .route_harness import install as _install
from .route_harness import listed_models as _listed_models
from .route_harness import post as _post
from .route_harness import seed_profile as _seed_profile

# --- the ordinary lane: miss, store, replay -----------------------------------


def test_a_published_model_misses_stores_and_then_replays(cache_client) -> None:
    """The headline behavior: one OpenAI call answers two identical requests.

    Before OME-884 direct OpenAI inherited the base ``CacheBypass``, so this second
    request always dispatched. The row's provenance columns are asserted too — a row
    filed under the wrong provider or model is unreachable by every future replay.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        first = _post(cache_client, _body())
        second = _post(cache_client, _body())

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert first.headers["X-AIGW-Cache-Key"] == second.headers["X-AIGW-Cache-Key"]
    assert len(dispatch.bodies) == 1, "the replay dispatched to OpenAI"
    assert len(store.rows) == 1
    assert [(write.provider, write.model) for write in store.writes] == [("openai", _PUBLISHED)]
    assert second.json()["choices"][0]["message"]["content"] == "ANSWER-1"


def test_a_model_outside_the_published_catalog_caches_exactly_like_a_published_one(
    cache_client,
) -> None:
    """Catalog != allowlist, in the cache as well as at dispatch.

    INVARIANT: ``default_models`` decides what ``/v1/models`` advertises. It decides
    nothing about what may be sent, dispatched, keyed or replayed.
    """
    assert _UNLISTED not in _listed_models(cache_client)
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        first = _post(cache_client, _body(model=_UNLISTED))
        second = _post(cache_client, _body(model=_UNLISTED))

    assert first.status_code == 200, first.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert len(dispatch.bodies) == 1
    assert dispatch.bodies[0]["model"] == _UNLISTED
    assert [write.model for write in store.writes] == [_UNLISTED]


def test_different_models_and_different_questions_never_share_a_row(cache_client) -> None:
    """Three requests that differ in exactly one place each get three keys."""
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    variants = [_body(), _body(model=_UNLISTED), _body(question="an entirely different question")]

    with _dispatching(cache_client, dispatch):
        responses = [_post(cache_client, variant) for variant in variants]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert [r.headers["X-AIGW-Cache"] for r in responses] == ["miss", "miss", "miss"]
    assert len({r.headers["X-AIGW-Cache-Key"] for r in responses}) == 3
    assert len(store.rows) == 3
    assert len(dispatch.bodies) == 3


def test_two_max_tokens_ceilings_never_share_a_row(cache_client) -> None:
    """``max_tokens`` is KEYED, so a truncated answer never answers a roomier request.

    INVARIANT (the reason the rule may not go back to ``bypass``): the cache stage
    deliberately stores a ``finish_reason: "length"`` response, because a truncation is
    the correct answer to the request that asked for it. Un-key the ceiling and the
    caller asking for 4000 tokens is served the answer that stopped at 64.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        tight = _post(cache_client, _body(max_tokens=64))
        roomy = _post(cache_client, _body(max_tokens=4000))
        again = _post(cache_client, _body(max_tokens=64))

    assert [tight.headers["X-AIGW-Cache"], roomy.headers["X-AIGW-Cache"]] == ["miss", "miss"]
    assert tight.headers["X-AIGW-Cache-Key"] != roomy.headers["X-AIGW-Cache-Key"]
    assert again.headers["X-AIGW-Cache"] == "hit"
    assert again.headers["X-AIGW-Cache-Key"] == tight.headers["X-AIGW-Cache-Key"]
    assert len(store.rows) == 2
    assert [body["max_tokens"] for body in dispatch.bodies] == [64, 4000]


def test_unpublishing_a_model_hides_the_listing_without_disabling_calls_or_replay(
    cache_client, monkeypatch
) -> None:
    """The MVP semantics an operator can actually observe.

    ``/v1/models`` reads ``register_models()`` live, so removing a seed takes effect at
    once. What must NOT take effect is any change to dispatch or to the cache: the row
    stored while the model was published still replays, and a brand-new request for the
    same unpublished model still reaches OpenAI.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        filled = _post(cache_client, _body())
    assert filled.headers["X-AIGW-Cache"] == "miss"
    assert _PUBLISHED in _listed_models(cache_client)

    plugin = cast(Any, cache_client.app).state.providers.get("openai")
    monkeypatch.setattr(
        plugin.settings,
        "default_models",
        [model for model in plugin.settings.default_models if model != _PUBLISHED],
    )

    assert _PUBLISHED not in _listed_models(cache_client)

    with _dispatching(cache_client, dispatch):
        replayed = _post(cache_client, _body())
        fresh = _post(cache_client, _body(question="asked only after unpublishing"))

    assert replayed.headers["X-AIGW-Cache"] == "hit"
    assert replayed.headers["X-AIGW-Cache-Key"] == filled.headers["X-AIGW-Cache-Key"]
    assert fresh.status_code == 200, fresh.text
    assert fresh.headers["X-AIGW-Cache"] == "miss"
    assert len(dispatch.bodies) == 2
    assert len(store.rows) == 2


# --- refusals: what must never reach, or leave, a row -------------------------


def test_a_malformed_model_never_reads_or_writes_the_cache(cache_client) -> None:
    """A model id the grammar rejects is refused locally and is invisible to the store.

    INVARIANT: the projection and ``prepare_chat_body`` share ONE predicate, so a
    request the cache would key is necessarily one dispatch would forward. This is the
    other half — an id neither will accept must not produce a read or a row.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        response = _post(cache_client, _body(model="openai/gpt 5"))

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_model"
    assert store.reads == []
    assert store.writes == []
    assert dispatch.bodies == []


def test_a_route_valid_unsupported_model_misses_is_refused_by_openai_and_stores_nothing(
    cache_client,
) -> None:
    """OpenAI is the authority on existence, and its refusal is not an answer.

    The request is eligible — it IS read from the cache — so the gateway asks OpenAI
    rather than guessing from a catalog. A 404 must leave the store exactly as it was:
    caching a refusal would make a transient or account-scoped rejection permanent for
    every caller in the deployment.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    rejection = NotFoundError(
        message="The model `gpt-does-not-exist` does not exist or you do not have access to it.",
        llm_provider="openai",
        model="gpt-does-not-exist",
        response=httpx.Response(
            404, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        ),
    )

    async def _reject(**_kwargs):
        raise rejection

    with patch("litellm.acompletion", new=_reject):
        response = _post(cache_client, _body(model="openai/gpt-does-not-exist"))

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "provider_error"
    # Sanitized: the raw provider text never reaches the caller.
    assert "gpt-does-not-exist" not in response.text
    assert len(store.reads) == 1, "the request was not even looked up"
    assert store.writes == []
    assert store.rows == {}


def test_caller_opt_out_bypasses_neither_reading_nor_filling(cache_client) -> None:
    """``cache: {"use-cache": false}`` means both directions, and leaves no trace."""
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        filled = _post(cache_client, _body())
        opted_out = _post(cache_client, {**_body(), "cache": {"use-cache": False}})

    assert filled.headers["X-AIGW-Cache"] == "miss"
    assert opted_out.status_code == 200, opted_out.text
    assert opted_out.headers["X-AIGW-Cache"] == "bypass"
    assert opted_out.headers["X-AIGW-Cache-Reason"] == BYPASS_OPTED_OUT
    assert len(store.reads) == 1, "the opt-out read the cache anyway"
    assert len(store.rows) == 1, "the opt-out filled the cache anyway"
    assert len(dispatch.bodies) == 2
    # INVARIANT: the gateway control object never reaches the provider as a parameter.
    assert "cache" not in dispatch.bodies[1]


def test_an_ambient_alias_refuses_replay_of_that_model_alone_and_preserves_the_row(
    cache_client, monkeypatch
) -> None:
    """The fill-then-poison tripwire: the row survives, but is no longer reachable.

    An entry in ``litellm.model_alias_map`` silently redirects one id to another, so a
    row stored under the requested id would be replayed while a miss dispatched
    something different — the wrong-hit class. The cache stage runs before model
    resolution and before any credential is read, so the dispatch-side 503 alone cannot
    deliver this: participation has to refuse it too.

    INVARIANT: the refusal is EXACTLY as wide as the alias. Every other model keeps its
    cache, and the poisoned model's row is left intact rather than deleted.
    """
    import litellm

    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        _post(cache_client, _body())
        _post(cache_client, _body(model=_UNLISTED))
    assert len(store.rows) == 2
    reads_before = len(store.reads)

    monkeypatch.setattr(litellm, "model_alias_map", {_PUBLISHED: "openai/gpt-4o"})

    # No dispatch patch: the request must be REFUSED by the real dispatch guard rather
    # than quietly sent into a runtime this plugin's adapter revision does not describe.
    refused = _post(cache_client, _body())
    # Snapshot BEFORE the next request: the unaffected model legitimately reads.
    reads_after_refusal = len(store.reads)
    with _dispatching(cache_client, dispatch):
        unaffected = _post(cache_client, _body(model=_UNLISTED))

    assert refused.status_code == 503, refused.text
    assert refused.json()["detail"]["code"] == "unsafe_openai_environment"
    assert reads_after_refusal == reads_before, "the aliased model was still looked up"
    assert len(store.rows) == 2, "the stored row was destroyed rather than made unreachable"
    assert unaffected.headers["X-AIGW-Cache"] == "hit"
