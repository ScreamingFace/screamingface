"""OME-884 Unit 3 — ``max_tokens`` promoted from ``bypass`` to ``keyed``, end to end.

FEATURE: one global exact-request cache (OME-305). ``max_tokens`` is direct OpenAI's one
enabled ordinary parameter. OME-864 had to declare it ``cache_behavior="bypass"`` because
no projection existed; a keyed rule on a provider with no projection is unobservable.

STORY: as a benchmark operator I re-run a suite that pins a token ceiling and the second
run is served from stored rows — while a run with a DIFFERENT ceiling is not.

INVARIANT under test: the effective ceiling is part of the key. Equal effective values
share one row (explicit or profile-defaulted — the body-wins merge runs before the cache
stage, OME-305 ruling 57); different values, a different model, or no ceiling at all never
collide. This is the precondition for ``chat_cache_stage._is_a_whole_answer`` storing a
``finish_reason: "length"`` response: with ``bypass``, a caller asking for 4000 tokens
would be served the answer that stopped at 20.

Scope of THIS file: the parameter contract and the keys it produces, proven through the
REAL plan. The projection's own purity lives in
``test_openai_global_cache_projection.py``; the wire spelling of the ceiling for every
published model lives in ``test_openai_dispatch_wire.py``.
"""

from __future__ import annotations

from typing import Any

import litellm
import pytest

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.request_cache.global_controls import parse_global_cache_controls
from aigateway.core.request_cache.global_keys import GlobalCacheKeyResult
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.openai_provider.plugin import PLUGIN

# Bound to the original private name so every relocated test body below reads unchanged.
from .ambient_state import safe_runtime as _safe_runtime

_SEEDED = "openai/gpt-5.6-sol"
_UNLISTED = "openai/gpt-4o-2024-11-20"


def _body(model: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


# --- OME-884 Unit 3: the keyed ``max_tokens`` contract -------------------------
#
# WHY these proofs run through ``build_global_cache_plan`` rather than calling the key
# builder directly: the plan is what the route actually uses, so it exercises the real
# provider auth modes, the real participation gate, the real rule table and the real
# projection together. A key proof that bypassed it could stay green while the request
# path bypassed every time.


def _plan(body: dict[str, Any]) -> Any:
    return build_global_cache_plan(
        body=body,
        plugin=PLUGIN,
        controls=parse_global_cache_controls({}),
        cache_enabled=True,
    )


def _planned_key(body: dict[str, Any]) -> str:
    planned = _plan(body)
    assert isinstance(planned, GlobalCacheKeyResult), planned
    return planned.key_hash


@pytest.mark.parametrize("model", [_SEEDED, _UNLISTED, "openai/gpt-4o", "openai/o3"])
def test_max_tokens_is_keyed_for_every_route_valid_model(model: str) -> None:
    """Promoted from ``bypass`` — and only now that a real projection backs it.

    A keyed rule on a provider with no projection is unobservable: the missing
    projection bypasses the request regardless of what its rules declare. That is why
    the promotion had to wait for the projection rather than shipping with OME-864.
    """
    rules = PLUGIN.chat_parameter_rules(model=model, auth_type=None)

    assert len(rules) == 1
    assert rules[0].request_path == "max_tokens"
    assert rules[0].cache_behavior == "keyed"
    # INVARIANT (ruling 59): the pre-auth key cannot honor a mode-restricted promise, so
    # a keyed rule must apply in EVERY mode the provider offers.
    assert set(PLUGIN.available_auth_modes()) <= set(rules[0].applicable_auth_modes)


def test_a_request_carrying_max_tokens_is_now_keyed_rather_than_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _safe_runtime(monkeypatch)

    assert _planned_key(_body(_SEEDED, max_tokens=64))


def test_equal_effective_ceilings_share_one_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    # The body-wins profile-default merge runs BEFORE the cache stage, so by the time a
    # plan is built there is no difference between "the caller sent 64" and "the profile
    # defaulted to 64". One upstream call, one row.
    _safe_runtime(monkeypatch)

    assert _planned_key(_body(_SEEDED, max_tokens=64)) == _planned_key(
        _body(_SEEDED, max_tokens=64)
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ({"max_tokens": 64}, {"max_tokens": 65}),
        ({"max_tokens": 64}, {}),
    ],
)
def test_different_effective_ceilings_never_collide(
    monkeypatch: pytest.MonkeyPatch, left: dict[str, Any], right: dict[str, Any]
) -> None:
    """The wrong-hit class this promotion exists to close.

    ``chat_cache_stage._is_a_whole_answer`` STORES a ``finish_reason: "length"``
    response, on the stated grounds that a truncation is the correct answer to the
    request that asked for it. That is sound ONLY while the ceiling is keyed: with
    ``bypass``, a caller asking for 4000 tokens would be served the answer that stopped
    at 20. An absent ceiling is its own case — it is not "unlimited equals some number".
    """
    _safe_runtime(monkeypatch)

    assert _planned_key(_body(_SEEDED, **left)) != _planned_key(_body(_SEEDED, **right))


def test_the_same_ceiling_on_two_models_never_collides(monkeypatch: pytest.MonkeyPatch) -> None:
    # LiteLLM maps the ceiling to ``max_tokens`` for GPT-4/4o and to
    # ``max_completion_tokens`` for GPT-5/o-series. Two spellings, one meaning — and the
    # model is keyed independently, so the difference can never be papered over.
    _safe_runtime(monkeypatch)

    assert _planned_key(_body("openai/gpt-4o", max_tokens=64)) != _planned_key(
        _body(_SEEDED, max_tokens=64)
    )


def test_an_unlisted_model_reaches_a_key_through_the_real_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End to end through the plan: participation, rules, auth modes and projection all
    # have to agree before an unlisted model produces a key at all.
    _safe_runtime(monkeypatch)

    assert _planned_key(_body(_UNLISTED, max_tokens=8)) != _planned_key(
        _body(_SEEDED, max_tokens=8)
    )


def test_a_malformed_model_produces_no_plan_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _safe_runtime(monkeypatch)

    assert _plan(_body("openai/gpt 5", max_tokens=8)) == CacheBypass(
        reason=PROJECTION_BYPASS_REASON
    )


def test_an_unsafe_runtime_produces_no_plan_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The participation gate reached through the real plan, not called directly.
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "headers", {"X-Leak": "ambient"})

    assert _plan(_body(_SEEDED, max_tokens=8)) == CacheBypass(reason=PROJECTION_BYPASS_REASON)


def test_a_caller_opt_out_bypasses_a_request_that_would_otherwise_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _safe_runtime(monkeypatch)
    body = _body(_SEEDED, max_tokens=8)
    controls = parse_global_cache_controls({"cache": {"use-cache": False}})

    decision = build_global_cache_plan(
        body=body, plugin=PLUGIN, controls=controls, cache_enabled=True
    )

    assert isinstance(decision, CacheBypass)
    assert decision.reason == controls.bypass_reason
