"""OME-884 cycle 2 — the ambient request modifier, at the ROUTE, end to end.

FEATURE: one globally shared exact-request cache (OME-305). ``litellm.modify_params``
rewrites ``max_tokens`` after this gateway has built the key, so while it is enabled direct
OpenAI must stop using the cache — without inventing an outage for the requests LiteLLM
cannot touch.

STORY: as an operator who enabled the flag by accident (``LITELLM_MODIFY_PARAMS=false``
enables it, in LiteLLM 1.97.0) I keep serving traffic; caching resumes, against the rows
already stored, the moment I unset the variable.

INVARIANT under test, through the real app and the real store: the enabled flag causes
neither a read nor a write and PRESERVES the existing row; a request carrying a ceiling —
explicit or profile-defaulted — is refused; a request without one is served live and
uncached. The unit-level verdicts behind this live in ``test_openai_runtime_modifier.py``.
"""

from __future__ import annotations

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON

# The route arrangement is shared with the sibling suites; see ``route_harness``. Bound
# to the original private names so every relocated test body below reads unchanged.
from .route_harness import Dispatch as _Dispatch
from .route_harness import Store as _Store
from .route_harness import body as _body
from .route_harness import dispatching as _dispatching
from .route_harness import install as _install
from .route_harness import post as _post
from .route_harness import seed_profile as _seed_profile

# --- OME-884 review cycle 2: the ambient modifier, end to end -----------------


def test_an_enabled_modifier_stops_reading_and_filling_but_preserves_the_row(
    cache_client, monkeypatch
) -> None:
    """The second fill-then-poison tripwire, and the whole point of the cycle-2 fix.

    ``litellm.modify_params`` rewrites ``max_tokens`` AFTER the key is built, so a runtime
    with it enabled would store an answer produced under a ceiling the key does not record.
    The row must therefore go untouched in both directions — not read, not written — while
    the flag is on, and become reachable again the moment it is cleared. Deleting or
    re-keying the row instead would throw away a generation that is still perfectly correct
    for every runtime that is not modifying anything.

    INVARIANT: participation is refused for the whole provider here, not just for requests
    carrying a ceiling, because the participation port receives only the model and cannot
    see ``max_tokens``. Over-declining costs reuse; over-permitting would cost correctness.
    """
    import litellm

    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with _dispatching(cache_client, dispatch):
        filled = _post(cache_client, _body())
    assert filled.headers["X-AIGW-Cache"] == "miss"
    assert filled.headers["X-AIGW-Cache-Write"] == "stored"
    assert len(store.rows) == 1
    reads_before, writes_before = len(store.reads), len(store.writes)

    monkeypatch.setattr(litellm, "modify_params", True)
    with _dispatching(cache_client, dispatch):
        under_modifier = _post(cache_client, _body())

    assert under_modifier.status_code == 200, under_modifier.text
    # A live answer, NOT the stored one: proof the row was genuinely not consulted.
    assert under_modifier.json()["choices"][0]["message"]["content"] == "ANSWER-2"
    assert under_modifier.headers["X-AIGW-Cache"] == "bypass"
    assert under_modifier.headers["X-AIGW-Cache-Reason"] == PROJECTION_BYPASS_REASON
    assert len(store.reads) == reads_before, "a modifying runtime still looked the row up"
    assert len(store.writes) == writes_before, "a modifying runtime still stored its answer"
    assert len(store.rows) == 1, "the intact row was destroyed rather than made unreachable"

    monkeypatch.setattr(litellm, "modify_params", False)
    # No dispatch patch: clearing the flag must make the PRESERVED row answer again.
    restored = _post(cache_client, _body())

    assert restored.headers["X-AIGW-Cache"] == "hit"
    assert restored.headers["X-AIGW-Cache-Key"] == filled.headers["X-AIGW-Cache-Key"]
    assert restored.json()["choices"][0]["message"]["content"] == "ANSWER-1"


def test_a_profile_defaulted_ceiling_is_refused_under_an_enabled_modifier(
    cache_client, monkeypatch
) -> None:
    """A stored default is an EFFECTIVE ceiling, so it gets the dispatch refusal too.

    Profile defaults are merged into the body before the cache stage (OME-305 ruling 57),
    so by the time dispatch inspects ``max_tokens`` a defaulted value is indistinguishable
    from a typed one — which is exactly right. A caller who never mentions ``max_tokens``
    can still be sent a ceiling LiteLLM rewrote, and this proves that path is refused
    rather than silently modified.
    """
    import litellm

    _seed_profile(cache_client, name="tight", defaults={"max_tokens": 64})
    store = _install(cache_client, _Store())

    monkeypatch.setattr(litellm, "modify_params", True)
    # No dispatch patch: the REAL guard must refuse before any upstream work happens.
    refused = _post(cache_client, _body(), profile="tight")

    assert refused.status_code == 503, refused.text
    assert refused.json()["detail"]["code"] == "unsafe_openai_environment"
    assert store.reads == [], "a refused request still looked the cache up"
    assert store.writes == [], "a refused request still wrote to the cache"


def test_a_request_without_a_ceiling_still_serves_under_an_enabled_modifier(
    cache_client, monkeypatch
) -> None:
    """The over-refusal this design exists to avoid, asserted at the route.

    Putting ``modify_params`` in the shared ambient tuple would have 503'd this request —
    a request installed LiteLLM provably never rewrites, because its modifier branch
    requires a non-``None`` ``max_tokens``. It must still be served, merely uncached.
    """
    import litellm

    _seed_profile(cache_client)
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    monkeypatch.setattr(litellm, "modify_params", True)
    with _dispatching(cache_client, dispatch):
        served = _post(cache_client, _body())

    assert served.status_code == 200, served.text
    assert served.json()["choices"][0]["message"]["content"] == "ANSWER-1"
    assert served.headers["X-AIGW-Cache"] == "bypass"
    assert store.reads == [] and store.writes == []
    assert "max_tokens" not in dispatch.bodies[0]
