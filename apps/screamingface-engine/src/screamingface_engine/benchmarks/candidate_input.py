"""Read a Case input: a plain prompt, or a candidate-input envelope of chat messages.

FEATURE (OME-1678): think of a Case input as a letter that is either written straight on the page
(a plain prompt) or sealed in an envelope (a JSON object naming a candidate-input schema). This
module is the one place that opens the envelope, so the connector and the inspect plugin read the
same rules instead of two drifting copies.

* v1 carries text messages, each ``{"role", "content": str}``.
* v2 lets a user message carry pictures and PDFs inline, as ``data:`` URIs (RFC 2397) inside
  OpenAI content parts. A message without a picture or file stays a plain string, and a Case with
  none at all stays v1, so every Case and every message has exactly one valid encoding.

Worked example (v2, one question and one picture)::

    {"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":[
      {"type":"text","text":"What is the height of the tallest bar?"},
      {"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgo="}}]}]}

INVARIANT: nothing here decodes or opens a picture. Only the ``data:`` prefix is checked, the same
envelope check the gateway makes, and the base64 is passed on verbatim. A refusal names the message
and part by position and never echoes a URL or the bytes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, NoReturn

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
    CANDIDATE_MESSAGE_ROLES,
)

_SCHEMA_FAMILY = "screamingface.candidate-input."
# WHY the gateway's own pattern (aigateway `content_parts.py`): a Case the connector accepts must
# also pass the gateway, so both read the envelope the same way.
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)(?:;[^;,]*)*;base64,(?P<data>.+)$", re.DOTALL
)
# WHY these four: the picture types every provider behind the gateway accepts. SVG is markup that
# can carry a script, so it is refused outright.
_PICTURE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_FILE_MIMES = frozenset({"application/pdf"})
# WHY: the Chat Completions `image_url.detail` set; anything else fails at the gateway anyway.
_IMAGE_DETAILS = frozenset({"auto", "low", "high"})
_MEDIA_PART_TYPES = frozenset({"image_url", "file"})


class CandidateInputError(ValueError):
    """A Case input names the candidate-input schema but breaks its rules."""


def parse_candidate_input(text: str | None) -> list[dict[str, Any]] | None:
    """Open a Case input into chat messages, or ``None`` when it is a plain prompt.

    Stage 1 — is it an envelope? Anything that is not a JSON object naming a
        ``screamingface.candidate-input.*`` schema is a prompt as written: ``None``.
    Stage 2 — which version? v1 and v2 are read; any other version of the family is refused by
        name, never guessed at.
    Stage 3 — every message: a known role, and content that is a string (v1 and v2) or a part
        list (v2 only, user messages only, holding at least one picture or file).
    Stage 4 — the whole v2 envelope: at least one picture or file, else it should be v1.

    Returns the messages rebuilt from their checked fields, so the request the connector sends
    has one fixed key order. A v1 Case comes back exactly as written.

    Raises:
        CandidateInputError: the envelope breaks a rule; the text names the message and part.
    """

    # Stage 1 — is it an envelope?
    envelope: dict[str, Any] | None = _json_object(text)
    schema: object = None if envelope is None else envelope.get("schema")
    if envelope is None or not isinstance(schema, str) or not schema.startswith(_SCHEMA_FAMILY):
        return None

    # Stage 2 — which version?
    if schema not in (CANDIDATE_INPUT_SCHEMA, CANDIDATE_INPUT_V2_SCHEMA):
        _refuse(f"unsupported schema {schema!r}")
    if set(envelope) != {"schema", "messages"}:
        _refuse("the chat envelope must contain only schema and messages")
    raw_messages: object = envelope["messages"]
    if not isinstance(raw_messages, list) or not raw_messages:
        _refuse("messages must be a non-empty array")

    # Stage 3 — every message.
    allows_parts: bool = schema == CANDIDATE_INPUT_V2_SCHEMA
    messages: list[dict[str, Any]] = [
        _message(index, value, allows_parts=allows_parts)
        for index, value in enumerate(raw_messages)
    ]

    # Stage 4 — a v2 envelope must earn its version.
    if allows_parts and all(isinstance(message["content"], str) for message in messages):
        _refuse("a v2 envelope that carries no picture or file; write it as v1")
    return messages


def _message(index: int, value: object, *, allows_parts: bool) -> dict[str, Any]:
    """Check one message and rebuild it as ``{"role", "content"}``."""

    if not isinstance(value, dict) or set(value) != {"role", "content"}:
        _refuse(f"message {index} must contain exactly role and content")
    role: object = value["role"]
    content: object = value["content"]
    if not isinstance(role, str) or role not in CANDIDATE_MESSAGE_ROLES:
        _refuse(f"message {index} has unsupported role {role!r}")
    if isinstance(content, str):
        return {"role": role, "content": content}
    if not allows_parts:
        _refuse(f"message {index} content must be text")
    return {"role": role, "content": _part_list(index, role, content)}


def _part_list(index: int, role: str, content: object) -> list[dict[str, Any]]:
    """Check a v2 message's part list: a user message holding at least one picture or file."""

    if not isinstance(content, list):
        _refuse(f"message {index} content must be text or a part list")
    if not content:
        _refuse(f"message {index}: a part list must not be empty")
    # WHY user only: Anthropic OAuth drops non-text parts from system messages, and a picture the
    # model never saw would grade as a wrong answer instead of failing the Case.
    if role != "user":
        _refuse(f"message {index}: pictures and files go in user messages only")
    parts: list[dict[str, Any]] = [
        _part(f"message {index} part {position}", part) for position, part in enumerate(content)
    ]
    if not any(part["type"] in _MEDIA_PART_TYPES for part in parts):
        _refuse(
            f"message {index}: a part list must carry a picture or file; write text as a string"
        )
    return parts


def _part(where: str, value: object) -> dict[str, Any]:
    """Check one content part and rebuild it from its allowed fields only."""

    if not isinstance(value, dict):
        _refuse(f"{where} must be an object")
    part_type: object = value.get("type")
    if part_type == "text":
        text: object = value.get("text")
        if set(value) != {"type", "text"} or not isinstance(text, str) or not text:
            _refuse(f"{where}: a text part is exactly type and a non-empty text")
        return {"type": "text", "text": text}
    if part_type == "image_url":
        return {"type": "image_url", "image_url": _picture(where, value)}
    if part_type == "file":
        return {"type": "file", "file": _file(where, value)}
    shown: str = part_type if isinstance(part_type, str) else "untyped"
    _refuse(f"{where}: unsupported part type {shown!r}")


def _picture(where: str, part: Mapping[str, Any]) -> dict[str, str]:
    """The ``image_url`` object of a picture part: an inline picture and an optional detail."""

    body: object = part.get("image_url")
    if (
        set(part) != {"type", "image_url"}
        or not isinstance(body, dict)
        or "url" not in body
        or not set(body) <= {"url", "detail"}
    ):
        _refuse(f"{where}: an image_url part is exactly type and image_url {{url, detail?}}")
    mime: str = _data_uri_mime(where, body["url"])
    if mime not in _PICTURE_MIMES:
        _refuse(f"{where}: picture type {mime} is not png, jpeg, gif or webp")
    picture: dict[str, str] = {"url": body["url"]}
    if "detail" in body:
        detail: object = body["detail"]
        if not isinstance(detail, str) or detail not in _IMAGE_DETAILS:
            _refuse(f"{where}: detail must be auto, low or high")
        picture["detail"] = detail
    return picture


def _file(where: str, part: Mapping[str, Any]) -> dict[str, str]:
    """The ``file`` object of a file part: an inline PDF and an optional filename."""

    body: object = part.get("file")
    if (
        set(part) != {"type", "file"}
        or not isinstance(body, dict)
        or "file_data" not in body
        or not set(body) <= {"file_data", "filename"}
    ):
        _refuse(f"{where}: a file part is exactly type and file {{file_data, filename?}}")
    mime: str = _data_uri_mime(where, body["file_data"])
    if mime not in _FILE_MIMES:
        _refuse(f"{where}: file type {mime} is not application/pdf")
    file: dict[str, str] = {"file_data": body["file_data"]}
    if "filename" in body:
        filename: object = body["filename"]
        if not isinstance(filename, str) or not filename:
            _refuse(f"{where}: filename must be non-empty text")
        file["filename"] = filename
    return file


def _data_uri_mime(where: str, value: object) -> str:
    """The lower-cased media type of an inline ``data:`` URI; anything else is refused.

    INVARIANT: an ``https://`` URL or a ``/blob/`` reference is refused here, so a Case can never
    make the gateway, or Codex behind it, fetch something the Case picked.
    """

    match: re.Match[str] | None = _DATA_URI_RE.match(value) if isinstance(value, str) else None
    if match is None:
        _refuse(f"{where}: expected an inline data: URI")
    return match["mime"].lower()


def _json_object(text: str | None) -> dict[str, Any] | None:
    """The text as a JSON object, or ``None`` when it is anything else."""

    # WHY the cheap check first: every plain prompt passes through here; only a text that opens a
    # JSON object can be an envelope.
    if not text or not text.lstrip().startswith("{"):
        return None
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _refuse(detail: str) -> NoReturn:
    """Stop with the rule a Case input broke."""

    raise CandidateInputError(detail)


__all__ = ["CandidateInputError", "parse_candidate_input"]
