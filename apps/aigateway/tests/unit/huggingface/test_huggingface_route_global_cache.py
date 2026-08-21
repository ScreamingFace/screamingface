"""OME-791 — HF promotion, key differences, and the route's miss -> hit behaviour.

FEATURE: one globally shared exact-request cache (OME-305). The projection made HF
*describable*; promoting its parameter rules from ``bypass`` to ``keyed`` is what makes an
identical re-run actually cheaper.

STORY: as a benchmark operator I re-run a suite against a backend-pinned HF model and the
identical calls come back from the first run's rows — one dispatch, one row, and no HF token
read on the replay.

What this module pins, and why each matters:
- every one of the TWELVE newly-keyed request paths, because a keyed path with no
  key-difference proof is how two materially different requests come to share one answer;
- a derived-set meta-test, so a future keyed path cannot land without its own proof;
- the route's end-to-end contract, including the things that must NOT happen on a hit.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.request_cache import RequestCacheWrite
from aigateway.core.request_cache.global_controls import GlobalCacheControls
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.huggingface_provider.parameters import (
    huggingface_chat_parameter_rules,
)
from aigateway.plugins.huggingface_provider.plugin import PLUGIN
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_CHAT_PATH = "/v1/chat/completions"
_PATCH_TARGET = (
    "aigateway.plugins.huggingface_provider.plugin.HuggingFaceProviderPlugin.chat_completion"
)
_MODEL = "huggingface/deepseek-ai/DeepSeek-R1:novita"
_HF_KEY = "hf_route_global_cache_key_1234567890"

# The complete set of HF request paths that OME-791 promotes to ``keyed``.
#
# INVARIANT: TWELVE, not the ten ``direct_rule`` calls a reader counts in ``parameters.py``.
# ``function_calling_rules`` emits ``tools`` AND ``tool_choice`` as two separate rules
# (``standard_parameters.py:232-252``, with ``tool_choice=True`` defaulted at ``:204``), so a
# literal set written from the source file alone is wrong by two. The meta-test below derives
# the real set from the live rule table and asserts equality against this literal, so the two
# can never drift.
_EXPECTED_KEYED_PATHS = frozenset(
    {
        "temperature",
        "max_tokens",
        "stop",
        "response_format",
        "seed",
        "n",
        "frequency_penalty",
        "presence_penalty",
        "logprobs",
        "top_logprobs",
        "tools",
        "tool_choice",
    }
)

# One concrete pair of DIFFERENT values per keyed path. A path missing from this table has no
# key-difference proof, which the meta-test refuses.
_KEY_DIFFERENCE_CASES: dict[str, tuple[Any, Any]] = {
    "temperature": (0.0, 1.0),
    "max_tokens": (16, 32),
    "stop": (["END"], ["STOP"]),
    "response_format": ({"type": "text"}, {"type": "json_object"}),
    "seed": (1, 2),
    "n": (1, 2),
    "frequency_penalty": (0.0, 0.5),
    "presence_penalty": (0.0, 0.5),
    # INVARIANT: ``top_logprobs`` requires ``logprobs is True``, so the pair varies the
    # dependent field while holding the enabling one — otherwise the 400 combination rule,
    # not the key, would be what distinguishes the two requests.
    "logprobs": (True, False),
    "top_logprobs": (1, 2),
    "tools": (
        [{"type": "function", "function": {"name": "alpha", "parameters": {}}}],
        [{"type": "function", "function": {"name": "beta", "parameters": {}}}],
    ),
    "tool_choice": ("auto", "none"),
}


def _published_cache_behaviour(document: dict[str, Any]) -> dict[str, str]:
    """``{request_path: cache_behavior}`` as a CALLER reads it off the contract document.

    Shape (verified against the live route): each entry under ``parameters`` — and each tool
    entry under ``tools`` — carries a ``gateway`` block holding ``cache_behavior``. Reading both
    sections matters: ``tools`` and ``tool_choice`` are two of the twelve promoted paths and do
    not appear beside the scalar parameters.
    """
    published: dict[str, str] = {}
    for section in ("parameters", "tools"):
        entries = document.get(section)
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            gateway = entry.get("gateway") if isinstance(entry, dict) else None
            if isinstance(gateway, dict) and "cache_behavior" in gateway:
                published[str(name)] = str(gateway["cache_behavior"])
    return published


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _key_hash(body: dict[str, Any]) -> str:
    """The global cache key for ``body``, through the REAL plan.

    WHY the whole plan rather than the projection alone: a key-difference test that called the
    projection directly would prove nothing about promotion, because the projection does not
    see parameters at all. Only the plan applies the rule table, so only the plan can show that
    a promoted path actually reached the key.
    """
    decision = build_global_cache_plan(
        body=body,
        plugin=PLUGIN,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )
    assert not hasattr(decision, "reason"), f"expected a key, got a bypass: {decision}"
    return cast(Any, decision).key_hash


# --- promotion, proven per path -----------------------------------------------


def test_the_promoted_set_is_exactly_the_twelve_paths_this_unit_claims() -> None:
    keyed = {
        rule.request_path
        for rule in huggingface_chat_parameter_rules(model=_MODEL, auth_type=None)
        if rule.cache_behavior == "keyed"
    }

    assert keyed == set(_EXPECTED_KEYED_PATHS)


def test_every_keyed_path_has_an_explicit_key_difference_proof() -> None:
    """The meta-test that makes this file self-enforcing.

    INVARIANT: a keyed path with no key-difference proof is exactly how two materially
    different requests come to share one stored answer. Deriving the set from the LIVE rules
    means a future promotion cannot land silently — it fails here until someone adds its pair.
    Mirrors ``test_every_openrouter_keyed_path_has_an_explicit_key_difference_proof``.
    """
    keyed = {
        rule.request_path
        for rule in huggingface_chat_parameter_rules(model=_MODEL, auth_type=None)
        if rule.cache_behavior == "keyed"
    }

    assert keyed == set(_KEY_DIFFERENCE_CASES), (
        "every keyed HF path needs a concrete differing-value pair in _KEY_DIFFERENCE_CASES"
    )


@pytest.mark.parametrize("path", sorted(_KEY_DIFFERENCE_CASES))
def test_a_keyed_path_changes_the_key_when_its_value_changes(path: str) -> None:
    low, high = _KEY_DIFFERENCE_CASES[path]
    extra = {"logprobs": True} if path == "top_logprobs" else {}

    assert _key_hash(_body(**{path: low}, **extra)) != _key_hash(_body(**{path: high}, **extra))


@pytest.mark.parametrize("path", sorted(_KEY_DIFFERENCE_CASES))
def test_a_keyed_path_keys_identically_for_an_identical_value(path: str) -> None:
    low, _ = _KEY_DIFFERENCE_CASES[path]
    extra = {"logprobs": True} if path == "top_logprobs" else {}

    assert _key_hash(_body(**{path: low}, **extra)) == _key_hash(_body(**{path: low}, **extra))


def test_two_backends_for_one_repo_do_not_collide() -> None:
    # The projection retains ``:<backend>`` in ``resolved_model``; this is the end-to-end
    # consequence, at the level a caller can observe.
    novita = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:novita"))
    together = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:together"))

    assert novita != together


def test_two_repos_do_not_collide() -> None:
    first = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:novita"))
    second = _key_hash(_body(model="huggingface/Qwen/Qwen3-235B-A22B:novita"))

    assert first != second


def test_every_registered_model_contributes_the_full_keyed_set() -> None:
    """HF's own regression floor, derived rather than hardcoded.

    AIDEV-NOTE: this replaces the tempting alternative of raising
    ``_OBSERVED_NON_BYPASS_INSTANCES`` in the SHARED conformance test. That number depends on
    catalog and environment state, and the file is append-only-protected; a floor derived from
    THIS plugin is both stronger for HF and free of blast radius.
    """
    entries = list(PLUGIN.register_models())
    assert entries, "no HF models registered"

    for entry in entries:
        keyed = {
            rule.request_path
            for rule in huggingface_chat_parameter_rules(model=entry.model_name, auth_type=None)
            if rule.cache_behavior == "keyed"
        }
        assert keyed == set(_EXPECTED_KEYED_PATHS), entry.model_name


async def _no_discovery(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_the_published_parameter_contract_reports_the_promoted_behaviour(
    authenticated_client, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller-visible half of promotion, which nothing else asserts.

    WHY this test exists: the published contract digests each rule's ``cache_behavior`` and
    ``projection_revision`` (``core/model_parameter_contract.py:78``), so this unit moves every
    HF model's ``contract_id`` and flips twelve rows of its detail document. No existing test
    pins a digest or the old revision, which means the entire caller-visible surface could flip
    with nothing objecting. One assertion is enough to make the change deliberate.
    """
    # No live discovery evidence: the unit suite forbids catalog egress
    # (``tests/conftest.py:145-165``), and live backend evidence is orthogonal to what this
    # test asserts — the GATEWAY's own declared cache disposition, which comes from the rule
    # table rather than from any snapshot.
    monkeypatch.setattr(
        type(PLUGIN), "discover_chat_parameter_snapshot", _no_discovery, raising=True
    )

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    index = ProfileIndexStore(credential_store=credential_blobs.store)
    await index.upsert(
        Profile(
            id=profile_id_for(account_id, "huggingface", "default"),
            account_id=account_id,
            provider="huggingface",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )

    resp = authenticated_client.get("/v1/model-parameters", params={"model": _MODEL})
    assert resp.status_code == 200, resp.text

    published = _published_cache_behaviour(resp.json())
    keyed = {path for path, behaviour in published.items() if behaviour == "keyed"}

    assert keyed == set(_EXPECTED_KEYED_PATHS), (
        f"the published contract does not report the promoted set: {sorted(keyed)}"
    )
    # And nothing ELSE quietly became cacheable: the published set is exactly the promotion.
    assert not [path for path, b in published.items() if b not in {"keyed", "bypass"}], published


# --- the route ----------------------------------------------------------------


class _DispatchCounter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> Any:
        self.calls.append(dict(body))
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{len(self.calls)}",
                "choices": [
                    {"message": {"content": "HF-PLAINTEXT-ANSWER-42"}, "finish_reason": "stop"}
                ],
            }
        )


class _MemoryStore:
    """The frozen store contract, in memory.

    INVARIANT modelled: ``get`` returns ``None`` only for a genuine miss;
    ``set_if_absent`` never raises and the first successful insert wins.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[RequestCacheWrite] = []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        self.get_calls.append(key_hash)
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> str:
        self.set_calls.append(entry)
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


@pytest.fixture
def _valid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module is deliberately OUTSIDE ``_LEGACY_API_KEY_ROUTE_MODULES``.

    AIDEV-NOTE: conftest grants its blanket validation success only to a frozen allowlist, and
    a new module is not on it — by design, so new tests exercise the real service unless they
    say otherwise. This double is that explicit statement, scoped to this module.
    """
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: str, _api_key: str) -> Any:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture
def cache_client(
    monkeypatch: pytest.MonkeyPatch, _valid_api_key: None, client: TestClient
) -> TestClient:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    resp = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert resp.status_code == 200, resp.text
    client.headers.update({"Authorization": f"Bearer {resp.json()['token']}"})
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "huggingface", "api_key": _HF_KEY, "label": "hf"},
    )
    assert resp.status_code == 201, resp.text
    return client


def _install(client: TestClient) -> _MemoryStore:
    store = _MemoryStore()
    cast(Any, client.app).state.request_cache_store = store
    return store


def test_an_identical_request_is_answered_from_the_row_with_one_dispatch(
    cache_client: TestClient,
) -> None:
    """THE acceptance test: the whole reason OME-791 exists."""
    store = _install(cache_client)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=_body())
        second = cache_client.post(_CHAT_PATH, json=_body())

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert len(counter.calls) == 1, "the replay must not have dispatched"
    assert len(store.rows) == 1
    assert second.json()["choices"][0]["message"]["content"] == "HF-PLAINTEXT-ANSWER-42"


def test_a_hit_reads_no_huggingface_provider_credential(
    cache_client: TestClient, credential_blobs: Any
) -> None:
    """The inversion this feature is FOR — stated precisely, not aspirationally.

    AIDEV-NOTE: the claim is deliberately narrow. A hit DOES perform one profile-index read,
    and that index is itself a ``credential_blobs`` row, so a hit costs one master-key
    decryption — documented as the accepted pre-cache cost in the AIDEV-NOTE at
    ``routes/chat_profile_defaults.py:68-71``. What must NOT happen is any
    ``aigateway:huggingface:*`` credential read, auth-mode resolution, key injection or
    provider dispatch. An earlier draft of this plan claimed "no credential work", which is
    false and would have failed here.
    """
    from aigateway.core.credential_blob.store import ORMStore

    store = _install(cache_client)
    counter = _DispatchCounter()
    services: list[str] = []
    original = ORMStore.read

    async def _recording(self: Any, service: str, account: str) -> Any:
        services.append(service)
        return await original(self, service, account)

    with patch.object(ORMStore, "read", _recording), patch(_PATCH_TARGET, counter):
        miss = cache_client.post(_CHAT_PATH, json=_body())
        assert miss.headers["X-AIGW-Cache"] == "miss"
        # Control: unless the MISS demonstrably read the HF credential, the assertion on the
        # hit below would pass vacuously.
        assert [s for s in services if "huggingface" in s], (
            f"the miss read no HF credential, so this test would prove nothing: {services}"
        )

        services.clear()
        hit = cache_client.post(_CHAT_PATH, json=_body())

    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert len(counter.calls) == 1, "no dispatch on a hit"
    assert not [s for s in services if "huggingface" in s], (
        f"a hit read an aigateway:huggingface:* credential: {services}"
    )
    # The accepted pre-cache cost, asserted POSITIVELY so the claim above stays honest: a hit
    # does still touch the credential table once, for the profile index.
    assert services, "expected the profile-index read, which is the accepted pre-cache cost"
    assert len(store.rows) == 1


def test_a_streaming_request_is_never_cached(cache_client: TestClient) -> None:
    # D10: refused by the core ahead of any provider
    # (``global_eligibility.TRUTHY_BYPASS_REASONS`` applied at :180, before ``_projected`` at
    # :406). Asserted here for HF SPECIFICALLY because HF's streaming path is live, and a
    # core-owned guarantee no HF test exercises is a guarantee nobody notices breaking.
    store = _install(cache_client)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(_CHAT_PATH, json=_body(stream=True))

    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert resp.headers["X-AIGW-Cache-Reason"] == "stream"
    assert store.rows == {}
    assert store.set_calls == []


def test_an_unsuffixed_id_dispatches_normally_and_never_touches_the_cache(
    cache_client: TestClient,
) -> None:
    # The one bypass that does NOT mirror a dispatch refusal: an unsuffixed id is perfectly
    # dispatchable, so the request must still be SERVED — it simply must not be keyed.
    store = _install(cache_client)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(
            _CHAT_PATH, json=_body(model="huggingface/deepseek-ai/DeepSeek-R1")
        )
        second = cache_client.post(
            _CHAT_PATH, json=_body(model="huggingface/deepseek-ai/DeepSeek-R1")
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "bypass"
    assert second.headers["X-AIGW-Cache"] == "bypass"
    assert len(counter.calls) == 2, "both requests must have dispatched"
    assert store.rows == {}
    assert store.get_calls == [], "an unkeyable request must not even probe the store"


def test_a_caller_opt_out_bypasses_without_writing(cache_client: TestClient) -> None:
    store = _install(cache_client)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        resp = cache_client.post(_CHAT_PATH, json=_body(cache={"participate": False}))

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    assert len(counter.calls) == 1
    assert store.rows == {}


def test_a_failed_dispatch_stores_nothing(cache_client: TestClient) -> None:
    store = _install(cache_client)

    async def _explode(_body: dict[str, Any]) -> Any:
        raise RuntimeError("upstream is down")

    with patch(_PATCH_TARGET, _explode):
        resp = cache_client.post(_CHAT_PATH, json=_body())

    assert resp.status_code >= 400
    # INVARIANT: only a whole answer with a ``finish_reason`` fills a row. Storing an error
    # would make one bad minute upstream permanent, because rows never expire.
    assert store.rows == {}
    assert store.set_calls == []


def test_a_row_filled_at_the_official_base_is_not_replayed_after_an_override(
    cache_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The D3 gate, proven on the READ side and not merely the write side.

    AIDEV-NOTE: this is the test the plan calls a tripwire, and the reason it exists is that
    the OBVIOUS version of it proves nothing. A test that overrides the base FIRST and then
    checks "no row was written" passes trivially — there was never a row to replay. The hazard
    is the other order: a row filled by a deployment pointed at the official router, then
    served to one pointed somewhere else. So this fills first, overrides second, and asserts
    the stored row survives untouched while the request dispatches for real.

    INVARIANT: declining participation is LOSSLESS. The row is neither invalidated nor
    rewritten — an operator who reverts the override gets their cache back.
    """
    store = _install(cache_client)
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        fill = cache_client.post(_CHAT_PATH, json=_body())
        assert fill.headers["X-AIGW-Cache"] == "miss"
        assert fill.headers["X-AIGW-Cache-Write"] == "stored"
        assert len(store.rows) == 1
        stored = dict(store.rows)

        # AIDEV-NOTE: patch the plugin INSTANCE, not the environment. ``PLUGIN`` is a
        # module-level singleton built at import time, so ``AIGW_HUGGINGFACE_*`` set after this
        # module has been imported cannot reach it.
        monkeypatch.setattr(
            PLUGIN,
            "settings",
            HuggingFacePluginSettings(router_api_base="https://proxy.internal/v1"),
        )

        after = cache_client.post(_CHAT_PATH, json=_body())

    assert after.status_code == 200, after.text
    assert after.headers["X-AIGW-Cache"] == "bypass"
    assert after.headers["X-AIGW-Cache-Reason"] == "provider_projection"
    assert len(counter.calls) == 2, "the overridden deployment must dispatch for itself"
    # Lossless: the row is still there, byte for byte.
    assert store.rows == stored
