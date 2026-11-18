"""The reply types of sf.ModelInference: a chat reply, its chunks and the two streams.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.3 and C1.4).
The field names are those of the OpenAI objects (ans:Q2).
AIDEV-NOTE: unit U2 needs only the names, for the typed overloads of ModelInference. Unit U3 adds
the fields of C1.3, to_dict() and the short forms. Unit U5 adds the iteration, the close and the
context manager of the two streams (C1.4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletion:
    """One chat reply, as an OpenAI ``chat.completion`` object (contracts C1.3)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletionChunk:
    """One chunk of a streamed reply, as an OpenAI ``chat.completion.chunk`` (contracts C1.3)."""


class ChatStream:
    """The chunks of one reply, for a sync client and ``stream=True`` (contracts C1.4)."""


class AsyncChatStream:
    """The chunks of one reply, for an AsyncClient and ``stream=True`` (contracts C1.4)."""
