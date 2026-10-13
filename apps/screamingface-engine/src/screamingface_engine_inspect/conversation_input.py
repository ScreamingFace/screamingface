"""A Case whose prompt is a fixed conversation, written as one input text (OME-1527, R14).

FEATURE: some exams hand the Candidate a chat the dataset already wrote (user, assistant,
user, …) and ask it for the next turn: healthbench's conversation Cases. That is still ONE
Candidate call, but the Case input can't be one plain prompt. Think of it as a sealed letter:
the conversation travels inside the candidate-input envelope, the one text format the
Engine already reads as chat messages. The connector opens it for a single model, a Fusion
synthesizer reads it as written, and the scorer opens it again to rebuild the chat.

The bytes are the hand-built preparers' (``benchmarks/healthbench/prepare.py`` ``envelope``):
keys ``schema`` then ``messages``, each message ``role`` then ``content``, compact
separators, non-ASCII kept as is. A migrated Benchmark's recorded calls then replay as hits.

Worked example: user "My knee hurts.", assistant "Since when?", user "Two days." →
``{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user","content":"My knee
hurts."},{"role":"assistant","content":"Since when?"},{"role":"user","content":"Two days."}]}``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA

#: The turns a conversation Case may hold. WHY not the connector's full role set: the scorer
#: rebuilds the chat as inspect messages, and inspect has no ``developer`` message; capture
#: never writes one, so a Case naming it was not written by us.
CONVERSATION_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})


def conversation_input(messages: Sequence[Mapping[str, str]]) -> str:
    """Seal a conversation into the one input text a Case carries: the envelope, byte for
    byte as a hand-built preparer wrote it."""

    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [
                {"role": message["role"], "content": message["content"]} for message in messages
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def conversation_messages(input_text: str) -> list[dict[str, str]] | None:
    """Open a Case input back into its conversation, or ``None`` when it is a plain prompt.

    The rule is the connector's (``world/connector.py``): a JSON object naming the
    candidate-input schema is a conversation, and any other text is a prompt as written.

    Raises:
        ValueError: the text names the schema but is not a well-formed conversation, so a
            broken Case is refused by name instead of graded as a prompt.
    """

    value: dict[str, Any] | None = _json_object(input_text)
    if value is None or value.get("schema") != CANDIDATE_INPUT_SCHEMA:
        return None
    raw: object = value.get("messages")
    if set(value) != {"schema", "messages"} or not isinstance(raw, list) or not raw:
        raise ValueError(
            "a conversation input must carry only schema and a non-empty messages list"
        )
    messages: list[dict[str, str]] = []
    for index, message in enumerate(raw):
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message["role"], str)
            or message["role"] not in CONVERSATION_ROLES
            or not isinstance(message["content"], str)
        ):
            raise ValueError(f"conversation message {index} must be a known role and text content")
        messages.append({"role": message["role"], "content": message["content"]})
    return messages


def _json_object(text: str) -> dict[str, Any] | None:
    """The text as a JSON object, or ``None`` when it is anything else."""

    # WHY the cheap check first: every plain prompt passes through here on its way to the
    # scorer; only a text that opens a JSON object can be an envelope.
    if not text.startswith("{"):
        return None
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


__all__ = ["CONVERSATION_ROLES", "conversation_input", "conversation_messages"]
