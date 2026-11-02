"""Top-level provider composition: bundled plugins first, then configured endpoint instances.

# FEATURE: hosted BYOM Unit 0 — the app composes its registry from the bundled loader plus a
# validated endpoint config, and installs the matching access policy in the same step.
# INVARIANT: no config changes nothing; an invalid config or an ID collision registers NO instance;
# a TOML file and its in-memory twin build instances that are equal at the factory boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from aigateway.core.endpoint_access import PERMIT_ALL, EndpointOperation
from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.remote_endpoint.definitions import (
    RemoteEndpointConfigError,
    parse_remote_endpoint_config,
)
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin
from aigateway.provider_composition import compose_providers, install_remote_endpoints

from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    ENDPOINT_A,
    ENDPOINT_B,
    document,
    endpoint,
    to_toml,
    two_endpoint_document,
)


def _bundled() -> ProviderRegistry:
    registry = ProviderRegistry()
    load_plugins(registry)
    return registry


def _ids(registry: ProviderRegistry) -> list[str]:
    return [plugin.custom_llm_provider for plugin in registry.all()]


def _config_file(tmp_path: Path, doc: dict[str, Any]) -> Path:
    path = tmp_path / "remote-endpoints.toml"
    path.write_text(to_toml(doc), encoding="utf-8")
    return path


def test_without_a_config_the_registry_and_policy_are_todays() -> None:
    registry = _bundled()
    before = _ids(registry)

    policy = compose_providers(registry, config_path=None)

    assert policy is PERMIT_ALL
    assert _ids(registry) == before
    assert not any(isinstance(p, RemoteEndpointPlugin) for p in registry.all())


def test_configured_endpoints_join_after_the_bundled_plugins(tmp_path: Path) -> None:
    registry = _bundled()
    bundled = _ids(registry)

    policy = compose_providers(
        registry, config_path=_config_file(tmp_path, two_endpoint_document())
    )

    assert _ids(registry) == [*bundled, ENDPOINT_A, ENDPOINT_B]
    assert all(isinstance(registry.get(i), RemoteEndpointPlugin) for i in (ENDPOINT_A, ENDPOINT_B))
    invoke = EndpointOperation.INVOKE
    assert policy.permits(invoke, account_id=ACCOUNT_A, provider=ENDPOINT_B)
    assert not policy.permits(invoke, account_id=ACCOUNT_B, provider=ENDPOINT_B)
    assert policy.permits(invoke, account_id=ACCOUNT_B, provider="openai")


def test_an_explicit_invalid_config_refuses_and_registers_nothing(tmp_path: Path) -> None:
    registry = _bundled()
    bundled = _ids(registry)
    doc = document(endpoint(ENDPOINT_A), endpoint(ENDPOINT_B, base_url="https://old.byom.test"))

    with pytest.raises(RemoteEndpointConfigError):
        compose_providers(registry, config_path=_config_file(tmp_path, doc))

    assert _ids(registry) == bundled


def test_an_explicit_but_unreadable_config_refuses(tmp_path: Path) -> None:
    with pytest.raises(RemoteEndpointConfigError):
        compose_providers(_bundled(), config_path=tmp_path / "absent.toml")


def test_a_collision_with_a_bundled_provider_registers_no_instance() -> None:
    registry = _bundled()

    class _Bundled:
        custom_llm_provider = ENDPOINT_B

    registry.register(cast(Any, _Bundled()))
    config = parse_remote_endpoint_config(two_endpoint_document())

    with pytest.raises(RemoteEndpointConfigError, match="bundled provider"):
        install_remote_endpoints(registry, config)

    assert registry.get(ENDPOINT_A) is None


async def _factory_facts(registry: ProviderRegistry) -> list[tuple[Any, ...]]:
    """What each built instance does: identity, key address, prepared body and the exact send."""
    facts: list[tuple[Any, ...]] = []
    for provider in (ENDPOINT_A, ENDPOINT_B):
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request, sent: list[httpx.Request] = sent) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

        plugin = cast(RemoteEndpointPlugin, registry.get(provider))
        plugin._transport = httpx.MockTransport(handler)
        strategy = plugin.api_key_strategy_for(f"{ACCOUNT_A}:default")
        body = plugin.prepare_chat_body(
            {"model": f"{provider}/{ALIAS}", "messages": [{"role": "user", "content": "x"}]}
        )
        await plugin.chat_completion({**body, "api_key": f"key-{provider}"})
        (request,) = sent
        facts.append(
            (
                plugin.custom_llm_provider,
                plugin.provider_display_name,
                plugin.credential_service_provider(),
                strategy.credential_service(),
                strategy.credential_account(),
                body,
                str(request.url),
                request.headers["authorization"],
                json.loads(request.content),
            )
        )
    return facts


@pytest.mark.asyncio
async def test_file_and_in_memory_inputs_build_equal_instances(tmp_path: Path) -> None:
    doc = two_endpoint_document()
    from_file, from_memory = _bundled(), _bundled()
    compose_providers(from_file, config_path=_config_file(tmp_path, doc))
    install_remote_endpoints(from_memory, parse_remote_endpoint_config(doc))

    file_facts = await _factory_facts(from_file)

    assert file_facts == await _factory_facts(from_memory)
    assert [fact[6] for fact in file_facts] == [
        "https://endpoint-a.byom.test/v1/chat/completions",
        "https://endpoint-b.byom.test/v1/chat/completions",
    ]
