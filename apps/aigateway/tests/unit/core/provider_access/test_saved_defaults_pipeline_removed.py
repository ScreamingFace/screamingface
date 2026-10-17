"""The saved-defaults pipeline and the chat shims are gone (OME-1209, Stage E, E2b).

# FEATURE: Stage E plan §3 E2b — Stage C (OME-1323) stopped the chat route from reading or merging
# stored Profile defaults and A2 (OME-1207) moved every route onto the provider-access port, so the
# code that served both had no production caller. Deleting it leaves one credential vocabulary.
# INVARIANT: no module, port operation, target field or plugin hook carries stored request
# defaults into a chat request. The stored `ProfileDefaults` on a Profile document stay (E5's).
# WHY a test of absence: the Stage C suites prove chat ignores stored defaults; this pins that the
# machinery that could merge them cannot be imported back by accident.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect

import pytest

from aigateway.core import provider_access
from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.provider_access import CredentialTarget, ProviderAccess
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin


@pytest.mark.parametrize(
    "module",
    [
        "aigateway.routes.chat_credentials",
        "aigateway.routes.chat_profile_defaults",
        "aigateway.core.provider_access.defaults",
        "aigateway.core.provider_access.profile_defaults",
    ],
)
def test_the_shim_and_defaults_modules_no_longer_import(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


@pytest.mark.parametrize(
    "name", ["RequestDefaults", "apply_defaults", "legacy_target_parts", "target_from_legacy"]
)
def test_the_provider_access_package_exports_no_defaults_surface(name: str) -> None:
    assert not hasattr(provider_access, name)
    assert name not in provider_access.__all__


def test_the_port_has_no_defaults_read() -> None:
    assert not hasattr(ProviderAccess, "defaults_for")


def test_a_credential_target_carries_no_defaults() -> None:
    assert "defaults" not in {field.name for field in dataclasses.fields(CredentialTarget)}


def test_no_plugin_declares_the_profile_default_hook() -> None:
    assert not hasattr(ProviderPluginBase, "should_apply_profile_default")
    assert "should_apply_profile_default" not in vars(AnthropicProviderPlugin)
    assert "should_apply_profile_default" not in inspect.getsource(
        importlib.import_module("aigateway.plugins.anthropic_provider.plugin")
    )
