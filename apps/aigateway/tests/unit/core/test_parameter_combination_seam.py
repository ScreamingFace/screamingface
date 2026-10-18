"""OME-640: the provider-agnostic cross-field validation seam.

FEATURE: one effective parameter contract. A per-field rule cannot express "these
two individually-valid fields cannot be sent together on THIS model under THIS
auth mode", so providers get one bounded seam to say it — and core stays free of
provider names.

INVARIANT: the seam is opt-in. A provider that says nothing keeps dispatching
exactly as before; no field becomes newly refusable because the hook exists.
INVARIANT: the conflict error carries SAFE request paths and a reason string
only — never a raw submitted value, exactly like ``UnsupportedParametersError``.
"""

from __future__ import annotations

import pytest

from aigateway.core.auth_types import AuthMode
from aigateway.core.loader import load_plugins
from aigateway.core.parameter_projection import IncompatibleParametersError
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.registry import ProviderRegistry


def test_the_error_carries_sorted_safe_paths_and_a_reason() -> None:
    exc = IncompatibleParametersError(("reasoning_effort", "max_tokens"), reason="because")

    # Sorted + deduplicated so the caller-facing list is deterministic across runs,
    # the same normalization UnsupportedParametersError applies to its map.
    assert exc.paths == ("max_tokens", "reasoning_effort")
    assert exc.reason == "because"
    assert "max_tokens" in str(exc)
    assert "because" in str(exc)


def test_the_error_deduplicates_repeated_paths() -> None:
    exc = IncompatibleParametersError(("max_tokens", "max_tokens"), reason="r")

    assert exc.paths == ("max_tokens",)


def test_the_default_hook_accepts_everything() -> None:
    # WHY this matters: the seam runs on EVERY chat request for EVERY provider.
    # A default that did anything but return would make the hook a new fail-open
    # or fail-closed surface for six providers that never asked for one.
    class _Plugin(ProviderPluginBase):
        custom_llm_provider = "x"

        def register_models(self) -> list[ModelEntry]:
            return []

    plugin = _Plugin()

    assert (
        plugin.validate_chat_parameter_combination(
            {"reasoning_effort": "high", "max_tokens": 1},
            model="x/anything",
            auth_mode="api_key",
        )
        is None
    )


@pytest.mark.parametrize("auth_mode", ["oauth", "api_key", "none"])
def test_only_providers_with_cross_field_contracts_override_the_seam(
    auth_mode: AuthMode,
) -> None:
    # An Anthropic-only conflict remains legal for every other provider even as
    # OpenRouter and Hugging Face opt in for their separate logprobs dependency.
    registry = ProviderRegistry()
    load_plugins(registry)
    conflicting = {"reasoning_effort": "high", "max_tokens": 1}

    overriding = {
        name
        for name, plugin in registry._plugins.items()
        if type(plugin).validate_chat_parameter_combination
        is not ProviderPluginBase.validate_chat_parameter_combination
    }

    assert overriding == {"anthropic", "huggingface", "openrouter"}
    for name, plugin in registry._plugins.items():
        if name == "anthropic":
            continue
        assert (
            plugin.validate_chat_parameter_combination(
                conflicting, model=f"{name}/some-model", auth_mode=auth_mode
            )
            is None
        )
