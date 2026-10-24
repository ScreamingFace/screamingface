"""Image and file input tokens in the caller's usage object (OME-1546, gateway half).

FEATURE: image/file token accounting. Image and PDF input is billed inside ``prompt_tokens``;
this module states how much of it was media, at
``usage.prompt_tokens_details.image_and_file_tokens``.

INVARIANT: the value is a NON-ADDITIVE subset of ``prompt_tokens`` (like ``cached_tokens``).
It never changes a total or a cost.

INVARIANT: unknown is ``None``, never ``0``. A known ``0`` means the provider reported a
per-modality breakdown that contained no image or document tokens.

WHY in core and provider-neutral: the Gemini and Antigravity adapters share the parser, and the
Codex adapter shares the key. Core imports no plugin.

WHY only the gateway-converted adapters (Gemini, Antigravity, Codex) carry the key: for the
LiteLLM pass-through providers (Anthropic, OpenRouter, Ollama, …) the gateway returns the
provider's body intact apart from ``_aigw`` — prior tests pin that, and the hit-shape contract
fixture pins ``_aigw``. There the key is ABSENT, which also means unknown.

AIDEV-NOTE: the engine half (forwarding into ``ai.url4.cost.usage``) is engine-owned and not
done here — see ``docs/spec/2026-10-20-image-token-accounting.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

__all__ = [
    "IMAGE_AND_FILE_KEY",
    "bounded_image_and_file_tokens_from_gemini",
    "image_and_file_tokens_from_gemini",
    "prompt_token_total_from_gemini",
]

IMAGE_AND_FILE_KEY: Final = "image_and_file_tokens"

# WHY IMAGE and DOCUMENT only: the field is "image and file" input. AUDIO and VIDEO are media
# too, but out of this unit's scope; folding them in would make the name lie.
_COUNTED_MODALITIES: Final = frozenset({"IMAGE", "DOCUMENT"})
_MAX_TOKEN_COUNT: Final = 2**53 - 1


def _bounded_count(value: object) -> int | None:
    # WHY `type(...) is int`: bool is an int subclass, and `True` is not a token count.
    if type(value) is not int or not 0 <= value <= _MAX_TOKEN_COUNT:
        return None
    return value


def image_and_file_tokens_from_gemini(usage_metadata: object) -> int | None:
    """IMAGE + DOCUMENT prompt tokens from Gemini ``usageMetadata``, or ``None`` if unknown.

    Reads the documented ``promptTokensDetails: [{modality, tokenCount}]``. An absent,
    non-list or empty breakdown is unknown. ``tokenCount`` absent means ``0`` (proto3 JSON
    omits zero values).

    INVARIANT: one malformed entry makes the WHOLE value unknown — a sum that skipped an
    entry would be a false known number.
    """
    if not isinstance(usage_metadata, Mapping):
        return None
    details = usage_metadata.get("promptTokensDetails")
    if not isinstance(details, list) or not details:
        return None
    total = 0
    for entry in details:
        if not isinstance(entry, Mapping):
            return None
        modality = entry.get("modality")
        if not isinstance(modality, str):
            return None
        count = _bounded_count(entry.get("tokenCount", 0))
        if count is None:
            return None
        if modality.upper() in _COUNTED_MODALITIES:
            total += count
    return total if total <= _MAX_TOKEN_COUNT else None


def prompt_token_total_from_gemini(usage_metadata: object) -> int | None:
    """``usageMetadata.promptTokenCount`` as a bounded non-negative int, or ``None`` if unknown.

    INVARIANT: absent, null, bool, float, string, negative or overflowing totals are unknown.
    AIDEV-NOTE: this validates the total only to bound the image/file detail. The adapters'
    reported ``prompt_tokens`` keeps its pre-existing lenient parsing on purpose — tightening it
    would change a caller-visible contract outside OME-1546 (PR #1481 review).
    """
    if not isinstance(usage_metadata, Mapping):
        return None
    return _bounded_count(usage_metadata.get("promptTokenCount"))


def bounded_image_and_file_tokens_from_gemini(usage_metadata: object) -> int | None:
    """The image/file detail to PUBLISH: known only inside a valid enclosing prompt total.

    INVARIANT: non-additive subset — a known value always satisfies
    ``0 <= image_and_file_tokens <= promptTokenCount``; otherwise ``None``.
    """
    prompt = prompt_token_total_from_gemini(usage_metadata)
    media = image_and_file_tokens_from_gemini(usage_metadata)
    if prompt is None or media is None or media > prompt:
        return None
    return media
