"""OME-884 — direct OpenAI's PURE global-cache projection and its model-ID contract.

FEATURE: one global exact-request cache (OME-305). OME-864 shipped direct `openai/*`
dispatch with the base class's safe-by-default ``CacheBypass``, so no direct OpenAI
request has ever been cacheable. This suite pins the projection that changes that.

STORY: as a benchmark operator I re-run a suite against `openai/*` and the identical
calls are served from the first run's stored responses — including from a second
account, and including for a model I addressed directly without seeding it.

INVARIANT under test: the projection is a PURE, TOTAL function of the request body.
Everything output-affecting that the boundary adds is either described in ``prepared``
(JSON-safe) or folded into ``GLOBAL_CACHE_ADAPTER_REVISION`` (everything else).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.request_cache.global_keys import (
    GlobalCacheKeyResult,
    build_global_cache_key,
)
from aigateway.plugins.openai_provider import global_cache as global_cache_module
from aigateway.plugins.openai_provider.global_cache import (
    GLOBAL_CACHE_ADAPTER_REVISION,
    gateway_dispatch_controls,
    project_global_cache_request,
)
from aigateway.plugins.openai_provider.parameters import openai_chat_parameter_rules
from aigateway.plugins.openai_provider.plugin import PLUGIN
from aigateway.plugins.openai_provider.settings import (
    OFFICIAL_API_BASE,
    OpenAIPluginSettings,
    is_route_valid_model_id,
)

# Bound to the original private name so the relocated hook test below reads unchanged.
from .ambient_state import safe_runtime as _safe_runtime

# A model the deployment seeds, and one that is route-valid but deliberately NOT in
# ``default_models`` — the whole point of OME-884 is that these two behave identically
# for cache purposes. The catalog publishes; it does not admit.
_SEEDED = "openai/gpt-5.6-sol"
_UNLISTED = "openai/gpt-4o-2024-11-20"

_MALFORMED_OR_FOREIGN = [
    "openai/",
    "openai/gpt/5",
    "openai/gpt 5",
    "openai/gpt-5?variant=x",
    "openai/https://example.invalid",
    "openai/-leading-dash",
    "openai/gpt-五",
    f"openai/{'x' * 129}",
    "openrouter/openai/gpt-4o",
    "codex/gpt-5",
    "gpt-4o",
    "",
]


def _body(model: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _key(body: dict[str, Any]) -> GlobalCacheKeyResult:
    built = build_global_cache_key(
        provider="openai",
        body=body,
        rules=openai_chat_parameter_rules(model=str(body.get("model")), auth_type=None),
        projection=project_global_cache_request,
        provider_auth_modes=("api_key",),
    )
    assert isinstance(built, GlobalCacheKeyResult), built
    return built


# --- the shared model-ID predicate -------------------------------------------


def test_the_shared_predicate_accepts_exactly_what_settings_validation_accepts() -> None:
    """ONE grammar, four readers (settings, preparation, projection, parameter rules).

    INVARIANT: OME-884 does not widen OME-864's bounded ASCII grammar. It only stops
    the grammar's verdict from being second-guessed by catalog membership.
    """
    for model in (*OpenAIPluginSettings().default_models, _UNLISTED, "openai/o3"):
        assert is_route_valid_model_id(model) is True, model
        # The settings validator is the other reader; the two may never disagree.
        assert OpenAIPluginSettings(default_models=[model]).default_models == [model]

    for model in _MALFORMED_OR_FOREIGN:
        assert is_route_valid_model_id(model) is False, model
        with pytest.raises(ValidationError):
            OpenAIPluginSettings(default_models=[model])


def test_the_predicate_is_total_for_a_non_string_model() -> None:
    # The cache stage hands the projection whatever the caller sent; a body whose
    # ``model`` is a number or absent must be a bypass, never a TypeError.
    for value in (None, 7, ["openai/gpt-4o"], {"model": "openai/gpt-4o"}, b"openai/gpt-4o"):
        assert is_route_valid_model_id(value) is False, value


# --- the projection ------------------------------------------------------------


def test_the_projection_returns_the_closed_member_set_the_core_requires() -> None:
    # ``global_eligibility._projected`` bypasses on an unrecognized member set, so an
    # extra or missing key here would silently un-cache the whole provider.
    projected = project_global_cache_request(_body(_SEEDED))

    assert isinstance(projected, dict)
    assert set(projected) == {"resolved_model", "provider_adapter_revision", "prepared"}
    assert projected["provider_adapter_revision"] == GLOBAL_CACHE_ADAPTER_REVISION


def test_the_resolved_model_is_the_upstream_id_the_wire_actually_carries() -> None:
    # LiteLLM strips its ``openai/`` provider prefix exactly once at the wire — pinned
    # by ``test_openai_dispatch``'s MockTransport payload assertion — so the upstream
    # remainder is what OpenAI resolves. The gateway-prefixed string is still keyed
    # separately as ``requested_model`` by the core.
    projected = project_global_cache_request(_body(_SEEDED))

    assert isinstance(projected, dict)
    assert projected["resolved_model"] == "gpt-5.6-sol"


def test_the_projection_describes_every_output_affecting_constant_dispatch_adds() -> None:
    """The whole JSON-safe half of the adapter contract, spelled out.

    INVARIANT: each of these is a value the gateway adds WITHOUT the caller asking, and
    each of them changes what OpenAI returns or how the answer is produced. A constant
    the boundary adds but the key cannot see is a wrong-hit waiting for the day it
    changes.
    """
    projected = project_global_cache_request(_body(_SEEDED))

    assert isinstance(projected, dict)
    assert projected["prepared"] == {
        "api_base": OFFICIAL_API_BASE,
        "caching": False,
        "cache": {"no-cache": True, "no-store": True},
        "num_retries": 0,
        "max_retries": 0,
        "_skip_responses_api_bridge": True,
    }
    # ONE table, two readers: the projection and ``chat_completion``. Sharing it is what
    # makes "the projection describes what dispatch sends" true by construction rather
    # than by two lists a maintainer must remember to edit together.
    assert projected["prepared"] == gateway_dispatch_controls()


def test_an_unlisted_route_valid_model_projects_exactly_like_a_seeded_one() -> None:
    """The catalog publishes; it does not admit (owner-approved MVP semantics).

    ``default_models`` is the bootstrap ``/v1/models`` catalog. A model absent from it
    must project — and therefore cache — identically apart from its own identity.
    """
    assert _UNLISTED not in OpenAIPluginSettings().default_models

    seeded = project_global_cache_request(_body(_SEEDED))
    unlisted = project_global_cache_request(_body(_UNLISTED))

    assert isinstance(seeded, dict) and isinstance(unlisted, dict)
    assert seeded["resolved_model"] != unlisted["resolved_model"]
    assert seeded["provider_adapter_revision"] == unlisted["provider_adapter_revision"]
    assert seeded["prepared"] == unlisted["prepared"]


@pytest.mark.parametrize("model", _MALFORMED_OR_FOREIGN)
def test_a_malformed_or_foreign_model_id_bypasses_rather_than_raising(model: str) -> None:
    # INVARIANT: a projection may never fail a request, only decline to key it. A
    # malformed id must therefore reach the local invalid-model path with NO cache read
    # and NO cache write, which a bypass is exactly what delivers.
    projected = project_global_cache_request(_body(model))

    assert projected == CacheBypass(reason=PROJECTION_BYPASS_REASON)


def test_a_body_without_a_model_at_all_bypasses() -> None:
    assert project_global_cache_request({"messages": []}) == CacheBypass(
        reason=PROJECTION_BYPASS_REASON
    )


def test_the_projection_is_deterministic_and_never_mutates_the_body() -> None:
    body = _body(_SEEDED, max_tokens=7, system="be terse")
    snapshot = copy.deepcopy(body)

    first = project_global_cache_request(body)
    second = project_global_cache_request(body)

    assert first == second
    assert body == snapshot


def test_the_projection_hands_back_fresh_containers_every_call() -> None:
    # The core hashes ``prepared`` whole and does not copy it. Sharing one mutable dict
    # across requests would let a later reader of the returned mapping alter the key
    # material of every subsequent request in the process.
    first = project_global_cache_request(_body(_SEEDED))
    second = project_global_cache_request(_body(_SEEDED))

    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["prepared"] is not second["prepared"]
    assert first["prepared"]["cache"] is not second["prepared"]["cache"]


# --- what the projection buys: real keys --------------------------------------


def test_prepared_is_json_safe_and_a_key_is_actually_built() -> None:
    """The projection is only worth something if the key builder accepts it.

    ``_require_json_safe`` refuses an ``Omit()`` sentinel, an SDK client, a non-string
    object key or a non-finite number — which is exactly why the transport guarantees
    that cannot be normalized live in the adapter revision instead of in ``prepared``.
    """
    built = _key(_body(_SEEDED))

    assert built.provider == "openai"
    assert built.model == _SEEDED
    assert len(built.key_hash) == 64


def test_an_unlisted_model_is_keyable_and_never_collides_with_a_seeded_one() -> None:
    assert _key(_body(_UNLISTED)).key_hash != _key(_body(_SEEDED)).key_hash


def test_different_messages_never_collide() -> None:
    other = _body(_SEEDED)
    other["messages"] = [{"role": "user", "content": "how many primes below two hundred?"}]

    assert _key(other).key_hash != _key(_body(_SEEDED)).key_hash


def test_an_absent_top_level_system_is_distinguishable_from_a_present_one() -> None:
    # Prompt material is hashed verbatim and "absent" is an unforgeable marker, so a
    # stored system prompt that later disappears cannot replay the answer it shaped.
    with_system = _key(_body(_SEEDED, system="be terse"))
    without_system = _key(_body(_SEEDED))
    empty_system = _key(_body(_SEEDED, system=""))

    assert len({with_system.key_hash, without_system.key_hash, empty_system.key_hash}) == 3


def test_bumping_the_adapter_revision_abandons_every_stored_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revision is INSIDE the hashed material — that is what makes a bump safe.

    INVARIANT: rows have no expiry and survive deployments, so a change to what this
    boundary sends for an unchanged request MUST be accompanied by a bump. This proves
    a bump actually abandons the generation rather than re-serving it.
    """
    before = _key(_body(_SEEDED))
    monkeypatch.setattr(
        global_cache_module, "GLOBAL_CACHE_ADAPTER_REVISION", f"{GLOBAL_CACHE_ADAPTER_REVISION}-x"
    )

    assert _key(_body(_SEEDED)).key_hash != before.key_hash


def test_a_malformed_model_yields_no_key_at_all() -> None:
    built = build_global_cache_key(
        provider="openai",
        body=_body("openai/gpt 5"),
        rules=openai_chat_parameter_rules(model="openai/gpt 5", auth_type=None),
        projection=project_global_cache_request,
        provider_auth_modes=("api_key",),
    )

    assert built == CacheBypass(reason=PROJECTION_BYPASS_REASON)


# --- the catalog is not an allowlist for readiness either ----------------------


def test_a_route_valid_validation_model_need_not_be_in_the_bootstrap_catalog() -> None:
    # OME-864 required membership; OME-884 removes that coupling in settings so an
    # operator can probe readiness with a model they do not publish.
    settings = OpenAIPluginSettings(default_models=[_SEEDED], validation_model="openai/gpt-5-nano")

    assert settings.validation_model == "openai/gpt-5-nano"
    assert settings.validation_model not in settings.default_models


def test_a_malformed_validation_model_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        OpenAIPluginSettings(default_models=[_SEEDED], validation_model="openai/gpt 5")
    with pytest.raises(ValidationError):
        OpenAIPluginSettings(default_models=[_SEEDED], validation_model="openrouter/openai/gpt-5")


# --- the plugin's own hooks ----------------------------------------------------


def test_the_plugin_exposes_the_module_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    _safe_runtime(monkeypatch)
    body = _body(_SEEDED)

    assert PLUGIN.global_cache_projection(body) == project_global_cache_request(body)


def test_a_cache_hit_certifies_no_historical_accounting_evidence() -> None:
    """OME-884: an explicit ``None``, not a missing attribute.

    ``attach_hit_metadata`` reaches the mapper through ``getattr`` inside a ``try``, so
    NOT implementing the hook logs "cache-reference mapper failed" on every hit — an
    operator-visible warning describing a failure that never happened. Direct OpenAI has
    no accounting strategy at all, so the truthful answer is "no evidence", quietly.
    """
    assert (
        PLUGIN.cache_reference_from_cached_response(
            {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
        )
        is None
    )
