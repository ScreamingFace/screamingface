"""Configurable settings for the OpenRouter provider plugin (OME-428).

Disabled by default (plan D2): installing the package must not expose models
or accept API keys until an operator sets ``AIGW_OPENROUTER_ENABLED=true``.

Model seeds are ``list[str]`` gateway IDs (``openrouter/<author>/<model>``) so
the whole list is env-overridable as a JSON array via
``AIGW_OPENROUTER_DEFAULT_MODELS`` — pydantic-settings cannot deserialize a
frozen ``ModelEntry`` dataclass from an env var. Each gateway ID loses exactly
one ``openrouter/`` prefix at the LiteLLM wire; the remainder must be a valid
upstream OpenRouter model ID (plan D8).
"""

from __future__ import annotations

import re

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from aigateway.core.plugin_base import PluginSettings

GATEWAY_MODEL_PREFIX = "openrouter/"

# D7: the gateway owns routing — every dispatch goes to the official API base.
# Homed here rather than in ``plugin.py`` so that both the dispatch path and the
# pure global-cache projection can reach it without importing the plugin.
OFFICIAL_API_BASE = "https://openrouter.ai/api/v1"

# D8: ASCII upstream ID `<author>/<model>[:variant]` with exactly two non-empty
# segments; the author may carry a single leading `~` alias marker. The
# character classes reject every forbidden shape by construction: Unicode,
# controls, whitespace, backslashes, percent escapes, URL schemes,
# query/fragment markers, empty segments, extra slashes/colons, empty variants.
_UPSTREAM_MODEL_ID_RE = re.compile(
    r"~?[A-Za-z0-9][A-Za-z0-9._-]*"  # author
    r"/[A-Za-z0-9][A-Za-z0-9._-]*"  # model base (exactly one '/')
    r"(:[A-Za-z0-9][A-Za-z0-9._-]*)?"  # optional single non-empty ':variant'
)


def is_valid_upstream_model_id(value: object) -> bool:
    """True when ``value`` is a syntactically valid upstream OpenRouter model ID.

    Purely syntactic (plan D8): models are bootstrap metadata, not request
    authorization, so valid unlisted IDs pass and no catalog lookup happens.
    """
    return isinstance(value, str) and _UPSTREAM_MODEL_ID_RE.fullmatch(value) is not None


# OME-712: OpenRouter's implicit-search model variant. It is a syntactically VALID
# ``:variant`` (D8 accepts it), so nothing else in this module refuses it — it needs its
# own predicate.
ONLINE_VARIANT_SUFFIX = ":online"


def is_online_variant(model: str) -> bool:
    """True for OpenRouter's implicit web-search model variant.

    ONE predicate for three call sites that must never disagree: ``prepare_chat_body``
    REFUSES such a model (search is a provider-neutral Gateway parameter, and this suffix
    is a second route around it), the global-cache projection BYPASSES it, and
    ``_validate_gateway_slug`` refuses to CONFIGURE one (OME-972). The first two are
    required, because the cache is consulted before dispatch — a guard only on the
    dispatch path would still let a stored entry answer 200 for a refused request.

    Suffix-only, so it answers for a gateway id and its upstream remainder alike:
    ``prepare_chat_body`` holds the former and the projection the latter.
    """
    return model.endswith(ONLINE_VARIANT_SUFFIX)


def _default_model_slugs() -> list[str]:
    """URL4 leaf seeds in gateway form — recommended bootstrap metadata (D8).

    All were present in the live OpenRouter catalog on 2026-08-05; re-check at release. Never
    treat this list as an authorization boundary.

    Validation here is purely SYNTACTIC (`is_valid_upstream_model_id`, D8) — nothing checks a
    slug against the live catalog, so a typo in one of these surfaces as a dispatch failure
    inside a user's expression, not at boot. Re-checking at release is the only guard.
    """
    return [
        "openrouter/anthropic/claude-fable-5",
        "openrouter/anthropic/claude-haiku-4.5",
        "openrouter/openai/gpt-5.5",
        # AIDEV-NOTE: the HealthBench worst-30% judge (healthbench/definition.py JUDGE_MODEL
        # pins it; the official judge is an OpenAI-internal gpt-5.4 snapshot, OpenRouter routes
        # the floating slug). Seeded here for the same reason as the DRACO judge below —
        # a different judge materially changes scores.
        "openrouter/openai/gpt-5.4",
        "openrouter/anthropic/claude-opus-4.8",
        # AIDEV-NOTE: the DRACO benchmark judge. arXiv:2602.11685 §4.2 PINS it, and the
        # benchmarks repo warns that a different judge materially changes the scores — so it is
        # seeded here rather than left to a deployment. `apps/screamingface-engine/url4.toml`
        # declares the matching route; `test_declared_models_match_aigateway.py` fails if the
        # two drift.
        "openrouter/google/gemini-3.1-pro-preview",
        # The remaining DRACO candidate lineup, also used by the Fusion and
        # CorrectiveEnsemble examples. These must be real gateway seeds: merely adding them to
        # a dev environment makes catalog checks pass while execution still fails elsewhere.
        # All were present in the live OpenRouter catalog on 2026-08-05; re-check at release.
        "openrouter/google/gemini-3-flash-preview",
        "openrouter/moonshotai/kimi-k2.6",
        "openrouter/moonshotai/kimi-k3",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/qwen/qwen3.6-plus",
        # OME-816: frontier + budget lineup from the Aug-2026 catalogs (OpenRouter 50 / OpenAI 15
        # / Anthropic-on-OpenRouter). Each was present in the live openrouter.ai/api/v1/models
        # catalog on 2026-08-13; re-check at release (D8 validation is syntactic only). The
        # `:variant` slugs (`:batch`, `:free`) are aigateway-only — url4.toml cannot route a colon.
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
        # OME-856: open-weight notebook lineup members OME-816 does not cover, present in
        # the live OpenRouter catalog on 2026-08-17; re-check at release.
        "openrouter/qwen/qwen3-coder",
        "openrouter/deepseek/deepseek-v4-flash",
        # Lightweight open-weight corrective-loop members (IFEval-fallible by design).
        "openrouter/mistralai/ministral-3b-2512",
        "openrouter/microsoft/phi-4",
    ]


def _validate_gateway_slug(slug: str) -> str:
    """Enforce ``openrouter/<author>/<model>[:variant]`` for configured seeds."""
    if not slug.startswith(GATEWAY_MODEL_PREFIX):
        raise ValueError(f"OpenRouter model must start with {GATEWAY_MODEL_PREFIX!r}: {slug!r}")
    upstream = slug[len(GATEWAY_MODEL_PREFIX) :]
    if not is_valid_upstream_model_id(upstream):
        raise ValueError(
            f"malformed OpenRouter model {slug!r}: expected "
            "'openrouter/<author>/<model>' with an optional single ':variant'"
        )
    # OME-972: refuse at CONFIG time what dispatch will always refuse. Every
    # listing path publishes explicitly configured slugs (they survive a healthy
    # live snapshot by design), while ``prepare_chat_body`` rejects ``:online``
    # with ``unsupported_model_variant`` — web search is a provider-neutral
    # Gateway parameter and this suffix is a second route around it. Configuring
    # one would publish a model whose every chat request fails.
    if is_online_variant(slug):
        raise ValueError(
            f"OpenRouter ':online' model {slug!r} cannot be configured: chat dispatch refuses "
            "the variant (use the provider-neutral web-search parameter instead)"
        )
    return slug


class OpenRouterPluginSettings(PluginSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_OPENROUTER_",
        extra="ignore",
        populate_by_name=True,
    )

    # Net-new per-provider gate (no other provider has one): discovery still
    # registers the plugin, but a disabled plugin contributes no models and
    # returns no credential strategy, so it can neither store keys nor
    # resolve credentials for dispatch (plan D2 — fail closed in the plugin,
    # never a provider branch in the loader/registry).
    enabled: bool = False
    # OME-879: gates POST /v1/models/admit (dynamic admission against the live
    # OpenRouter catalog). Default ON — prod can pin a closed world by setting
    # AIGW_OPENROUTER_DYNAMIC=false without a breaking change.
    dynamic: bool = True
    # OME-972: gates LIVE catalog discovery for the /v1/models LISTING (never
    # dispatch). Default ON — AIGW_OPENROUTER_LIVE_MODELS=false restores the
    # static compiled-seed listing with zero catalog egress.
    live_models: bool = True
    default_models: list[str] = Field(default_factory=_default_model_slugs)
    validation_model: str = "openrouter/openrouter/free"

    @field_validator("default_models")
    @classmethod
    def _validate_models(cls, value: list[str]) -> list[str]:
        # Rejects malformed entries (defaults AND env overrides) at construction.
        return [_validate_gateway_slug(slug) for slug in value]
