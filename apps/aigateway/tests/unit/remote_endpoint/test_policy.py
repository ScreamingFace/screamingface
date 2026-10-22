"""The core endpoint-access port, its default and the configured-grant adapter.

# FEATURE: hosted BYOM Unit 0 — access to a configured endpoint is a policy decision made before any
# credential use or upstream I/O; bundled providers keep today's behavior through the default.
# INVARIANT: a disabled endpoint or an account outside its grant is denied for every operation; an
# app without an installed policy is a wiring bug that fails, never a silent permit.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from aigateway.core.endpoint_access import PERMIT_ALL, EndpointOperation, accessible_plugin
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.policy import RemoteEndpointAccess

from .fixtures import ACCOUNT_A, ACCOUNT_B, ENDPOINT_A, ENDPOINT_B, two_endpoint_document

_OPERATIONS = list(EndpointOperation)


def _policy(**kwargs: Any) -> RemoteEndpointAccess:
    config = parse_remote_endpoint_config(two_endpoint_document(**kwargs))
    return RemoteEndpointAccess(config.grants)


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_the_default_policy_permits_every_provider(operation: EndpointOperation) -> None:
    assert PERMIT_ALL.permits(operation, account_id=ACCOUNT_B, provider="anthropic")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_granted_accounts_are_permitted_and_others_are_not(operation: EndpointOperation) -> None:
    policy = _policy()

    allowed = {
        (account, provider)
        for account in (ACCOUNT_A, ACCOUNT_B)
        for provider in (ENDPOINT_A, ENDPOINT_B)
        if policy.permits(operation, account_id=account, provider=provider)
    }

    assert allowed == {(ACCOUNT_A, ENDPOINT_A), (ACCOUNT_B, ENDPOINT_A), (ACCOUNT_A, ENDPOINT_B)}


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_a_disabled_endpoint_is_denied_even_to_granted_accounts(
    operation: EndpointOperation,
) -> None:
    policy = _policy(a_enabled=False)

    assert not policy.permits(operation, account_id=ACCOUNT_A, provider=ENDPOINT_A)
    assert policy.permits(operation, account_id=ACCOUNT_A, provider=ENDPOINT_B)


def test_providers_outside_the_config_keep_the_default_permit() -> None:
    policy = _policy()

    assert policy.permits(EndpointOperation.INVOKE, account_id=ACCOUNT_B, provider="openai")


class _Plugin:
    def __init__(self, provider: str) -> None:
        self.custom_llm_provider = provider


def _app(policy: object | None) -> SimpleNamespace:
    registry = ProviderRegistry()
    registry.register(cast(Any, _Plugin(ENDPOINT_A)))
    registry.register(cast(Any, _Plugin("openai")))
    state = SimpleNamespace(providers=registry)
    if policy is not None:
        state.endpoint_access = policy
    return SimpleNamespace(state=state)


def test_accessible_plugin_returns_the_registered_plugin_when_permitted() -> None:
    app = _app(_policy())

    plugin = accessible_plugin(
        app, ENDPOINT_A, account_id=ACCOUNT_B, operation=EndpointOperation.ATTACH
    )

    assert plugin is app.state.providers.get(ENDPOINT_A)


def test_accessible_plugin_hides_a_denied_provider_like_an_unknown_one() -> None:
    app = _app(_policy(a_accounts=(ACCOUNT_A,)))

    denied = accessible_plugin(
        app, ENDPOINT_A, account_id=ACCOUNT_B, operation=EndpointOperation.INVOKE
    )
    unknown = accessible_plugin(
        app, "absent", account_id=ACCOUNT_B, operation=EndpointOperation.INVOKE
    )

    assert denied is None
    assert unknown is None


def test_an_app_without_an_installed_policy_fails_instead_of_permitting() -> None:
    with pytest.raises(AttributeError):
        accessible_plugin(
            _app(None), "openai", account_id=ACCOUNT_A, operation=EndpointOperation.VALIDATE
        )
