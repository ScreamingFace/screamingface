"""MI-27 (contracts C1.6): the public surface has the names of sf.InferenceClient.

FEATURE: SDK model inference, unit U7.
"""

from __future__ import annotations

import json
from pathlib import Path

import screamingface as sf
from screamingface import chat_completion, inference
from screamingface import warnings as sf_warnings

_SNAPSHOT = Path(__file__).resolve().parent / "public_surface_snapshot.json"

NEW_NAMES = (
    "InferenceClient",
    "InferenceEndpoint",
    "ChatCompletion",
    "ChatChoice",
    "ChatMessage",
    "ChatToolCall",
    "ChatFunctionCall",
    "ChatUsage",
    "ChatCompletionChunk",
    "ChatChunkChoice",
    "ChatDelta",
    "ChatDeltaToolCall",
    "ChatStream",
    "AsyncChatStream",
    "InferenceInfo",
    "FinalStep",
    "IgnoredParameterWarning",
)


def test_public_surface_has_the_new_names() -> None:
    assert len(set(NEW_NAMES)) == 17
    for name in NEW_NAMES:
        assert name in sf.__all__

    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["screamingface"]
    for name in NEW_NAMES:
        assert name in snapshot["__all__"]
        assert snapshot["exports"][name]["kind"] == "class"


def test_the_top_level_names_are_the_module_objects() -> None:
    assert sf.InferenceClient is inference.InferenceClient
    assert sf.InferenceEndpoint is inference.InferenceEndpoint
    assert sf.IgnoredParameterWarning is sf_warnings.IgnoredParameterWarning

    chat_names = [name for name in NEW_NAMES if hasattr(chat_completion, name)]
    assert len(chat_names) == 14
    for name in chat_names:
        assert getattr(sf, name) is getattr(chat_completion, name)


def test_the_namespace_classes_and_old_names_are_not_top_level() -> None:
    for name in ("Chat", "Completions", "ModelInference"):
        assert name not in sf.__all__
        assert not hasattr(sf, name)
