"""OME-791 — the HF chat route's global-cache miss -> store -> hit behaviour.

FEATURE: one globally shared exact-request cache (OME-305).

STORY: as a benchmark operator I re-run a suite against a backend-pinned HF model and the
identical calls come back from the first run's rows — one dispatch, one row, and no HF token
read on the replay.

What this module pins, and why each matters:
- the route's end-to-end contract, including the things that must NOT happen on a hit;
- that an id whose backend is chosen PER REQUEST dispatches normally and never touches a row.

Split from the keying tests (OME-791 review); see ``test_huggingface_global_cache_keys.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.request_cache import RequestCacheWrite
from aigateway.plugins.huggingface_provider.plugin import PLUGIN
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_CHAT_PATH = "/v1/chat/completions"
_PATCH_TARGET = (
    "aigateway.plugins.huggingface_provider.plugin.HuggingFaceProviderPlugin.chat_completion"
)
_MODEL = "huggingface/deepseek-ai/DeepSeek-R1:novita"
_HF_KEY = "hf_route_global_cache_key_1234567890"


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


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


@pytest.mark.parametrize("suffix", ["fastest", "cheapest", "preferred", "auto", "notarealprovider"])
def test_a_policy_id_dispatches_every_time_and_never_touches_the_cache(
    suffix: str, cache_client: TestClient
) -> None:
    """OME-791 B1/B3 at the ROUTE, where the damage would actually be done.

    The projection-level test proves no key is produced. This proves the consequence a caller
    can observe: the second identical request DISPATCHES AGAIN instead of becoming a hit, and no
    row is written that a different account could later be served.
    """
    store = _install(cache_client)
    counter = _DispatchCounter()
    model = f"huggingface/deepseek-ai/DeepSeek-R1:{suffix}"

    with patch(_PATCH_TARGET, counter):
        first = cache_client.post(_CHAT_PATH, json=_body(model=model))
        second = cache_client.post(_CHAT_PATH, json=_body(model=model))

    # Dispatch is untouched by this change — a policy id is a VALID request.
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "bypass"
    assert second.headers["X-AIGW-Cache"] == "bypass"
    assert len(counter.calls) == 2, "a policy request must never become a cache hit"
    assert store.set_calls == [], "no row may be written for an account-dependent route"
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
