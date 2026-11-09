"""No plugin hook is named after the retired Profile model, and no hook name is misspelled.

FEATURE: Stage E of the Profile retirement (E4c) — the surviving plugin hooks carry credential
names, so a provider author meets one vocabulary: Connections and their credentials.

WHY a guard rather than the renames alone: core looks these hooks up duck-typed with a silent
default (`getattr(plugin, name, None)`). A plugin that kept an old name or misspelled a new one,
or a lookup that asks for a name no plugin defines, would not fail; the provider would quietly
lose its chatless, ambient, session or error-marking behaviour.

INVARIANT: no class in a provider plugin's hierarchy defines an old hook name, each plugin
overrides exactly the neutral hooks listed below, every strategy hook takes `credential_name`,
no source module names an old hook, and every hook name core looks up on a plugin exists.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import aigateway
import aigateway.plugins
from aigateway.core.loader import load_plugins
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.registry import ProviderRegistry

OLD_HOOKS = (
    "allows_chatless_profile",
    "profileless_auth_mode",
    "invalidate_profile_session",
    "should_mark_profile_error_on_dispatch_status",
)
NEUTRAL_HOOKS = (
    "allows_chatless_credential",
    "credentialless_auth_mode",
    "invalidate_credential_session",
    "should_mark_credential_error_on_dispatch_status",
)
STRATEGY_HOOKS = ("oauth_strategy_for", "api_key_strategy_for", "credential_strategy_for")

_MARKS_ERRORS = {"should_mark_credential_error_on_dispatch_status"}
# INVARIANT: the neutral hooks each provider plugin overrides. A misspelled override drops out of
# its row, so this table, not the suite, is what notices it; a new plugin adds its row here.
OVERRIDES: dict[str, set[str]] = {
    "AnthropicProviderPlugin": _MARKS_ERRORS,
    "AntigravityProviderPlugin": {"allows_chatless_credential", "invalidate_credential_session"}
    | _MARKS_ERRORS,
    "CodexProviderPlugin": set(),
    "GeminiProviderPlugin": set(NEUTRAL_HOOKS),
    "HuggingFaceProviderPlugin": _MARKS_ERRORS,
    "LocalProviderPlugin": {"allows_chatless_credential"},
    "OllamaProviderPlugin": {"allows_chatless_credential"},
    "OpenAIProviderPlugin": _MARKS_ERRORS,
    "OpenRouterProviderPlugin": _MARKS_ERRORS,
    "RemoteEndpointPlugin": set(),
}
# WHY: optional duck-typed plugin members that `ProviderPluginBase` does not declare. A new
# lookup either names a member of the base class or is added here on purpose.
OPTIONAL_PLUGIN_MEMBERS = {
    "cache_reference_from_cached_response",
    "classify_dispatch_operational_outcome",
    "custom_llm_provider",
    "normalize_chat_usage_accounting",
    "supplement_chat_usage_accounting",
    "usage_accounting_strategy",
}
SRC = Path(aigateway.__file__).parent


def _subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def _plugin_classes() -> list[type]:
    # WHY every module, not `load_plugins`: the loader registers only `*_provider` packages, and
    # a plugin module in any other package under `aigateway.plugins` must be checked too.
    for info in pkgutil.walk_packages(aigateway.plugins.__path__, prefix="aigateway.plugins."):
        importlib.import_module(info.name)
    # INVARIANT: only plugins defined under `aigateway.plugins` seed the set, so it does not
    # depend on which other modules the suite happened to import first.
    classes = {
        cls
        for plugin_class in _subclasses(ProviderPluginBase)
        if plugin_class.__module__.startswith("aigateway.plugins.")
        for cls in plugin_class.__mro__
        if cls.__module__.startswith("aigateway.")
    }
    return sorted(classes, key=lambda cls: f"{cls.__module__}.{cls.__qualname__}")


PLUGIN_CLASSES = _plugin_classes()
PROVIDER_CLASSES = [
    cls
    for cls in PLUGIN_CLASSES
    if issubclass(cls, ProviderPluginBase) and cls is not ProviderPluginBase
]


def _plugin_lookups() -> list[tuple[str, str]]:
    """Every `getattr`/`hasattr` on a plugin object with a literal name, as (name, site)."""
    lookups = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("getattr", "hasattr")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                continue
            target = node.args[0]
            owner = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
            if "plugin" in owner.lower():
                lookups.append((node.args[1].value, f"{path.relative_to(SRC)}:{node.lineno}"))
    return lookups


class _Bare(ProviderPluginBase):
    custom_llm_provider = "bare"

    def register_models(self) -> list[ModelEntry]:
        return []


def test_every_provider_plugin_and_both_base_classes_are_checked() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)
    names = {cls.__name__ for cls in PLUGIN_CLASSES}

    assert {"ProviderPluginBase", "ProviderPluginCore"} <= names
    assert {type(plugin) for plugin in registry.all()} <= set(PLUGIN_CLASSES)
    assert len(registry.all()) >= 9


@pytest.mark.parametrize("cls", PLUGIN_CLASSES, ids=lambda cls: cls.__qualname__)
def test_no_plugin_or_base_class_defines_an_old_hook_name(cls: type) -> None:
    assert [name for name in OLD_HOOKS if name in vars(cls)] == []


def test_every_provider_plugin_has_an_override_row() -> None:
    assert {cls.__qualname__ for cls in PROVIDER_CLASSES} == set(OVERRIDES)


@pytest.mark.parametrize("cls", PROVIDER_CLASSES, ids=lambda cls: cls.__qualname__)
def test_each_plugin_overrides_exactly_its_neutral_hooks(cls: type) -> None:
    assert {name for name in NEUTRAL_HOOKS if name in vars(cls)} == OVERRIDES[cls.__qualname__]


def test_the_base_class_keeps_the_defaults_under_the_neutral_names() -> None:
    plugin = _Bare()

    assert plugin.allows_chatless_credential() is False
    assert plugin.credentialless_auth_mode() is None
    assert plugin.invalidate_credential_session("default") is None
    assert plugin.should_mark_credential_error_on_dispatch_status(401) is False


@pytest.mark.parametrize("cls", PLUGIN_CLASSES, ids=lambda cls: cls.__qualname__)
def test_every_strategy_hook_takes_a_credential_name(cls: type) -> None:
    for hook in STRATEGY_HOOKS:
        if hook not in vars(cls):
            continue
        params = list(inspect.signature(vars(cls)[hook]).parameters)
        assert params[1] == "credential_name", (hook, params)
        assert "profile_name" not in params, (hook, params)


def test_no_source_module_names_an_old_hook() -> None:
    pattern = re.compile(r"\b(?:" + "|".join(OLD_HOOKS) + r")\b")
    hits = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]

    assert hits == []


def test_every_hook_core_looks_up_on_a_plugin_exists() -> None:
    lookups = _plugin_lookups()
    unknown = [
        site
        for name, site in lookups
        if not hasattr(ProviderPluginBase, name) and name not in OPTIONAL_PLUGIN_MEMBERS
    ]

    assert {name for name, _ in lookups} >= set(NEUTRAL_HOOKS)
    assert unknown == []
