"""Read a Fusion's synthesizer context so the synthesizer sees the Case's pictures (OME-1679).

FEATURE (OME-1679): a Fusion has member models answer a Case, then a synthesizer writes the final
answer from theirs. The SDK compiles the synthesizer's context before any Case exists, as one
url4 struct, and url4 renders it at run time as JSON text::

    {"input": "<the Case input, as written>", "outputs": {"member_1": "about 42", ...}}

A reducer's signal calls read the same object with ``panel`` in place of ``outputs``. Members get
the Case's pictures as image parts; without this module the synthesizer would get them as base64
inside that text. The connector asks here only for a context that is not itself an envelope.

INVARIANT (spec F2): both reads are structural. The context is parsed as JSON and must have the
shape the combine parser reads (``combine/spec.py``); ``input`` is read as a member, and that
string goes through the shared envelope reader; no rendered text is ever scanned for pictures.
The engine learns that shape and nothing else about recipes, member names included.

AIDEV-NOTE: a Fusion used as another Fusion's synthesizer is not read here. The SDK hands its
synthesizer ``{"input": "{input: '<Case>', outputs: …}", …}``: the inner ``input`` is url4 struct
text, not JSON, so the picture stays base64 in that text. Fixing it means the SDK compiling that
input as JSON first (OME-1741).
"""

from __future__ import annotations

import json
from typing import Any

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    ContentPart,
    FilePart,
    ImagePart,
    media_placeholder,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.combine.ports import loads_bounded
from screamingface_engine.combine.spec import _CONTEXT_KEYS  # pyright: ignore[reportPrivateUsage]

_INPUT_KEY = "input"


def fusion_picture_messages(context: str | None) -> list[CandidateMessage] | None:
    """The synthesizer's user message for a picture Case, or ``None`` to send the text as is.

    Stage 1 — is it a Fusion context? A JSON object with no repeated key, ``input`` as text, exactly
        one of ``outputs`` and ``panel``, and no key the combine parser does not know. Anything
        else is ``None``, so its bytes are sent as written.
    Stage 2 — is that input a picture Case? It is read by the members' rules: a broken envelope is
        refused, and a plain prompt or a Case without pictures is ``None``, so a text-only Fusion
        keeps its exact bytes and every golden replays.
    Stage 3 — one user message: every picture and file part first, in Case order, then one text
        part. That text is the context with only ``input`` changed: the Case rebuilt with each
        picture's ``url`` (or file's ``file_data``) replaced by its placeholder, less the digest,
        numbered from 1 across the Case: placeholder ``index`` k is the k-th part sent before it.

    e.g. ``{"input": <v2 Case: question + 300 KB PNG>, "outputs": {...}}`` →
    ``[{"role": "user", "content": [<the PNG image part>, {"type": "text", "text":
    '{"input": "<the Case, PNG shown as {placeholder, index: 1, media_type, size}>", ...}'}]}]``.

    Raises:
        CandidateInputError: the Case under ``input`` breaks the envelope rules, or a picture's
            base64 does not decode; the text names the message and part.
    """

    # Stage 1 — a Fusion context?
    fusion: dict[str, Any] | None = _fusion_object(context)
    if fusion is None:
        return None
    case_input: str = fusion[_INPUT_KEY]

    # Stage 2 — a picture Case?
    try:
        messages: list[CandidateMessage] | None = parse_candidate_input(case_input)
    except CandidateInputError as exc:
        raise CandidateInputError(f"in the Fusion input, {exc}") from exc
    if messages is None or all(isinstance(message["content"], str) for message in messages):
        return None

    # Stage 3 — the pictures, then the text that shows them.
    media: list[ContentPart] = []
    shown: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        content: str | list[ContentPart] = message["content"]
        if isinstance(content, str):
            shown.append(dict(message))
            continue
        shown_parts: list[dict[str, Any]] = []
        for position, part in enumerate(content):
            if part["type"] == "text":
                shown_parts.append(dict(part))
                continue
            media.append(part)
            shown_parts.append(
                _shown_part(
                    part,
                    number=len(media),
                    where=f"in the Fusion input, message {index} part {position}",
                )
            )
        shown.append({"role": message["role"], "content": shown_parts})
    # WHY compact: the envelope sits inside `input` as one string, the way the importer writes it.
    fusion[_INPUT_KEY] = json.dumps(
        {"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": shown}, separators=(",", ":")
    )
    # WHY json.dumps with its defaults: url4 renders the Fusion struct the same way
    # (`StructNode.resolve`), so the text reads exactly as the Fusion wrote it, `input` aside.
    text: str = json.dumps(fusion)
    return [{"role": "user", "content": [*media, {"type": "text", "text": text}]}]


def _fusion_object(context: str | None) -> dict[str, Any] | None:
    """The context as a Fusion's ``{input, outputs | panel, …}`` object, or ``None`` if it is not.

    e.g. ``{"input": "…", "outputs": {…}}`` and ``{"input": "…", "panel": "…", "signals": {…}}``
    are; ``{"input": "…", "metadata": "…"}``, a repeated ``input``, or ``input`` as an object are
    not.
    """

    value: object = None
    # WHY the cheap check first: every plain prompt passes through here.
    if context and context.lstrip().startswith("{"):
        try:
            # WHY unique keys: json.loads keeps the last of two `input`s, so rebuilding the text
            # would silently drop one; no Fusion writes such a text, so it is sent as written.
            value = loads_bounded(context, unique_keys=True)
        # WHY RecursionError too: as in candidate_input.py, deep nesting is text, not a Fusion.
        except (ValueError, RecursionError):
            value = None
    # INVARIANT: the combine parser's shape rule (`parse_context`), so the two agree on what a
    # Fusion context is.
    if (
        not isinstance(value, dict)
        or not isinstance(value.get(_INPUT_KEY), str)
        or not value.keys() <= _CONTEXT_KEYS
        or ("outputs" in value) == ("panel" in value)
    ):
        return None
    return value


def _shown_part(part: ContentPart, *, number: int, where: str) -> dict[str, Any]:
    """A picture or file part with its bytes replaced by the placeholder; other fields kept."""

    if part["type"] == "image_url":
        image: dict[str, Any] = dict(part["image_url"])
        image["url"] = _shown_placeholder(part, number=number, where=where)
        return {"type": "image_url", "image_url": image}
    assert part["type"] == "file"
    file: dict[str, Any] = dict(part["file"])
    file["file_data"] = _shown_placeholder(part, number=number, where=where)
    return {"type": "file", "file": file}


def _shown_placeholder(part: ImagePart | FilePart, *, number: int, where: str) -> dict[str, Any]:
    """The placeholder as the synthesizer reads it: the shared one, numbered, less its digest.

    e.g. the second part sent → ``{"placeholder": "image", "index": 2, "media_type": "image/png",
    "size": 307200}``.
    """

    placeholder: dict[str, Any] = dict(media_placeholder(part, where=where))
    # WHY drop the digest here and only here: the synthesizer cannot hash the picture it is shown
    # beside this text, and a digest in a model's text reads as a reference to fetch, which the
    # spec's Fusion paragraph forbids. Results keep it, because a picture opened from a Case
    # Result is checked against it (OME-1271).
    del placeholder["sha256"]
    # WHY a number, and only here: the synthesizer gets every part first and this text after, so
    # it must pair part k with placeholder k. Two same-type same-size pictures look identical
    # without it. 1-based, to match MMMU's own <image 1> in its questions. Results keep the
    # Case's own layout, so they need none.
    return {"placeholder": placeholder.pop("placeholder"), "index": number, **placeholder}


__all__ = ["fusion_picture_messages"]
