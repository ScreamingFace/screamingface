"""Neutral content parts parsed from OpenAI chat ``content`` (OME-1541).

FEATURE: image and file input across the gateway (OME-1529). Providers whose wire format is not
OpenAI's (Gemini, Antigravity, Codex) translate from these parts instead of flattening ``content``
to one string — the flatten silently dropped every image and answered 200 without it.

INVARIANT: a non-text part is never dropped silently. It parses into a `MediaPart` /
`RemoteImagePart`, or raises `UnsupportedContentPart` (422) naming the provider and part type.
Plugins import this module; core never imports a plugin.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException

# WHY: base64 is passed through verbatim — no decode/re-encode of a multi-megabyte payload — so
# only the envelope is validated: `data:<type>/<subtype>[;param…];base64,<non-empty payload>`.
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)(?:;[^;,]*)*;base64,(?P<data>.+)$", re.DOTALL
)
_REMOTE_SCHEMES = ("https://", "http://")
_MEDIA_TYPES = frozenset({"image_url", "file"})
# WHY: the Chat Completions `image_url.detail` set. Responses also has "original", but a caller
# speaking Chat Completions cannot send it, so anything outside this set is a malformed request.
_IMAGE_DETAILS = frozenset({"auto", "low", "high"})
# INVARIANT: scope is images and PDFs (OME-1541 spec). An audio/video payload wrapped in an image
# or file envelope is refused by MIME, not dispatched under the wrong part type.
_FILE_MIMES = frozenset({"application/pdf"})


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str


@dataclass(frozen=True, slots=True)
class MediaPart:
    """Inline bytes (still base64) of an image or a file such as a PDF."""

    kind: Literal["image", "file"]
    mime: str
    data: str
    filename: str | None = None
    detail: str | None = None

    @property
    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.data}"


@dataclass(frozen=True, slots=True)
class RemoteImagePart:
    """An image the caller referenced by URL. The gateway never fetches it (SSRF)."""

    url: str
    detail: str | None = None


ContentPart = TextPart | MediaPart | RemoteImagePart


class UnsupportedContentPart(HTTPException):
    """A content part this provider cannot carry — refused before any upstream call.

    # WHY 422: the request is well-formed JSON the gateway understood, but cannot be served as
    # sent. Not retryable, and no provider marks a credential as errored on it.
    """

    def __init__(self, *, provider: str, part_type: str, reason: str) -> None:
        # WHY a typed copy: `HTTPException.detail` is annotated `str`; callers that branch on
        # the fields read `info` instead of an untyped detail.
        self.info: dict[str, str] = {
            "code": "unsupported_content_part",
            "provider": provider,
            "part_type": part_type,
            "reason": reason,
            "message": f"{provider} cannot accept a {part_type} content part: {reason}",
        }
        super().__init__(status_code=422, detail=dict(self.info))


def parse_content(content: Any, *, provider: str) -> list[ContentPart]:
    """Parse one message's ``content`` into ordered neutral parts.

    Text handling deliberately matches the flatteners this replaces: any dict carrying a
    non-empty ``text``/``content`` string is text, and empty text and non-dict junk are skipped.
    """
    if content is None:
        return []
    if isinstance(content, str):
        return [TextPart(content)]
    if not isinstance(content, list):
        return [TextPart(str(content))]
    parts: list[ContentPart] = []
    for item in content:
        if isinstance(item, str):
            parts.append(TextPart(item))
        elif isinstance(item, Mapping):
            part = _parse_item(item, provider)
            if part is not None:
                parts.append(part)
    return parts


def text_of(parts: Iterable[ContentPart]) -> str:
    """The legacy flatten: text parts joined with a newline, media excluded."""
    return "\n".join(part.text for part in parts if isinstance(part, TextPart))


def has_media(parts: Iterable[ContentPart]) -> bool:
    return any(not isinstance(part, TextPart) for part in parts)


def check_messages(
    messages: Iterable[Any],
    *,
    provider: str,
    media_roles: frozenset[str],
    allow_remote_images: bool,
) -> None:
    """Refuse, before dispatch, every part this provider's adapter cannot carry.

    # WHY here and not only in the adapter: adapters run inside LiteLLM, whose exception
    # mapping would turn the typed 422 into a generic error. `prepare_chat_body` runs in the
    # route, so the caller gets the 422 detail as raised.
    """
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "user")
        for part in parse_content(message.get("content"), provider=provider):
            if isinstance(part, TextPart):
                continue
            part_type = "image_url" if part_kind(part) == "image" else "file"
            if role not in media_roles:
                raise UnsupportedContentPart(
                    provider=provider, part_type=part_type, reason=f"media in a {role} message"
                )
            if isinstance(part, RemoteImagePart) and not allow_remote_images:
                raise UnsupportedContentPart(
                    provider=provider, part_type=part_type, reason="remote_url"
                )


def part_kind(part: MediaPart | RemoteImagePart) -> Literal["image", "file"]:
    return "image" if isinstance(part, RemoteImagePart) else part.kind


def _parse_item(item: Mapping[str, Any], provider: str) -> ContentPart | None:
    part_type = item.get("type")
    if part_type == "image_url":
        return _parse_image(item.get("image_url"), provider)
    if part_type == "file":
        return _parse_file(item.get("file"), provider)
    text = item.get("text") or item.get("content")
    if isinstance(text, str):
        return TextPart(text)
    if part_type == "text":
        # an empty text part was skipped by the old flatten; still is
        return None
    # INVARIANT: fail closed — an unknown typed part (audio, video, …) or an untyped mapping
    # that carries no text is refused. Skipping it is exactly the silent drop this module ends.
    raise UnsupportedContentPart(
        provider=provider,
        part_type=part_type if isinstance(part_type, str) else "untyped",
        reason="unsupported",
    )


def _parse_image(value: Any, provider: str) -> MediaPart | RemoteImagePart:
    url = value.get("url") if isinstance(value, Mapping) else value
    detail = _image_detail(value, provider)
    if isinstance(url, str):
        match = _DATA_URI_RE.match(url)
        if match is not None:
            mime = match["mime"].lower()
            if not mime.startswith("image/"):
                raise UnsupportedContentPart(
                    provider=provider, part_type="image_url", reason=f"unsupported_mime {mime}"
                )
            return MediaPart(kind="image", mime=mime, data=match["data"], detail=detail)
        if url.startswith(_REMOTE_SCHEMES):
            return RemoteImagePart(url, detail=detail)
    raise UnsupportedContentPart(
        provider=provider, part_type="image_url", reason="expected a base64 data URI or http(s) URL"
    )


def _image_detail(value: Any, provider: str) -> str | None:
    detail = value.get("detail") if isinstance(value, Mapping) else None
    if detail is None or detail in _IMAGE_DETAILS:
        return detail
    raise UnsupportedContentPart(
        provider=provider, part_type="image_url", reason=f"invalid detail {detail!r}"
    )


def _parse_file(value: Any, provider: str) -> MediaPart:
    data = value.get("file_data") if isinstance(value, Mapping) else None
    match = _DATA_URI_RE.match(data) if isinstance(data, str) else None
    if match is None:
        # WHY: `file_id` refers to an OpenAI Files upload, and a URL would need a fetch — the
        # gateway holds neither, so only inline base64 is carried.
        raise UnsupportedContentPart(
            provider=provider, part_type="file", reason="expected base64 file_data"
        )
    mime = match["mime"].lower()
    if mime not in _FILE_MIMES:
        raise UnsupportedContentPart(
            provider=provider, part_type="file", reason=f"unsupported_mime {mime}"
        )
    filename = value.get("filename") if isinstance(value, Mapping) else None
    return MediaPart(
        kind="file",
        mime=mime,
        data=match["data"],
        filename=filename if isinstance(filename, str) and filename else None,
    )


def text_only(content: Any, *, provider: str, role: str) -> str:
    """Flatten ``content`` where the provider's slot holds text only (system, tool result).

    # INVARIANT: refuses media rather than dropping it — `check_messages` normally refuses
    # first; this keeps the adapter itself from ever being the silent drop.
    """
    parts = parse_content(content, provider=provider)
    for part in parts:
        if not isinstance(part, TextPart):
            raise UnsupportedContentPart(
                provider=provider,
                part_type="image_url" if part_kind(part) == "image" else "file",
                reason=f"media in a {role} message",
            )
    return text_of(parts)


def gemini_parts(parts: Iterable[ContentPart], *, provider: str) -> list[dict[str, Any]]:
    """Gemini-format parts (Gemini API, Code Assist, Antigravity): text and ``inlineData``.

    # INVARIANT: consecutive text parts are joined with a newline into ONE ``{"text"}`` part,
    # exactly as the old flatten did, so a text-only message is byte-identical to before.
    # WHY in core: two plugins (gemini, antigravity) speak this format and must not import
    # each other.
    """
    out: list[dict[str, Any]] = []
    run: list[str] = []

    def flush() -> None:
        text = "\n".join(run)
        if text:
            out.append({"text": text})
        run.clear()

    for part in parts:
        if isinstance(part, TextPart):
            run.append(part.text)
        elif isinstance(part, MediaPart):
            flush()
            out.append({"inlineData": {"mimeType": part.mime, "data": part.data}})
        else:
            raise UnsupportedContentPart(
                provider=provider, part_type="image_url", reason="remote_url"
            )
    flush()
    return out
