"""OME-1537 — the input-modality vocabulary every ``/v1/models`` row reports.

FEATURE: model input modalities. A row says which inputs the model takes —
``text``, ``image``, ``pdf`` — so the engine can refuse a blind model before it
spends money on a request the model cannot read.

INVARIANT: the vocabulary is CLOSED and core-owned. A provider maps its own
catalogue words onto it (OpenRouter's ``file`` -> ``pdf``, Ollama's ``vision`` ->
``image``) inside its plugin; core only filters, so an off-vocabulary value can
never be published.
INVARIANT: unknown is ``("text",)``. Unknown NEVER means vision — every failure,
fallback and missing piece of evidence collapses to text-only.

AIDEV-NOTE: this module is a leaf (imports nothing from the gateway), so the plugin
contract, the row composer and every plugin can depend on it without a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

type InputModality = Literal["text", "image", "pdf"]

# INVARIANT: canonical order of the published list; a row is always a prefix-free,
# duplicate-free subsequence of this tuple that starts with "text".
INPUT_MODALITY_ORDER: tuple[InputModality, ...] = ("text", "image", "pdf")
TEXT_ONLY: tuple[InputModality, ...] = ("text",)
TEXT_IMAGE: tuple[InputModality, ...] = ("text", "image")
TEXT_IMAGE_PDF: tuple[InputModality, ...] = ("text", "image", "pdf")


def normalize_input_modalities(values: object) -> tuple[InputModality, ...]:
    """Project any claimed modalities onto the closed vocabulary, text first.

    WHY ``text`` is forced: every model on ``/v1/models`` is a chat model, so it
    takes text; a catalogue row that lists only ``image`` is describing its extras.
    WHY a bare ``str`` is refused: iterating ``"image"`` yields its characters, which
    would silently publish text-only for a model a plugin meant to mark as vision —
    treat the malformed claim as unknown instead.
    """
    if values is None or isinstance(values, str | bytes) or not isinstance(values, Iterable):
        return TEXT_ONLY
    claimed = {value for value in values if isinstance(value, str)}
    claimed.add("text")
    return tuple(modality for modality in INPUT_MODALITY_ORDER if modality in claimed)


def declared_family_modalities(
    model: str, table: Sequence[tuple[str, tuple[InputModality, ...]]]
) -> tuple[InputModality, ...]:
    """A provider's DECLARED modalities for ``model``: first matching family prefix wins.

    For providers whose catalogue publishes no modality field, the plugin declares a
    reviewed per-family table. A model outside every declared family is unknown and
    therefore text-only — a new family is never assumed to see.
    """
    for prefix, modalities in table:
        if prefix and model.startswith(prefix):
            return modalities
    return TEXT_ONLY
