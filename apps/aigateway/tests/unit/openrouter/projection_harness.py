"""The shared arrangement behind OpenRouter's global-cache proofs.

WHY a module rather than a copy per suite: three cohesive suites ask three different
questions about the SAME projection — what shape it produces and what it refuses to
describe, whether those equivalences survive as far as the HASH, and whether the operator
switch governs participation without touching key material. They are only comparable while
they build the request identically.

INVARIANT: every helper here is pure. No plugin constructed here holds a credential, and
nothing reads the clock, the environment or the filesystem — the projection under test is
contractually a pure function of the request body, so its harness must not be the thing
that smuggles state in.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.cache_ports import CacheBypass
from aigateway.core.request_cache.global_keys import build_global_cache_key
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

MODEL = "openrouter/anthropic/claude-fable-5"
UPSTREAM = "anthropic/claude-fable-5"
MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]

# Spelled out rather than imported: a rename of the production constant must not be
# able to silently rename what the gateway forces onto every routing policy.
STRICT = {"require_parameters": True}


def plugin() -> OpenRouterProviderPlugin:
    return OpenRouterProviderPlugin()


def body(**overrides: Any) -> dict[str, Any]:
    built: dict[str, Any] = {"model": MODEL, "messages": [dict(m) for m in MESSAGES]}
    built.update(overrides)
    return built


def projected(**overrides: Any) -> dict[str, Any]:
    produced = plugin().global_cache_projection(body(**overrides))
    assert not isinstance(produced, CacheBypass), produced
    return produced


def policy(**overrides: Any) -> Any:
    return projected(**overrides)["prepared"]["provider"]


def reason(**overrides: Any) -> str:
    produced = plugin().global_cache_projection(body(**overrides))
    assert isinstance(produced, CacheBypass), produced
    return produced.reason


def key(**overrides: Any) -> str:
    built_for = plugin()
    built = build_global_cache_key(
        provider="openrouter",
        body=body(**overrides),
        rules=built_for.chat_parameter_rules(model=MODEL, auth_type=None),
        projection=built_for.global_cache_projection,
        provider_auth_modes=built_for.available_auth_modes(),
    )
    assert not isinstance(built, CacheBypass), built
    return built.key_hash
