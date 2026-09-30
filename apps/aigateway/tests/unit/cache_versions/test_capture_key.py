"""Support: the capture key equals the live global cache key for the same body.

FEATURE: OME-1307 (E14) - capture and the later replay lookup key a call exactly like the live
cache does, so a captured call can be found again by the same hash.
INVARIANT: `build_capture_key` ignores the operator switch and the caller opt-out. An opted-out
call still has a key, because its prompt is kept for the freeze (CV-H1).
"""

from __future__ import annotations

import hashlib
from typing import Any

from aigateway.core.cache_versions.capture_key import build_capture_key
from aigateway.core.cache_versions.ports import CaptureKey
from aigateway.core.request_cache.global_controls import (
    BYPASS_OPTED_OUT,
    GlobalCacheControls,
    parse_global_cache_controls,
)
from aigateway.core.request_cache.global_keys import GlobalCacheKeyResult
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.anthropic_provider.plugin import PLUGIN as ANTHROPIC
from aigateway.plugins.gemini_provider.plugin import PLUGIN as GEMINI


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _live_key_hash(body: dict[str, Any]) -> str:
    plan = build_global_cache_plan(
        body=dict(body),
        plugin=ANTHROPIC,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )
    assert isinstance(plan, GlobalCacheKeyResult), plan
    return plan.key_hash


def test_capture_key_equals_the_global_cache_key() -> None:
    body = _body(temperature=0)

    key = build_capture_key(body=dict(body), plugin=ANTHROPIC)

    assert key is not None
    assert key.key_hash == _live_key_hash(body)
    assert hashlib.sha256(key.material.encode("utf-8")).hexdigest() == key.key_hash
    assert "how many primes below one hundred?" in key.material


def test_an_opted_out_body_still_has_a_capture_key() -> None:
    body = _body(cache={"use-cache": False})
    controls = parse_global_cache_controls(body)  # pops `cache`, like the route does
    assert controls.bypass_reason == BYPASS_OPTED_OUT, "the live cache would bypass this call"

    key = build_capture_key(body=body, plugin=ANTHROPIC)

    assert key is not None
    assert key.key_hash == _live_key_hash(_body())


def test_a_non_participating_provider_has_no_capture_key() -> None:
    body = _body(model="gemini/gemini-2.5-flash")

    assert build_capture_key(body=body, plugin=GEMINI) is None


def test_a_streaming_body_has_no_capture_key() -> None:
    assert build_capture_key(body=_body(stream=True), plugin=ANTHROPIC) is None


def test_capture_key_repr_hides_the_material() -> None:
    key = CaptureKey(key_hash="ab" * 32, material="the secret prompt text")

    text = repr(key)

    assert "secret prompt" not in text
    assert text == f"CaptureKey(key_hash={'ab' * 6}…)"
