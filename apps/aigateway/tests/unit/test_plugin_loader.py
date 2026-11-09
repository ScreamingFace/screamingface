"""Loader auto-discovers provider packages when scanning aigateway.plugins.*."""

from __future__ import annotations

import logging
import sys

from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry


def test_loader_discovers_anthropic_provider() -> None:
    reg = ProviderRegistry()
    load_plugins(reg)
    plugin = reg.get("anthropic")
    assert plugin is not None
    assert plugin.custom_llm_provider == "anthropic"
    models = plugin.register_models()
    names = {m.model_name for m in models}
    assert "claude-sonnet-4-5" in names
    for m in models:
        assert m.litellm_params["model"].startswith("anthropic/")


def test_loader_discovers_codex_provider() -> None:
    reg = ProviderRegistry()
    load_plugins(reg)
    plugin = reg.get("codex")
    assert plugin is not None
    assert plugin.custom_llm_provider == "codex"
    models = plugin.register_models()
    names = {m.model_name for m in models}
    assert "codex/gpt-6-astra" in names
    assert "codex/codex-auto-review" not in names
    for m in models:
        assert m.litellm_params["model"].startswith("codex/")


def test_loader_discovers_antigravity_provider() -> None:
    reg = ProviderRegistry()
    load_plugins(reg)
    plugin = reg.get("antigravity")
    assert plugin is not None
    assert plugin.custom_llm_provider == "antigravity"
    models = plugin.register_models()
    names = {m.model_name for m in models}
    assert "antigravity/gemini-3-flash" in names
    for m in models:
        assert m.litellm_params["model"].startswith("antigravity/")


def test_loader_discovers_huggingface_provider() -> None:
    reg = ProviderRegistry()
    load_plugins(reg)
    plugin = reg.get("huggingface")
    assert plugin is not None
    assert plugin.custom_llm_provider == "huggingface"
    models = plugin.register_models()
    names = {m.model_name for m in models}
    assert "huggingface/deepseek-ai/DeepSeek-R1:novita" in names
    for m in models:
        assert m.litellm_params["model"].startswith("huggingface/")
        assert m.litellm_params["api_base"] == "https://router.huggingface.co/v1"


def test_loader_silently_ignores_non_provider_plugin_packages(caplog) -> None:
    reg = ProviderRegistry()

    with caplog.at_level(logging.WARNING, logger="aigateway.core.loader"):
        load_plugins(reg)

    assert not [record for record in caplog.records if "plugins.taxonomy" in record.getMessage()]


def test_loader_warns_when_a_provider_dependency_is_unavailable(
    tmp_path, monkeypatch, caplog
) -> None:
    package = tmp_path / "test_plugins"
    provider = package / "broken_provider"
    package.mkdir()
    provider.mkdir()
    (package / "__init__.py").write_text("")
    (provider / "__init__.py").write_text("")
    (provider / "plugin.py").write_text("import dependency_that_does_not_exist\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="aigateway.core.loader"):
        load_plugins(ProviderRegistry(), package="test_plugins")

    assert (
        "provider plugin test_plugins.broken_provider has an unavailable dependency" in caplog.text
    )
    for name in tuple(sys.modules):
        if name == "test_plugins" or name.startswith("test_plugins."):
            sys.modules.pop(name)


def test_loader_warns_when_a_provider_package_dependency_is_unavailable(
    tmp_path, monkeypatch, caplog
) -> None:
    package = tmp_path / "test_plugins"
    provider = package / "broken_provider"
    package.mkdir()
    provider.mkdir()
    (package / "__init__.py").write_text("")
    (provider / "__init__.py").write_text("import dependency_that_does_not_exist\n")
    (provider / "plugin.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="aigateway.core.loader"):
        load_plugins(ProviderRegistry(), package="test_plugins")

    assert (
        "provider plugin test_plugins.broken_provider has an unavailable dependency" in caplog.text
    )
    for name in tuple(sys.modules):
        if name == "test_plugins" or name.startswith("test_plugins."):
            sys.modules.pop(name)
