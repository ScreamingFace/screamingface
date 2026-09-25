"""OME-884 — what enters a direct-OpenAI cache key at the ROUTE, and what cannot.

FEATURE: one globally shared exact-request cache (OME-305). The key is built from the
caller's request — since OME-1323 (D2) the gateway merges no stored Profile default into
it — and anything about WHO is asking must not be in it.

STORY: as a benchmark operator I re-run a suite from a second account that holds no OpenAI
key of its own, and the identical calls are served from the first run's rows — no OpenAI
credential is read or decrypted to serve them.

INVARIANT under test: account, profile, auth mode and credential are structurally absent,
which is what licenses cross-account replay. A hit reads no provider credential, dispatches
nothing, and reports no accounting rather than a failed accounting mapper. (Explicit caller
parameters keying apart is pinned by ``test_chat_global_cache_key_parity.py``.)
"""

from __future__ import annotations

import logging
from typing import Any, cast

# The route arrangement is shared with the sibling suites; see ``route_harness``. Bound
# to the original private names so every relocated test body below reads unchanged.
from .route_harness import Dispatch as _Dispatch
from .route_harness import Store as _Store
from .route_harness import body as _body
from .route_harness import dispatching as _dispatching
from .route_harness import install as _install
from .route_harness import post as _post
from .route_harness import seed_profile as _seed_profile

# --- identity is structurally absent from the key -----------------------------


def test_a_second_account_replays_the_first_accounts_row_without_a_key_of_its_own(
    cache_client, provisioned_user_factory
) -> None:
    """The inversion this ticket exists for, across an account boundary.

    The replaying account has no OpenAI profile and no OpenAI credential. It is served
    anyway, because neither the account, the profile name nor the credential is in the
    key — the accepted, documented consequence of a globally shared cache.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        filled = _post(cache_client, _body())
    assert filled.headers["X-AIGW-Cache"] == "miss"

    provisioned_user_factory("second-account")
    login = cache_client.post(
        "/v1/auth/login",
        json={"username": "second-account", "password": "test-user-password"},
    )
    assert login.status_code == 200, login.text
    cache_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    with _dispatching(cache_client, dispatch):
        replayed = _post(cache_client, _body())

    assert replayed.status_code == 200, replayed.text
    assert replayed.headers["X-AIGW-Cache"] == "hit"
    assert replayed.headers["X-AIGW-Cache-Key"] == filled.headers["X-AIGW-Cache-Key"]
    assert replayed.json()["choices"][0]["message"]["content"] == "ANSWER-1"
    assert len(dispatch.bodies) == 1
    assert len(store.rows) == 1


def test_a_hit_reads_no_openai_credential_dispatches_nothing_and_reports_no_accounting(
    cache_client, monkeypatch, caplog
) -> None:
    """What a hit must NOT do — the whole point of placing the stage before Stage 2.

    The guard refuses only ``aigateway:openai:`` provider credentials: reading one would
    mean decrypting a secret to serve a response that needs none. The request that
    reaches the cache is exactly the caller's body (OME-1323, D2), and no Profile read
    runs to supplement it.

    Also pinned here: the accounting a hit reports. Direct OpenAI contributes no usage
    strategy, so ``accounting_not_supported`` is the honest answer, and its explicit
    ``cache_reference_from_cached_response`` returning ``None`` must not be mistaken for
    a mapper FAILURE — a missing attribute would log one on every single hit.
    """
    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        filled = _post(cache_client, _body())
    assert filled.headers["X-AIGW-Cache"] == "miss"

    credential_store = cast(Any, cache_client.app).state.credential_store
    real_read = credential_store.read

    async def guarded_read(service: str, account: str) -> str | None:
        if service.startswith("aigateway:openai:"):
            raise AssertionError("a cache hit read the OpenAI provider credential")
        return await real_read(service, account)

    monkeypatch.setattr(credential_store, "read", guarded_read)

    def _refuse(*_args, **_kwargs):
        raise AssertionError("a cache hit dispatched to OpenAI")

    with caplog.at_level(logging.WARNING, logger="aigateway.plugins.taxonomy.session"):
        with _dispatching(cache_client, _refuse):
            served = _post(cache_client, _body())

    assert served.status_code == 200, served.text
    assert served.headers["X-AIGW-Cache"] == "hit"
    assert served.json()["choices"][0]["message"]["content"] == "ANSWER-1"
    assert len(store.rows) == 1
    assert len(dispatch.bodies) == 1

    accounting = served.json()["_aigw"]["usage_accounting"]
    assert accounting["capture_status"] == "accounting_not_supported"
    assert accounting["cache"] == {"status": "hit", "reference": None}
    assert accounting["attempts"] == []
    assert accounting["observed_attempts"] == 0
    assert "cache-reference mapper" not in caplog.text
