"""Shared scaffolding for the OME-305 registry-wide global-cache sweeps.

Not a test module. It builds the REAL provider registry once and exposes the
(plugin, model) pairs the conformance and purity suites both sweep.

INVARIANT (plan §12): no provider name and no model inventory appears here. Every
helper works by SHAPE, so a provider added later is swept automatically and a
provider removed later takes its coverage with it.

EXCEPTION, and it is closed: ``MODEL_LESS_PROVIDERS`` names every such provider. It is
recorded deliberately and is not an inventory — see its own comment. The invariant
exists so coverage follows the registry rather than a hand-maintained list; that one
constant serves the same goal from the other side, by making an environment-dependent
DROP in coverage fail loudly instead of silently. Do not add a second name here for any
other reason.

WHY a private sibling module and not a conftest: a conftest is imported by every
suite in the directory, so scaffolding for two cache suites would become ambient for
all of them. This follows the existing ``tests/unit/_pg_mvcc_store`` precedent —
imported explicitly by exactly the suites that want it.

AIDEV-NOTE: the registry is built ONCE at import and shared. That is deliberate —
``load_plugins`` probes for a local Ollama process, and doing it per suite is slow
noise. It also means no test may mutate ``REGISTRY`` or a plugin it yields; build a
twin instance instead (see ``operator_gate_overrides``).
"""

from __future__ import annotations

from typing import Any

from aigateway.core.chat_parameters import ParameterProjectionRule, normalize_rules
from aigateway.core.loader import load_plugins
from aigateway.core.model_capabilities import canonical_model_id
from aigateway.core.plugin_base import PluginSettings
from aigateway.core.registry import ProviderRegistry


def operator_gate_overrides(settings_cls: type[PluginSettings]) -> dict[str, bool]:
    """The plugin's operator on/off gates, mapped to ON.

    A gate is recognised by SHAPE (a bool setting defaulting to False), never by
    name, so this keeps the sweeps free of provider names.
    """
    return {
        name: True
        for name, field in settings_cls.model_fields.items()
        if field.annotation is bool and field.default is False
    }


def _load_registry() -> ProviderRegistry:
    # A provider that ships disabled contributes no models, so every invariant the
    # sweeps assert would hold vacuously for it. Conformance describes the DECLARED
    # contract, which does not change when an operator flips a switch.
    discovered = ProviderRegistry()
    load_plugins(discovered)
    registry = ProviderRegistry()
    for plugin in discovered.all():
        overrides = operator_gate_overrides(plugin.settings_cls)
        registry.register(type(plugin)(plugin.settings_cls(**overrides)) if overrides else plugin)
    return registry


REGISTRY = _load_registry()


def _iter_models() -> list[tuple[Any, str]]:
    """Every (plugin, canonical provider-prefixed model id) the registry declares.

    WHY the CANONICAL id and not the provider-local name: the route reads the prefix
    to resolve the plugin (``model.split("/", 1)[0]``) but never rewrites
    ``body["model"]``, so the full prefixed string the caller sent is exactly what the
    pre-cache stage hashes and hands to the projection — and it is what
    ``chat_parameter_rules(model=...)`` receives. A provider is entitled to reject an
    unprefixed model, so sweeping the wrong form would prove nothing.
    """
    pairs: list[tuple[Any, str]] = []
    for plugin in REGISTRY.all():
        for entry in plugin.register_models():
            pairs.append(
                (
                    plugin,
                    canonical_model_id(
                        custom_llm_provider=plugin.custom_llm_provider,
                        model_name=entry.model_name,
                    ),
                )
            )
    return pairs


MODELS = _iter_models()

# Every registered plugin, INDEPENDENT of whether it declares any models.
#
# WHY this exists alongside ``MODELS`` (OME-305, lead finding L2): a plugin-level
# invariant — "the projection takes no identity", "it is not a coroutine", "it opens no
# socket" — is a property of the CLASS, so sweeping it through ``MODELS`` both runs it
# redundantly once per model and, far worse, skips any plugin that declares no models.
# One provider discovers its models from a local daemon and returns ``[]`` when nothing
# answers, which is the normal case in CI — so it was registered and never swept, and an
# impure projection added there would have passed.
PROVIDERS: tuple[Any, ...] = tuple(REGISTRY.all())

# INVARIANT: at least this many providers must reach the sweeps. A non-empty assertion
# cannot notice one provider silently dropping out; a floor can.
MINIMUM_PROVIDERS = 7

# The ONE deliberate exception to this module's "no provider name" invariant, and it is
# recorded rather than derived on purpose.
#
# WHY naming it is the lesser evil: this is not an inventory, it is an ENVIRONMENTAL
# fact — this provider enumerates models by probing a local daemon, so it contributes
# zero models unless one is running. Left underived, any other provider that started
# returning no models would silently shrink the sweeps exactly the way this one did.
# Asserting the difference is EXACTLY this set turns that into a failure. If a running
# daemon makes this set empty, the assertion below still holds (it allows a subset).
MODEL_LESS_PROVIDERS: frozenset[str] = frozenset({"local", "ollama"})


def rules(plugin: Any, model: str) -> tuple[ParameterProjectionRule, ...]:
    # auth_type=None is the provider's AUTH-MODE-INDEPENDENT rule set — the same one
    # the pre-cache stage uses, because no auth mode is resolved yet.
    return normalize_rules(plugin.chat_parameter_rules(model=model, auth_type=None))


def body(model: str) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


def models_of(plugin: Any) -> list[str]:
    """Every model id one plugin declares — the identity test, not equality."""
    return [model for owner, model in MODELS if owner is plugin]


def unswept_providers() -> set[str]:
    """Providers that are registered but contribute no (plugin, model) pair."""
    return {plugin.custom_llm_provider for plugin in PROVIDERS} - {
        plugin.custom_llm_provider for plugin, _ in MODELS
    }


def probe_body(plugin: Any) -> dict[str, Any]:
    """A body usable for a plugin-level purity probe even with no declared models.

    WHY a synthetic model id is sound here: the invariants that use this ask whether
    the projection performs I/O, mutates its argument or takes identity. A projection
    that cannot recognise the model must answer ``CacheBypass``, and it must do so
    WITHOUT dialling anything — so an unrecognised id exercises the property just as
    well as a real one, and it is the only way to cover a provider whose model list is
    empty. The id is derived from the plugin, never hardcoded.
    """
    declared = models_of(plugin)
    model = declared[0] if declared else f"{plugin.custom_llm_provider}/unavailable-probe"
    return body(model)
