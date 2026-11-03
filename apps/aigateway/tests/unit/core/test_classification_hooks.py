"""The two classification hooks every provider plugin inherits.

# FEATURE: hosted BYOM Unit 3 — a provider lists its classifiers and dispatches a classification
# through two base hooks. The base answers "none" and "unsupported", so a plugin that never heard
# of classification keeps working unchanged.
"""

from __future__ import annotations

import pytest

from aigateway.core.loader import load_plugins
from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.registry import ProviderRegistry

HOOKS = ("register_classifiers", "classify")


def _bundled() -> list[ProviderPluginBase]:
    registry = ProviderRegistry()
    load_plugins(registry)
    return registry.all()


BUNDLED = _bundled()


def test_every_bundled_plugin_is_checked() -> None:
    assert len(BUNDLED) >= 9


def test_the_base_class_declares_both_hooks() -> None:
    assert all(callable(getattr(ProviderPluginBase, name, None)) for name in HOOKS)


@pytest.mark.parametrize("plugin", BUNDLED, ids=lambda plugin: plugin.custom_llm_provider)
def test_a_bundled_plugin_lists_no_classifiers(plugin: ProviderPluginBase) -> None:
    assert plugin.register_classifiers() == []
    # INVARIANT: the default comes from the base; no bundled plugin overrides either hook.
    overriding = [
        cls.__qualname__
        for cls in type(plugin).__mro__
        if cls.__module__.startswith("aigateway.plugins.") and set(HOOKS) & vars(cls).keys()
    ]
    assert overriding == []


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin", BUNDLED, ids=lambda plugin: plugin.custom_llm_provider)
async def test_a_bundled_plugin_refuses_a_classification_as_unsupported(
    plugin: ProviderPluginBase,
) -> None:
    body = {"model": f"{plugin.custom_llm_provider}/any", "input": "text", "api_key": "sk-x"}

    with pytest.raises(NotImplementedError):
        await plugin.classify(body)
