"""Configurable settings for the Hugging Face provider plugin (SF-345).

Model seeds are ``list[str]`` (not ``list[ModelEntry]``) so the whole list is
env-overridable as a JSON array via ``AIGW_HUGGINGFACE_DEFAULT_MODELS`` —
pydantic-settings cannot deserialize a frozen ``ModelEntry`` dataclass from an
env var. ``register_models`` turns each slug into a ``ModelEntry``.

Every slug is validated to the router-suffix form ``huggingface/<org>/<model>``
(optionally ``:<provider|policy>``). This rejects the unsafe provider-as-path-segment
form ``huggingface/<provider>/<org>/<model>``, which sends a malformed id to the
unified router and — without the pinned ``api_base`` — triggers an env-keyed
``huggingface.co`` mapping lookup that ignores the per-request token.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from aigateway.core.plugin_base import PluginSettings

# Unified OpenAI-compatible router. Pinning this as api_base short-circuits
# litellm's per-request provider-mapping fetch to huggingface.co.
#
# OME-791: PUBLIC because it is now global-cache KEY MATERIAL. ``global_cache.py`` emits it
# as the projected ``api_base``, so the pure projection must be able to name it without
# importing anything impure — it may not read the ``router_api_base`` FIELD below.
#
# INVARIANT: this constant is the OFFICIAL router; the field is what a deployment may
# override. ``participates_in_global_cache`` declines when they disagree, which is what lets
# the projection emit a constant while the field stays configurable (plan D3).
#
# AIDEV-NOTE: three other spellings of this host exist in the package and are deliberately
# NOT derived from this constant (plan D4): ``api_key_validation._READINESS_URL`` is a
# hardcoded literal precisely so an overridden base cannot redirect a credential probe —
# ``test_huggingface_validation_requires_identity_and_readiness`` pins that — and
# ``discovery.MODELS_URL`` / ``discovery.ALLOWED_ORIGINS`` serve the catalog surface and
# carry no key material. This constant owns the DISPATCH path only.
OFFICIAL_ROUTER_API_BASE = "https://router.huggingface.co/v1"

# OME-791 (B1): the complete Hugging Face partner-provider vocabulary, transcribed from the
# authoritative partner table at https://huggingface.co/docs/inference-providers/index
# (18 partners, read 2026-08-21). Slugs are the doc-route names — the machine-readable form
# that appears in the ``:<suffix>`` position — NOT the human display names, so "Fireworks" is
# ``fireworks-ai``, "OVHcloud AI Endpoints" is ``ovhcloud``, "Z.ai" is ``zai-org``.
#
# INVARIANT: FAIL-CLOSED, and this is the whole point. The suffix position also accepts ROUTING
# POLICIES — the same page documents ``:fastest`` (the unsuffixed default), ``:cheapest`` and
# ``:preferred`` — which name no fixed backend. ``:preferred`` resolves against the REQUESTING
# ACCOUNT's preference order, so a row keyed under it would replay one account's provider to an
# account whose identical request would have gone elsewhere. Since the global key is
# architecturally identity-free, that hazard cannot be keyed around; it can only be declined.
#
# WHY an allowlist and NOT a denylist of policy names: a denylist fails OPEN. The day Hugging
# Face adds another policy keyword, a denylist would silently begin caching it as though it
# named a backend, and nothing in this repository would notice. An unknown suffix must bypass.
#
# AIDEV-NOTE: this admits a suffix to the CACHE, never to DISPATCH. ``_validate_model_slug``
# stays permissive on purpose (B1.4): a policy or unknown suffix is a perfectly valid request
# that must still reach the router. Drift against the live vocabulary is reported by the
# opt-in ``AIGW_LIVE`` test at ``tests/live/test_huggingface_provider_allowlist_drift.py``.
KNOWN_ROUTER_BACKENDS: frozenset[str] = frozenset(
    {
        "baseten",
        "cerebras",
        "cohere",
        "deepinfra",
        "fal-ai",
        "featherless-ai",
        "fireworks-ai",
        "groq",
        "hf-inference",
        "novita",
        "nscale",
        "ovhcloud",
        "publicai",
        "replicate",
        "scaleway",
        "together",
        "wavespeed",
        "zai-org",
    }
)


def _default_model_slugs() -> list[str]:
    """Seed models in ``huggingface/<org>/<model>:<provider>`` router form.

    Single source of truth for the SF model dropdown via ``GET /v1/models``
    (SF-284), so it must NOT be copied SF-side. Verify live provider mappings
    before relying on any seed (opt-in ``AIGW_LIVE`` test).
    """
    return [
        "huggingface/openai/gpt-oss-120b:cerebras",
        "huggingface/Qwen/Qwen3-Coder-480B-A35B-Instruct:novita",
        "huggingface/deepseek-ai/DeepSeek-R1:novita",
        "huggingface/google/gemma-2-2b-it:featherless-ai",
        "huggingface/meta-llama/Llama-3.1-8B-Instruct:nscale",
        # OME-817: text-generation models the unified router serves as chat, each pinned to a
        # live `:provider` backend. Verified against router.huggingface.co/v1/models on
        # 2026-08-13 (re-verify at release); embeddings / GGUF quants / self-host-only weights
        # from the source catalog were dropped because the router does not serve them.
        "huggingface/moonshotai/Kimi-K3:deepinfra",
        "huggingface/Qwen/Qwen3.8-2.4T-A95B:together",
        "huggingface/zai-org/GLM-5.2:deepinfra",
        "huggingface/deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra",
        "huggingface/tencent/Hy3:deepinfra",
        "huggingface/thinkingmachines/Inkling:together",
        "huggingface/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:deepinfra",
        "huggingface/MiniMaxAI/MiniMax-M3:deepinfra",
        "huggingface/meta-models/Muse-Glimmer-30B:together",
        "huggingface/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16:fireworks-ai",
        "huggingface/openai/gpt-oss-20b:deepinfra",
        "huggingface/meta-llama/Llama-4-Scout-17B-16E-Instruct:nscale",
        "huggingface/google/gemma-4-31B-it:deepinfra",
        "huggingface/XiaomiMiMo/MiMo-V2.5:deepinfra",
        "huggingface/microsoft/phi-4:deepinfra",
        "huggingface/thinkingmachines/Inkling-Small:together",
        "huggingface/google/gemma-3-4b-it:deepinfra",
        "huggingface/CohereLabs/c4ai-command-a-03-2025:cohere",
        "huggingface/deepseek-ai/DeepSeek-R1-Distill-Llama-8B:nscale",
    ]


def _validate_model_slug(slug: str) -> str:
    """Enforce the safe router shape ``huggingface/<org>/<model>[:<provider|policy>]``.

    The repo part (before any ``:``) must be exactly ``<org>/<model>`` — one ``/``.
    Rejects the forbidden ``huggingface/<provider>/<org>/<model>`` path-segment form.
    """
    if not slug.startswith("huggingface/"):
        raise ValueError(f"HF model must start with 'huggingface/': {slug!r}")
    body = slug[len("huggingface/") :]
    repo, sep, suffix = body.partition(":")
    org, slash, model = repo.partition("/")
    if not slash or not org or not model or "/" in model:
        raise ValueError(
            f"unsafe/malformed HF model {slug!r}: expected "
            "'huggingface/<org>/<model>[:<provider>]'. The provider-as-path-segment "
            "form 'huggingface/<provider>/<org>/<model>' is forbidden."
        )
    if sep and (not suffix or ":" in suffix or "/" in suffix):
        raise ValueError(
            f"malformed HF model {slug!r}: the ':<provider|policy>' suffix must be a "
            "single non-empty token (e.g. ':novita')."
        )
    return slug


def pinned_router_target(slug: str) -> tuple[str, str] | None:
    """The ``(<org>/<model>, <backend>)`` pair a gateway id pins, or ``None``.

    Lives beside ``_validate_model_slug`` so there is ONE definition of what a
    well-formed HF gateway id is; this adds only the pinned-backend condition.

    INVARIANT (OME-791 B1): a target is returned ONLY for a suffix in
    ``KNOWN_ROUTER_BACKENDS``. Three distinct inputs therefore share the ``None`` answer,
    for one reason — NONE of them names a backend that is fixed for the next call:

    * an UNSUFFIXED id: the router selects a backend per request (equivalently ``:fastest``).
    * a ROUTING POLICY (``:fastest``, ``:cheapest``, ``:preferred``): a selection rule, not a
      backend. ``:preferred`` resolves against the REQUESTING ACCOUNT's preference order, so it
      is identity-dependent — unkeyable under an identity-free global key.
    * an UNKNOWN suffix: unrecognised, therefore unproven. Fail closed.

    Reporting a target for any of those would be a guess dressed as live evidence — and, since
    this predicate also gates the global cache, a guess written into a row that never expires.

    WHY this does NOT narrow dispatch: ``_validate_model_slug`` remains permissive, so every
    syntactically valid id — policies and unknown suffixes included — still reaches the router
    normally. This function narrows only what may be CACHED and what may be reported as
    single-backend evidence.
    """
    try:
        _validate_model_slug(slug)
    except ValueError:
        return None
    repo, sep, backend = slug[len("huggingface/") :].partition(":")
    if not sep or backend not in KNOWN_ROUTER_BACKENDS:
        return None
    return (repo, backend)


class HuggingFacePluginSettings(PluginSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_HUGGINGFACE_",
        extra="ignore",
        populate_by_name=True,
    )

    default_models: list[str] = Field(default_factory=_default_model_slugs)
    router_api_base: str = OFFICIAL_ROUTER_API_BASE
    validation_model: str | None = None

    @field_validator("default_models")
    @classmethod
    def _validate_models(cls, value: list[str]) -> list[str]:
        # Rejects unsafe/malformed entries (defaults AND env overrides) at construction.
        return [_validate_model_slug(slug) for slug in value]
