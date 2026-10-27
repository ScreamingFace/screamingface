"""The Case input a Case Result echoes: the Case as written, less any picture's bytes (OME-1271).

FEATURE (OME-1271): every Case Result carries the input it answered, so a researcher reads the
question beside the answer. A picture Benchmark carries its pictures inline as base64 (LAB-Bench
FigQA: 181 Cases, about 330 MB), and a notebook holding all of it runs out of memory. So the copy
that leaves the engine shows each picture or file as the shared placeholder instead: its type,
size and sha256, and its filename when the part names one. The sha256 stays, because it is what
proves a picture opened later is the one the model saw.

INVARIANT: only the published copy changes. Grading reads the real Case before this runs, and a
Case with no picture or file is echoed as the exact same string.
"""

from __future__ import annotations

import json
from typing import Any

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    ContentPart,
    media_placeholder,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA


def echoed_input(case_input: str) -> str:
    """The text a Case Result shows for ``case_input``: as written, or with each picture's bytes
    replaced by its placeholder.

    Stage 1 — read the Case by the members' rules (``parse_candidate_input``). A plain prompt, a
        v1 conversation, or anything else without a picture or file comes back as the same
        string, so a text Benchmark's results stay byte-identical.
    Stage 2 — a Case the reader refuses is echoed as one line naming the rule it broke. It already
        failed when the Candidate was asked; its raw text may hold megabytes of base64, and the
        reader's refusal never quotes a URL or the bytes.
    Stage 3 — a v2 Case is rebuilt with every picture's ``url`` (or file's ``file_data``) replaced
        by its placeholder, every other field and every text kept, in the Case's own order.

    e.g. ``{"schema":"…v2","messages":[{"role":"user","content":[{"type":"text","text":"What is
    shown?"},{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgo="}}]}]}`` →
    the same envelope with ``"url":{"placeholder":"image","media_type":"image/png","size":8,
    "sha256":"4c4b6a3b…"}``.
    """

    # Stage 1 — read the Case.
    try:
        messages: list[CandidateMessage] | None = parse_candidate_input(case_input)
    # Stage 2 — a refused Case.
    except CandidateInputError as exc:
        return f"[Case input not shown: {exc}]"
    if messages is None or all(isinstance(message["content"], str) for message in messages):
        return case_input

    # Stage 3 — the Case, less the bytes.
    shown: list[dict[str, Any]] = [
        dict(message)
        if isinstance(message["content"], str)
        else {
            "role": message["role"],
            "content": [
                _shown_part(part, where=f"message {index} part {position}")
                for position, part in enumerate(message["content"])
            ],
        }
        for index, message in enumerate(messages)
    ]
    # WHY compact and unescaped: the importer writes a Case this way, so the echo reads like the
    # Case did; the SDK reads it with json.loads either way.
    return json.dumps(
        {"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": shown},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _shown_part(part: ContentPart, *, where: str) -> dict[str, Any]:
    """One part as a result shows it: text as written, a picture or file with its bytes replaced.

    WHY the placeholder sits where the bytes were (``image_url.url``, ``file.file_data``): that is
    where the SDK's Case Result looks for it (``case_result.py`` ``_part_placeholder``), and the
    Fusion synthesizer's text uses the same spot (``world/fusion_context.py``).
    """

    if part["type"] == "text":
        return dict(part)
    if part["type"] == "image_url":
        image: dict[str, Any] = dict(part["image_url"])
        image["url"] = media_placeholder(part, where=where)
        return {"type": "image_url", "image_url": image}
    file: dict[str, Any] = dict(part["file"])
    file["file_data"] = media_placeholder(part, where=where)
    return {"type": "file", "file": file}


__all__ = ["echoed_input"]
