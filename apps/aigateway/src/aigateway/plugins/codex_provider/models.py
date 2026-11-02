from __future__ import annotations

from aigateway.core.plugin_base import ModelEntry

# WHY these four: the Codex backend's live list (visibility=list) on 2026-10-17. Every earlier
# slug (gpt-5.2 ... gpt-5.5) is refused for every ChatGPT account (OME-1634).
# INVARIANT: this static list is what /v1/models shows every caller — account-specific live
# lists are never merged into it (one account's entitlements must not leak to another).
_MODEL_SLUGS = [
    "gpt-6-astra",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
]

MODELS: list[ModelEntry] = [
    ModelEntry(model_name=f"codex/{slug}", litellm_params={"model": f"codex/{slug}"})
    for slug in _MODEL_SLUGS
]
