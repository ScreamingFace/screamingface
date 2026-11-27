"""MI-39 (contracts C1.6): the public surface has the chat names, the module sf.chat and no
sf.InferenceClient.

FEATURE: SDK model inference, units U7 and U9.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import screamingface as sf
from screamingface import chat, chat_completion, inference
from screamingface import warnings as sf_warnings
from screamingface.client import AsyncClient, Client
from screamingface.inference import AsyncChat, Chat

_SNAPSHOT = Path(__file__).resolve().parent / "public_surface_snapshot.json"

NEW_NAMES = (
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


def _snapshot() -> dict[str, Any]:
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["screamingface"]


def test_public_surface_has_the_new_names() -> None:
    assert len(set(NEW_NAMES)) == 16
    for name in NEW_NAMES:
        assert name in sf.__all__

    snapshot = _snapshot()
    for name in NEW_NAMES:
        assert name in snapshot["__all__"]
        assert snapshot["exports"][name]["kind"] == "class"


def test_the_module_chat_is_exported() -> None:
    assert "chat" in sf.__all__
    assert sf.chat is chat

    snapshot = _snapshot()
    assert "chat" in snapshot["__all__"]
    assert snapshot["exports"]["chat"] == {"kind": "module", "module": "screamingface.chat"}


def test_inference_client_is_not_a_name() -> None:
    # WHY: this test asserts that the removed name stays absent from every surface.
    assert "InferenceClient" not in sf.__all__
    assert not hasattr(sf, "InferenceClient")
    assert not hasattr(inference, "InferenceClient")

    snapshot = _snapshot()
    assert "InferenceClient" not in snapshot["__all__"]
    assert "InferenceClient" not in snapshot["exports"]


def test_the_top_level_names_are_the_module_objects() -> None:
    assert sf.InferenceEndpoint is inference.InferenceEndpoint
    assert sf.IgnoredParameterWarning is sf_warnings.IgnoredParameterWarning

    chat_names = [name for name in NEW_NAMES if hasattr(chat_completion, name)]
    assert len(chat_names) == 14
    for name in chat_names:
        assert getattr(sf, name) is getattr(chat_completion, name)


def test_the_namespace_classes_and_old_names_are_not_top_level() -> None:
    # WHY: the namespace classes are reached only through client.chat, recipe.chat and sf.chat.
    for name in (
        "Chat",
        "Completions",
        "AsyncChat",
        "AsyncCompletions",
        "RecipeChat",
        "RecipeCompletions",
        "ModelInference",
    ):
        assert name not in sf.__all__
        assert not hasattr(sf, name)


def test_the_snapshot_has_chat_on_each_recipe_class() -> None:
    snapshot = _snapshot()
    recipe_classes = [
        name
        for name, entry in snapshot["exports"].items()
        if entry["kind"] == "class"
        and isinstance(getattr(sf, name), type)
        and issubclass(getattr(sf, name), sf.Recipe)
    ]
    assert {"Recipe", "Model", "Pipeline"} <= set(recipe_classes)
    for name in recipe_classes:
        assert snapshot["exports"][name]["members"]["chat"] == "property", name

    # WHY: a lone step and a bare Url4 are not recipes that can be called, so they have no chat.
    for name in ("Fanout", "Synthesize"):
        assert "chat" not in snapshot["exports"][name]["members"]


def test_each_client_has_chat() -> None:
    # WHY: the snapshot records class members only; client.chat is an instance attribute,
    # as client.models is, so this test checks it at run time.
    with Client(
        engine_url="http://engine.test", scoreboard_url="http://scoreboard.test", save_results=False
    ) as client:
        assert isinstance(client.chat, Chat)


@pytest.mark.asyncio
async def test_each_async_client_has_chat() -> None:
    async with AsyncClient(
        engine_url="http://engine.test", scoreboard_url="http://scoreboard.test", save_results=False
    ) as client:
        assert isinstance(client.chat, AsyncChat)
