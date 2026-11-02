"""The body-only shared-cache projection and the participation gate of a configured endpoint.

# FEATURE: hosted BYOM Unit 1 — chats to a configured target join the shared response cache
# through the existing pure projection contract, as bundled providers do.
# INVARIANT: the projection reads the request body alone. No definition field (origin, request
# path, upstream model), no grant, no key and no `enabled` flag enters key material, so two
# instances that differ only in those project alike.
# INVARIANT: participation needs an enabled endpoint and a declared chat alias of this provider;
# it reads no grant and no key.
"""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest

from aigateway.core.cache_ports import CacheBypass
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.global_cache import GLOBAL_CACHE_ADAPTER_REVISION
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin
from aigateway.provider_composition import install_remote_endpoints

from .conftest import chat_body
from .fixtures import (
    ALIAS,
    ENDPOINT_A,
    ENDPOINT_B,
    chat_target,
    document,
    endpoint,
    two_endpoint_document,
)

MODEL = f"{ENDPOINT_A}/{ALIAS}"
BODY = {**chat_body(ENDPOINT_A), "max_tokens": 5}


def _plugin(*, enabled: bool = True, **overrides: Any) -> RemoteEndpointPlugin:
    definition = parse_remote_endpoint_config(document(endpoint(**overrides))).endpoints[0]
    return RemoteEndpointPlugin(definition, enabled=enabled)


class _Poisoned:
    """Any read raises: stands in for state the projection must never consult."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"global_cache_projection read .{name}")

    def __bool__(self) -> bool:
        raise AssertionError("global_cache_projection read the enabled flag")


# --- projection ---------------------------------------------------------------------------------


def test_a_text_chat_projects_the_requested_model_and_constants() -> None:
    assert _plugin().global_cache_projection(BODY) == {
        "resolved_model": MODEL,
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": {},
    }


def test_instances_that_differ_in_origin_path_and_upstream_model_project_alike() -> None:
    first = _plugin()
    retargeted = _plugin(
        origin="http://192.168.1.20:1234",
        targets=[chat_target(request_path="/v2/chat", upstream_model="other/model")],
    )

    assert retargeted.global_cache_projection(BODY) == first.global_cache_projection(BODY)


def test_the_projection_reads_no_definition_and_no_enabled_flag() -> None:
    plugin = _plugin()
    expected = plugin.global_cache_projection(BODY)
    # cast: substituting a poisoned stand-in is the whole mechanism.
    cast(Any, plugin)._definition = _Poisoned()
    cast(Any, plugin)._enabled = _Poisoned()

    assert plugin.global_cache_projection(BODY) == expected


def test_the_projection_neither_mutates_the_body_nor_shares_its_result() -> None:
    plugin = _plugin()
    body = copy.deepcopy(BODY)

    first = plugin.global_cache_projection(body)
    assert not isinstance(first, CacheBypass)
    first["prepared"]["leaked"] = True

    assert body == BODY
    assert plugin.global_cache_projection(body) == _plugin().global_cache_projection(BODY)


def test_the_projection_reads_no_clock_randomness_filesystem_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    import os
    import random
    import time

    plugin = _plugin()
    expected = plugin.global_cache_projection(BODY)

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("global_cache_projection reached an ambient source")

    with monkeypatch.context() as poison:
        for module, attribute in (
            (time, "time"),
            (time, "monotonic"),
            (random, "random"),
            (builtins, "open"),
        ):
            poison.setattr(module, attribute, _refuse)
        poison.setattr(os, "environ", _Poisoned())
        projected = plugin.global_cache_projection(BODY)

    assert projected == expected


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [{"role": "user", "content": "ping"}]},
        {"model": 42, "messages": [{"role": "user", "content": "ping"}]},
        {"model": MODEL},
        {"model": MODEL, "messages": []},
        {"model": MODEL, "messages": "ping"},
        {"model": MODEL, "messages": [{"role": "tool", "content": "ping"}]},
        {"model": MODEL, "messages": [{"role": "user", "content": "ping", "name": "x"}]},
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
        },
        {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": "data:,"}}],
                }
            ],
        },
    ],
)
def test_a_body_outside_the_text_contract_bypasses_and_never_raises(body: dict[str, Any]) -> None:
    # WHY bypass: the cache is read before `prepare_chat_body`, which then refuses the request.
    assert isinstance(_plugin().global_cache_projection(body), CacheBypass)


# --- participation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "model", "participates"),
    [
        (True, MODEL, True),
        (False, MODEL, False),
        (True, f"{ENDPOINT_A}/model_v9", False),
        (True, f"{ENDPOINT_B}/{ALIAS}", False),
        (True, ALIAS, False),
        (True, None, False),
        (True, 42, False),
    ],
)
def test_participation_needs_an_enabled_endpoint_and_a_declared_alias(
    enabled: bool, model: object, participates: bool
) -> None:
    assert _plugin(enabled=enabled).participates_in_global_cache(model) is participates


def test_composition_hands_each_instance_its_enabled_flag() -> None:
    registry = ProviderRegistry()
    config = parse_remote_endpoint_config(two_endpoint_document(b_enabled=False))

    install_remote_endpoints(registry, config)

    first, second = (registry.get(provider) for provider in (ENDPOINT_A, ENDPOINT_B))
    assert first is not None and second is not None
    assert first.participates_in_global_cache(MODEL) is True
    assert second.participates_in_global_cache(f"{ENDPOINT_B}/{ALIAS}") is False


def test_a_cache_hit_carries_no_usage_reference() -> None:
    # WHY explicit: the hit path asks every provider for one, and this provider has none.
    assert _plugin().cache_reference_from_cached_response({"choices": []}) is None


def test_max_tokens_is_keyed() -> None:
    (rule,) = _plugin().chat_parameter_rules(model=MODEL, auth_type="api_key")

    assert (rule.request_path, rule.cache_behavior) == ("max_tokens", "keyed")
