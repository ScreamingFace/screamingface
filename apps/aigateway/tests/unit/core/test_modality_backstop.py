"""The modality backstop's core pieces (OME-1807).

# INVARIANT (owner decision A, 2026-11-02): the gateway refuses a media part only on PUBLISHED
# evidence that the model lacks its modality. `None` evidence is unknown and admits everything.
# The `/v1/models` publication (unknown -> text-only, OME-1537) is unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.content_parts import UnsupportedContentPart, check_input_modalities
from aigateway.core.input_modalities import (
    TEXT_IMAGE_PDF,
    TEXT_ONLY,
    declared_family_evidence,
    declared_family_modalities,
)
from aigateway.core.model_capabilities import routed_model_modality_evidence
from aigateway.core.plugin_base import ModelEntry

_PDF = {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}}
_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_REMOTE = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}


def _messages(*parts: Any) -> list[dict[str, Any]]:
    return [{"role": "user", "content": ["look", *parts]}]


def _check(messages: Any, modalities: Any) -> None:
    check_input_modalities(messages, provider="p", modalities=modalities)


# --- check_input_modalities ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "modalities", "part_type", "missing"),
    [
        (_PDF, ("text", "image"), "file", "pdf"),
        (_PNG, ("text",), "image_url", "image"),
        (_REMOTE, ("text", "pdf"), "image_url", "image"),
    ],
)
def test_a_part_whose_modality_is_not_published_is_refused(
    part: dict[str, Any], modalities: tuple[str, ...], part_type: str, missing: str
) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        _check(_messages(part), modalities)

    assert caught.value.status_code == 422
    assert caught.value.info["code"] == "unsupported_content_part"
    assert caught.value.info["part_type"] == part_type
    assert caught.value.info["reason"] == f"modality_unsupported {missing}"


@pytest.mark.parametrize(
    "messages",
    [
        _messages(_PDF, _PNG),
        [{"role": "user", "content": "plain text"}],
        [{"role": "system", "content": [_PNG]}, {"role": "user", "content": [_PDF]}],
    ],
)
def test_unknown_evidence_admits_everything(messages: Any) -> None:
    _check(messages, None)


def test_published_modalities_admit_their_parts() -> None:
    _check(_messages(_PDF, _PNG), TEXT_IMAGE_PDF)


def test_text_and_foreign_parts_are_never_judged() -> None:
    # Not this check's business: the data:-only guard and adapters own every other part type.
    messages: list[Any] = [
        "not a mapping",
        {"role": "user", "content": "plain"},
        {"role": "user", "content": None},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}, "loose", 3]},
        {"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]},
    ]
    _check(messages, TEXT_ONLY)


def test_off_vocabulary_or_malformed_evidence_is_normalized_not_trusted() -> None:
    # A bare string is a malformed claim (OME-1537) -> text-only, which refuses an image.
    with pytest.raises(UnsupportedContentPart):
        _check(_messages(_PNG), "image")


# --- declared family evidence ----------------------------------------------------------------

_TABLE = (("o3-mini", TEXT_ONLY), ("o3", TEXT_IMAGE_PDF))


def test_declared_family_evidence_distinguishes_unknown_from_declared_text_only() -> None:
    assert declared_family_evidence("o3-mini", _TABLE) == TEXT_ONLY
    assert declared_family_evidence("o3-pro", _TABLE) == TEXT_IMAGE_PDF
    assert declared_family_evidence("gpt-3.5-turbo", _TABLE) is None


def test_declared_family_modalities_publication_is_unchanged() -> None:
    assert declared_family_modalities("gpt-3.5-turbo", _TABLE) == TEXT_ONLY
    assert declared_family_modalities("o3-mini", _TABLE) == TEXT_ONLY
    assert declared_family_modalities("o3", _TABLE) == TEXT_IMAGE_PDF


# --- routed_model_modality_evidence ----------------------------------------------------------


class _Plugin:
    custom_llm_provider = "prov"

    def model_input_modality_evidence(self, entry: ModelEntry) -> tuple[str, ...] | None:
        return entry.input_modalities


class _Catalog:
    def __init__(self, entries: tuple[ModelEntry, ...] | None) -> None:
        self.entries = entries

    def snapshot_entries(self, plugin: Any) -> tuple[ModelEntry, ...] | None:
        return self.entries


def _entry(name: str, modalities: tuple[str, ...] | None) -> ModelEntry:
    return ModelEntry(model_name=name, litellm_params={"model": name}, input_modalities=modalities)


def test_the_snapshot_entry_supplies_the_evidence() -> None:
    catalog = _Catalog((_entry("prov/a", ("text",)), _entry("prov/b", ("text", "image"))))

    evidence = routed_model_modality_evidence(_Plugin(), "prov/b", catalog=catalog, admitted={})

    assert evidence == ("text", "image")


def test_an_unprefixed_snapshot_name_matches_its_canonical_id() -> None:
    catalog = _Catalog((_entry("b", ("text", "image")),))

    evidence = routed_model_modality_evidence(_Plugin(), "prov/b", catalog=catalog, admitted={})

    assert evidence == ("text", "image")


def test_an_admitted_entry_is_used_when_the_snapshot_lacks_the_model() -> None:
    admitted = {"prov/b": _entry("prov/b", ("text", "pdf"))}

    evidence = routed_model_modality_evidence(
        _Plugin(), "prov/b", catalog=_Catalog(None), admitted=admitted
    )

    assert evidence == ("text", "pdf")


def test_an_unlisted_model_is_asked_of_the_plugin_by_name() -> None:
    # No catalog at all (discovery off) and not admitted: the plugin judges the bare id, and an
    # evidence-on-entry provider has none for it -> unknown.
    evidence = routed_model_modality_evidence(_Plugin(), "prov/b", catalog=None, admitted={})

    assert evidence is None


def test_a_plugin_without_the_evidence_port_is_unknown() -> None:
    class _Bare:
        custom_llm_provider = "prov"

    evidence = routed_model_modality_evidence(_Bare(), "prov/b", catalog=None, admitted={})

    assert evidence is None


# --- the plugin port: tri-state evidence, publication unchanged ------------------------------


def _registry_plugins() -> dict[str, Any]:
    from aigateway.core.loader import load_plugins
    from aigateway.core.registry import ProviderRegistry

    registry = ProviderRegistry()
    load_plugins(registry)
    return {plugin.custom_llm_provider: plugin for plugin in registry.all()}


@pytest.mark.parametrize(
    ("model", "evidence"),
    [
        ("anthropic/claude-haiku-4-5", TEXT_IMAGE_PDF),
        ("anthropic/not-a-claude", None),
        ("openai/gpt-4o-mini", TEXT_IMAGE_PDF),
        ("openai/o3-mini", TEXT_ONLY),
        ("openai/gpt-3.5-turbo", None),
        ("gemini-cli/gemini-2.5-flash", TEXT_IMAGE_PDF),
        ("gemini-cli/other", None),
        ("codex/gpt-5", TEXT_IMAGE_PDF),
        ("codex/other", None),
        ("antigravity/gemini-3-pro", TEXT_IMAGE_PDF),
        ("antigravity/claude-sonnet", None),
        ("openrouter/google/gemini-2.5-flash", None),
    ],
)
def test_each_plugin_reports_declared_evidence_or_unknown(
    model: str, evidence: tuple[str, ...] | None
) -> None:
    plugin = _registry_plugins()[model.split("/", 1)[0]]
    entry = ModelEntry(model_name=model, litellm_params={"model": model})

    assert plugin.model_input_modality_evidence(entry) == evidence
    # Publication is unchanged: unknown still publishes text-only on /v1/models (OME-1537).
    assert plugin.model_input_modalities(entry) == (evidence if evidence is not None else TEXT_ONLY)
