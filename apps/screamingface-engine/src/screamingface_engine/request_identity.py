"""Payload-free identity for one authored model request.

FEATURE (OME-1271): think of the key as a fingerprint of what the model will SEE, not of how the
request was typed. For text, those are the same thing, so a text request is hashed exactly as it
always was. A picture is different: one picture can be spelled many ways in base64 (line breaks,
dropped padding) inside an envelope whose JSON key order and whitespace vary too. So a v2 Case that
carries a picture or file is keyed by its canonical part list instead: each part's place and kind,
and for a picture the sha256 of its DECODED bytes. Rule source: the request-identity section of the
file-input spec on #1450.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Literal, NewType, NotRequired, TypedDict

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    ContentPart,
    parse_candidate_input,
    split_data_uri,
)

ModelRequestKey = NewType("ModelRequestKey", str)

NON_TEXT_PART_ADAPTER_REVISION: int = 1
"""The version of how the connector builds picture and file parts for the gateway.

AIDEV-NOTE: bump it whenever that building changes (a new field forwarded, a re-encoding), so no
picture call is answered from a reply stored under the old build. It enters only picture-bearing
keys; a text request has no such part, and its key must stay what it has always been.
"""


class CanonicalPart(TypedDict):
    """One part of a request as the key reads it; absent fields are omitted, never ``null``.

    e.g. ``{"kind": "image", "role": "user", "message": 1, "position": 1,
    "digest": "sha256:9f…", "media_type": "image/png", "detail": "low"}``.
    """

    kind: Literal["text", "image", "file"]
    role: str
    message: int
    position: int
    text: NotRequired[str]
    digest: NotRequired[str]
    media_type: NotRequired[str]
    detail: NotRequired[str]
    filename: NotRequired[str]


def canonical_request_parts(messages: Sequence[CandidateMessage]) -> list[CanonicalPart]:
    """Flatten parsed envelope messages into the ordered part list the request key hashes.

    Walks messages in order, then parts in order. A string message is one text part at position
    0. A picture or file part is named by the sha256 of its decoded bytes plus its media type and
    its optional detail or filename, so its base64 spelling never reaches the key.

    Raises:
        CandidateInputError: a picture or file is not decodable base64 in a ``data:`` URI.
    """

    parts: list[CanonicalPart] = []
    for index, message in enumerate(messages):
        role: str = message["role"]
        content: str | list[ContentPart] = message["content"]
        if isinstance(content, str):
            parts.append(
                {"kind": "text", "role": role, "message": index, "position": 0, "text": content}
            )
            continue
        parts.extend(
            _canonical_part(role, index, position, part) for position, part in enumerate(content)
        )
    return parts


def _canonical_part(role: str, index: int, position: int, part: ContentPart) -> CanonicalPart:
    """One part of a part-list message, read by its type; a picture or file by its bytes."""

    where: str = f"message {index} part {position}"
    if part["type"] == "text":
        return {
            "kind": "text",
            "role": role,
            "message": index,
            "position": position,
            "text": part["text"],
        }
    if part["type"] == "image_url":
        image: CanonicalPart = _media_part(
            "image", role, index, position, part["image_url"]["url"], where
        )
        if "detail" in part["image_url"]:
            image["detail"] = part["image_url"]["detail"]
        return image
    file: CanonicalPart = _media_part(
        "file", role, index, position, part["file"]["file_data"], where
    )
    if "filename" in part["file"]:
        file["filename"] = part["file"]["filename"]
    return file


def model_request_key(
    *,
    path: str,
    params: Mapping[str, str],
    context: str | None,
    intent: str | None,
) -> ModelRequestKey:
    """Hash the exact URL4 model request fields shared by author and connector.

    Stage 1 — read the parts: a v2 context carrying a picture or file is decoded and hashed into
        its canonical part list here, before any key exists.
    Stage 2 — choose the form: no picture or file → today's fields (``context`` as raw text),
        byte for byte; otherwise the part list replaces ``context``, beside the adapter revision.
    Stage 3 — hash one canonical JSON (UTF-8, sorted keys, no insignificant whitespace).
    """

    # Stage 1 — read the parts.
    parts: list[CanonicalPart] | None = _picture_request_parts(context)

    # Stage 2 — choose the form.
    fields: dict[str, object] = {"path": path, "params": sorted(params.items()), "intent": intent}
    if parts is None:
        fields["context"] = context
    else:
        fields["parts"] = parts
        fields["adapter_revision"] = NON_TEXT_PART_ADAPTER_REVISION

    # Stage 3 — hash.
    payload: bytes = json.dumps(
        fields, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return ModelRequestKey(hashlib.sha256(payload).hexdigest())


def _picture_request_parts(context: str | None) -> list[CanonicalPart] | None:
    """The canonical part list of a context that carries a picture or file, else ``None``.

    INVARIANT: ``None`` for a plain prompt, a v1 envelope and any text-only context, so those keep
    today's key. Also ``None`` for an envelope the parser or the decoder refuses: the connector
    refuses that request by name (or the gateway does), and the key must not raise first and turn
    the refusal into a stray error. It keys the text as written, as it always has.
    """

    try:
        messages: list[CandidateMessage] | None = parse_candidate_input(context)
        if messages is None or all(isinstance(m["content"], str) for m in messages):
            return None
        return canonical_request_parts(messages)
    except CandidateInputError:
        return None


def _media_part(
    kind: Literal["image", "file"],
    role: str,
    index: int,
    position: int,
    uri: str,
    where: str,
) -> CanonicalPart:
    """Name one inline picture or file by the sha256 of its decoded bytes and its media type."""

    split: tuple[str, str] | None = split_data_uri(uri)
    if split is None:
        raise CandidateInputError(f"{where}: expected an inline data: URI")
    media_type, encoded = split
    # WHY strip and re-pad: base64 line breaks and dropped `=` padding spell the same bytes, and
    # strict decoding of what remains refuses anything that is not base64.
    compact: str = "".join(encoded.split())
    compact += "=" * (-len(compact) % 4)
    try:
        raw: bytes = base64.b64decode(compact, validate=True)
    except binascii.Error:
        raise CandidateInputError(f"{where}: the data: URI is not valid base64") from None
    return {
        "kind": kind,
        "role": role,
        "message": index,
        "position": position,
        "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "media_type": media_type,
    }


__all__ = [
    "NON_TEXT_PART_ADAPTER_REVISION",
    "CanonicalPart",
    "ModelRequestKey",
    "canonical_request_parts",
    "model_request_key",
]
