"""OpenRouter plugin settings (OME-428 Phase 2, plan D2/D8).

Pins: disabled-by-default, env overrides via AIGW_OPENROUTER_*, the three URL4
seed gateway IDs, and the D8 upstream model-ID syntax validator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.plugins.openrouter_provider.settings import (
    GATEWAY_MODEL_PREFIX,
    OpenRouterPluginSettings,
    is_online_variant,
    is_valid_upstream_model_id,
)

# Independent protocol pin: this is the single source in the test suite that fails when the
# canonical benchmark seed set changes. Dispatch tests consume the configured defaults so every
# newly pinned seed is exercised without copying this list again.
_SEEDS = [
    "openrouter/anthropic/claude-fable-5",
    "openrouter/anthropic/claude-haiku-4.5",
    "openrouter/openai/gpt-5.5",
    # The HealthBench worst-30% judge (url4-cloud healthbench/definition.py pins it).
    "openrouter/openai/gpt-5.4",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3.1-pro-preview",
    # The remaining DRACO / IFEval small-model candidate lineup.
    "openrouter/google/gemini-3-flash-preview",
    "openrouter/moonshotai/kimi-k2.6",
    "openrouter/moonshotai/kimi-k3",
    "openrouter/deepseek/deepseek-v4-pro",
    "openrouter/qwen/qwen3.6-plus",
    # OME-816: frontier + budget lineup from the Aug-2026 catalogs (OpenRouter 50 / OpenAI 15 /
    # Anthropic-on-OpenRouter). Each was present in the live openrouter.ai/api/v1/models catalog
    # on 2026-08-13; re-check at release. `:variant` slugs (:batch/:free) are aigateway-only —
    # url4.toml cannot route a colon (OME-819).
    "openrouter/anthropic/claude-opus-5",
    "openrouter/x-ai/grok-4.6",
    "openrouter/openai/gpt-5.6-sol",
    "openrouter/qwen/qwen3.8-max",
    "openrouter/openai/gpt-5.6-terra",
    "openrouter/x-ai/grok-4.5",
    "openrouter/anthropic/claude-sonnet-5",
    "openrouter/deepseek/deepseek-v4-pro-0813",
    "openrouter/qwen/qwen3.8-2.4t-a95b",
    "openrouter/nvidia/nemotron-3.5-lightning",
    "openrouter/upstage/solar-pro4",
    "openrouter/meta/muse-glimmer-30b",
    "openrouter/meta/muse-spark-1.2",
    "openrouter/sakana/sakana-namazu",
    "openrouter/qwen/qwen3.7-flash",
    "openrouter/deepseek/deepseek-v4-flash-0731",
    "openrouter/tencent/hy3",
    "openrouter/openai/gpt-5.6-luna",
    "openrouter/z-ai/glm-5.2",
    "openrouter/xiaomi/mimo-v2.5",
    "openrouter/google/gemini-3.6-flash",
    "openrouter/nvidia/nemotron-3-ultra-550b-a55b",
    "openrouter/minimax/minimax-m3",
    "openrouter/meituan/longcat-2.0",
    "openrouter/thinkingmachines/inkling",
    "openrouter/openai/gpt-5.6-sol-pro",
    "openrouter/openai/gpt-5.6-luna-pro",
    "openrouter/anthropic/claude-opus-5-fast",
    "openrouter/openrouter/auto-beta",
    "openrouter/openrouter/fusion",
    "openrouter/sakana/fugu-ultra",
    "openrouter/inclusionai/ling-3.0-flash",
    "openrouter/nex-agi/nex-n2-mini",
    "openrouter/liquid/lfm-2.5-2.6b:free",
    "openrouter/thinkingmachines/inkling-small",
    "openrouter/google/gemini-3.5-flash-lite",
    "openrouter/mistralai/ministral-14b-2512",
    "openrouter/google/gemini-3.5-flash",
    "openrouter/mistralai/mistral-large-2512",
    "openrouter/mistralai/mistral-medium-3-5",
    "openrouter/meta/muse-spark-1.1",
    "openrouter/aion-labs/aion-3.0",
    "openrouter/aion-labs/aion-3.0-mini",
    "openrouter/openai/gpt-5.6-sol:batch",
    "openrouter/openai/gpt-5.6-terra-pro",
    "openrouter/openai/gpt-5.2",
    "openrouter/openai/gpt-5.2-pro",
    "openrouter/openai/gpt-5",
    "openrouter/openai/gpt-5-mini",
    "openrouter/openai/gpt-4.1-mini",
    "openrouter/openai/gpt-oss-120b",
    "openrouter/anthropic/claude-opus-5:batch",
    "openrouter/anthropic/claude-sonnet-5:batch",
    "openrouter/anthropic/claude-fable-5:batch",
    "openrouter/anthropic/claude-opus-4.6",
    "openrouter/anthropic/claude-opus-4.5",
    "openrouter/anthropic/claude-sonnet-4.6",
    "openrouter/anthropic/claude-sonnet-4.5",
    # OME-856: open-weight notebook lineup members OME-816 does not cover.
    "openrouter/qwen/qwen3-coder",
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/mistralai/ministral-3b-2512",
    "openrouter/microsoft/phi-4",
]


def test_enabled_defaults_false() -> None:
    assert OpenRouterPluginSettings().enabled is False


def test_default_models_are_exactly_the_declared_seeds() -> None:
    assert OpenRouterPluginSettings().default_models == _SEEDS


def test_every_declared_seed_is_gateway_shaped() -> None:
    # INVARIANT: every seed is a well-formed gateway id `openrouter/<author>/<model>[:variant]`.
    # The construction validator already rejects a malformed one; pin it independently so a bad
    # paste is caught here too, not only inside a user's expression at dispatch.
    for slug in _SEEDS:
        assert slug.startswith(GATEWAY_MODEL_PREFIX), slug
        assert is_valid_upstream_model_id(slug[len(GATEWAY_MODEL_PREFIX) :]), slug


def test_no_declared_seed_is_an_online_variant() -> None:
    # INVARIANT: web search is a provider-neutral Gateway parameter, and OpenRouter's `:online`
    # suffix is a second route around it that `prepare_chat_body` refuses at dispatch — so a
    # `:online` seed would resolve to nothing. None may be seeded.
    assert [s for s in _SEEDS if is_online_variant(s)] == []


def test_enabled_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_OPENROUTER_ENABLED", "true")
    assert OpenRouterPluginSettings().enabled is True


def test_default_models_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AIGW_OPENROUTER_DEFAULT_MODELS",
        '["openrouter/mistralai/mistral-large-3"]',
    )
    assert OpenRouterPluginSettings().default_models == ["openrouter/mistralai/mistral-large-3"]


def test_env_override_with_malformed_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_OPENROUTER_DEFAULT_MODELS", '["openrouter/justoneword"]')
    with pytest.raises(ValidationError):
        OpenRouterPluginSettings()


def test_models_without_gateway_prefix_rejected() -> None:
    with pytest.raises(ValidationError):
        OpenRouterPluginSettings(default_models=["anthropic/claude-fable-5"])


@pytest.mark.parametrize(
    "upstream",
    [
        "anthropic/claude-fable-5",
        "openai/gpt-5.5",  # dots in the model base
        "anthropic/claude-opus-4.8",
        "openrouter/free",  # special router is syntactically ordinary (BYOK allows it)
        "openrouter/free:thinking",
        "mistralai/devstral-2.1:free",  # dotted base + variant
        "~legacy-author/some_model",  # ~ alias marker, underscore
        "a/b",  # minimal two segments
        "a1/b2:nitro",
    ],
)
def test_valid_upstream_model_ids(upstream: str) -> None:
    assert is_valid_upstream_model_id(upstream) is True


@pytest.mark.parametrize(
    "upstream",
    [
        "",  # empty
        "anthropic",  # one segment
        "a/b/c",  # extra slash
        "a//b",  # empty middle segment
        "/b",  # empty author
        "a/",  # empty model
        "a/b:",  # empty variant
        "a/b:c:d",  # extra colon
        ":free",  # no base
        "~/model",  # ~ without author characters
        "a b/c",  # whitespace
        "a\tb/c",  # control/tab
        "ä/b",  # Unicode author
        "a/претрен",  # Unicode model
        "a\\b/c",  # backslash
        "a%20b/c",  # percent escape
        "https://evil.example/x",  # scheme
        "a/b?x=1",  # query marker
        "a/b#frag",  # fragment marker
        ".hidden/model",  # author must start alphanumeric
        "a/-model",  # model must start alphanumeric
        "a/b:-variant",  # variant must start alphanumeric
        42,  # non-string
        None,
    ],
)
def test_invalid_upstream_model_ids(upstream: object) -> None:
    assert is_valid_upstream_model_id(upstream) is False


# OME-972 correction pass: `:online` is refused at CONFIG time, not just dispatch.


def test_online_variant_is_rejected_at_configuration() -> None:
    # INVARIANT: what the gateway lists, it must be able to dispatch. A
    # `:online` slug is published by every listing path (explicit operator
    # config survives every healthy snapshot) while `prepare_chat_body` refuses
    # it with `unsupported_model_variant` — so configuring one creates a model
    # that can only ever fail. Fail fast at startup instead.
    with pytest.raises(ValidationError):
        OpenRouterPluginSettings(default_models=["openrouter/openai/gpt-5:online"])


def test_online_variant_is_rejected_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_OPENROUTER_DEFAULT_MODELS", '["openrouter/openai/gpt-5:online"]')
    with pytest.raises(ValidationError):
        OpenRouterPluginSettings()


@pytest.mark.parametrize("slug", ["openrouter/openai/gpt-5:free", "openrouter/a/b:batch"])
def test_other_colon_variants_remain_configurable(slug: str) -> None:
    # Scope guard: only `:online` is refused. Every other variant dispatch
    # already accepts stays explicitly configurable (and listable).
    assert OpenRouterPluginSettings(default_models=[slug]).default_models == [slug]
