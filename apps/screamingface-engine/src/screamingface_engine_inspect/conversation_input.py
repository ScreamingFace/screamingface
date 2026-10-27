"""A Case whose prompt is a fixed conversation, written as one input text (OME-1527, R14).

FEATURE: some exams hand the Candidate a chat the dataset already wrote (user, assistant,
user, …) and ask it for the next turn: healthbench's conversation Cases. That is still ONE
Candidate call, but the Case input can't be one plain prompt. Think of it as a sealed letter:
the conversation travels inside the candidate-input envelope, the one text format the
Engine already reads as chat messages. The connector opens it for a single model, a Fusion
synthesizer reads it as written, and the scorer opens it again to rebuild the chat.

The bytes are the hand-built preparers' (hand-built healthbench's ``prepare.envelope``, deleted in
OME-1527 row 20 once its local Task reproduced them):
keys ``schema`` then ``messages``, each message ``role`` then ``content``, compact
separators, non-ASCII kept as is. A migrated Benchmark's recorded calls then replay as hits.

Worked example: user "My knee hurts.", assistant "Since when?", user "Two days." →
``{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user","content":"My knee
hurts."},{"role":"assistant","content":"Since when?"},{"role":"user","content":"Two days."}]}``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)

#: The turns a conversation Case may hold. WHY not the connector's full role set: the scorer
#: rebuilds the chat as inspect messages, and inspect has no ``developer`` message; capture
#: never writes one, so a Case naming it was not written by us.
CONVERSATION_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})


def conversation_input(messages: Sequence[Mapping[str, str]]) -> str:
    """Seal a conversation into the one input text a Case carries: the envelope, byte for
    byte as a hand-built preparer wrote it."""

    return _sealed(
        CANDIDATE_INPUT_SCHEMA,
        [{"role": message["role"], "content": message["content"]} for message in messages],
    )


def picture_case_input(messages: Sequence[CandidateMessage]) -> str:
    """Seal a Case that carries pictures into the v2 envelope, in the v1 envelope's bytes style.

    FEATURE (OME-1271): the importer's picture Cases. e.g. one user message holding a PNG then
    its question → ``{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user",
    "content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBO…"}},
    {"type":"text","text":"How tall?"}]}]}``.
    """

    return _sealed(CANDIDATE_INPUT_V2_SCHEMA, list(messages))


def _sealed(schema: str, messages: Sequence[Mapping[str, object]]) -> str:
    """The envelope's bytes: keys ``schema`` then ``messages``, compact, non-ASCII as is."""

    return json.dumps(
        {"schema": schema, "messages": list(messages)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def conversation_messages(input_text: str) -> list[CandidateMessage] | None:
    """Open a Case input back into its conversation, or ``None`` when it is a plain prompt.

    FEATURE (OME-1271): the rule is the shared parser's (``benchmarks/candidate_input.py``),
    the one the connector reads with, so the plugin and the connector never disagree on what
    is an envelope. A v1 envelope comes back as text turns; a v2 envelope (a user message
    carrying a picture or PDF inline) comes back with that message's part list; any other
    version of the schema is refused, never read as a prompt.

    Worked example: ``{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user",
    "content":[{"type":"text","text":"How tall?"},{"type":"image_url","image_url":{"url":
    "data:image/png;base64,iVBO…"}}]}]}`` → one user message whose content is those two parts.

    Raises:
        CandidateInputError: a ``ValueError``; the text names the schema but is not a
            well-formed conversation (an unknown version included), so a broken Case is
            refused by name instead of graded as a prompt.
    """

    try:
        messages: list[CandidateMessage] | None = parse_candidate_input(input_text)
    except CandidateInputError as exc:
        raise CandidateInputError(f"a conversation input is not a valid envelope: {exc}") from exc
    if messages is None:
        return None
    for index, message in enumerate(messages):
        # WHY on top of the shared rule: the shared parser admits ``developer`` (the connector
        # can send it), but the scorer could not rebuild it (see CONVERSATION_ROLES).
        if message["role"] not in CONVERSATION_ROLES:
            raise CandidateInputError(f"conversation message {index} must be a known role")
    return messages


__all__ = [
    "CONVERSATION_ROLES",
    "conversation_input",
    "conversation_messages",
    "picture_case_input",
]
