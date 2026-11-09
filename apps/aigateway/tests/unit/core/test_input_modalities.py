"""OME-1537 — the ``input_modalities`` field on every ``/v1/models`` row.

FEATURE: model input modalities — the engine reads which inputs a model takes
(text / image / pdf) and refuses a blind model before spending money.

INVARIANT: unknown is ``["text"]``; unknown NEVER means vision. Every row carries
the field, in canonical order, inside the closed vocabulary — whatever a plugin
returns, core normalizes it before it is published.
"""

from __future__ import annotations

import pytest

from aigateway.core.input_modalities import (
    INPUT_MODALITY_ORDER,
    TEXT_IMAGE,
    TEXT_IMAGE_PDF,
    TEXT_ONLY,
    declared_family_modalities,
    normalize_input_modalities,
)
from aigateway.core.model_capabilities import model_row
from aigateway.core.plugin_base import ModelEntry, PluginSettings, ProviderPluginBase


class _Plugin(ProviderPluginBase[PluginSettings]):
    custom_llm_provider = "faux"

    def register_models(self) -> list[ModelEntry]:
        return []


class _DeclaringPlugin(_Plugin):
    def __init__(self, declared: tuple[str, ...]) -> None:
        super().__init__()
        self._declared = declared

    def model_input_modalities(self, entry: ModelEntry) -> tuple[str, ...]:
        return self._declared


def _entry(name: str = "faux/m", modalities: tuple[str, ...] | None = None) -> ModelEntry:
    return ModelEntry(model_name=name, litellm_params={"model": name}, input_modalities=modalities)


# ---------------------------------------------------------------- vocabulary


def test_vocabulary_is_closed_and_ordered() -> None:
    assert INPUT_MODALITY_ORDER == ("text", "image", "pdf")
    assert TEXT_ONLY == ("text",)
    assert TEXT_IMAGE == ("text", "image")
    assert TEXT_IMAGE_PDF == ("text", "image", "pdf")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ("text",)),
        ((), ("text",)),
        (("pdf", "image", "text"), ("text", "image", "pdf")),
        (("image",), ("text", "image")),  # text is always accepted by a chat model
        (("image", "image", "text"), ("text", "image")),
        (("audio", "video", "file", "IMAGE", 7), ("text",)),  # off-vocabulary dropped
    ],
)
def test_normalize_filters_forces_text_and_orders(raw: object, expected: tuple[str, ...]) -> None:
    assert normalize_input_modalities(raw) == expected


def test_normalize_refuses_a_bare_string_rather_than_iterating_its_characters() -> None:
    # WHY: "image" iterated is i, m, a, g, e — silently text-only. Treat as unknown.
    assert normalize_input_modalities("image") == ("text",)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-haiku-4-5", ("text", "image", "pdf")),
        ("gemini-3-flash", ("text", "image")),
        ("mystery-1", ("text",)),
        ("", ("text",)),
    ],
)
def test_declared_family_table_first_prefix_wins_and_unknown_is_text(
    model: str, expected: tuple[str, ...]
) -> None:
    table = (("claude-", TEXT_IMAGE_PDF), ("gemini-", TEXT_IMAGE))
    assert declared_family_modalities(model, table) == expected


# ---------------------------------------------------------------- the row


def test_every_row_carries_input_modalities_default_text_only() -> None:
    row = model_row(_Plugin(), _entry())
    assert row["input_modalities"] == ["text"]


def test_row_carries_discovered_evidence_from_the_entry() -> None:
    row = model_row(_Plugin(), _entry(modalities=("image", "text")))
    assert row["input_modalities"] == ["text", "image"]


def test_row_normalizes_whatever_a_plugin_declares() -> None:
    row = model_row(_DeclaringPlugin(("pdf", "audio", "image")), _entry())
    assert row["input_modalities"] == ["text", "image", "pdf"]


def test_evidence_field_does_not_change_entry_identity() -> None:
    # INVARIANT: the evidence is NOT part of equality — existing comparisons of
    # listing entries keep meaning what they meant.
    assert _entry(modalities=("text", "image")) == _entry()
    assert ModelEntry(model_name="x", litellm_params={}).input_modalities is None
