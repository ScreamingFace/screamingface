"""Neutral content parts parsed from OpenAI chat ``content`` (OME-1541).

FEATURE: image and file input across the gateway (OME-1529). Providers whose wire format is not
OpenAI's (Gemini, Antigravity, Codex) translate from these parts instead of flattening ``content``
to one string — the flatten silently dropped every image and answered 200 without it.

INVARIANT: a non-text part is never dropped silently. It parses into a `MediaPart` /
`RemoteImagePart`, or raises `UnsupportedContentPart` (422) naming the provider and part type.
Plugins import this module; core never imports a plugin.

FEATURE (OME-1970): a **reference part** names a Case file the caller uploaded to the gateway
earlier (`PUT /v1/blobs/sha256/{digest}`) by ``blob:sha256/<64 hex>``, the SHA-256 of its bytes,
where an inline part holds its ``data:`` URI. The admission checks here (`check_messages`,
`text_only`) judge it as the inline part it stands for; the chat route swaps it for that inline
part inside the upstream slot (`core/blob_refs.py`), so an adapter's `parse_content` never meets
one and refuses it if it ever does.
"""

from __future__ import annotations

import binascii
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from fastapi import HTTPException

from .input_modalities import normalize_input_modalities

# WHY: base64 is passed through verbatim — no re-encode of a multi-megabyte payload. This pattern is
# the envelope `data:<type>/<subtype>[;param…];base64,<non-empty payload>`; `parse_data_uri` adds
# the payload's base64 check. AIDEV-NOTE: the engine copies this exact pattern (conformance tests on
# both sides) — change it in both apps or not at all.
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)(?:;[^;,]*)*;base64,(?P<data>.+)$", re.DOTALL
)
# WHY a bound on the part before the first comma (OME-1542 review 2): the envelope regex is linear,
# but on an 8 MiB header of `;param` segments it still costs ~200 ms per parse. RFC 6838 caps a
# type and a subtype at 127 characters each; 1 KiB leaves ample room for parameters (`name=…`).
# INVARIANT: none of the envelope's header classes match a comma, so a header longer than this can
# never be a data URI the regex accepts within it — checking the bound first changes no outcome
# for a header that fits.
_MAX_DATA_URI_HEADER = 1024
_REMOTE_SCHEMES = ("https://", "http://")
# WHY: the Chat Completions `image_url.detail` set. Responses also has "original", but a caller
# speaking Chat Completions cannot send it, so anything outside this set is a malformed request.
_IMAGE_DETAILS = frozenset({"auto", "low", "high"})
# INVARIANT: scope is images and PDFs (OME-1541 spec). An audio/video payload wrapped in an image
# or file envelope is refused by MIME, not dispatched under the wrong part type.
_FILE_MIMES = frozenset({"application/pdf"})
# FEATURE (OME-1970): the reference part's spelling, and its two declared facts about the file.
BLOB_REFERENCE_PREFIX = "blob:sha256/"
# WHY lowercase hex only: one file has one name, as the upload route spells it.
_BLOB_REFERENCE_RE = re.compile(r"blob:sha256/(?P<sha256>[0-9a-f]{64})")
REFERENCE_FIELDS = ("x_media_type", "x_size")
# INVARIANT: a reference part's shape is closed. Any other key would ride to the provider beside
# the swapped-in file, and change the cache key away from the inline request's.
_REFERENCE_INNER_KEYS: Mapping[str, frozenset[str]] = {
    "image_url": frozenset({"url", "detail"}),
    "file": frozenset({"file_data", "filename"}),
}
_REFERENCE_VALUE_KEY: Mapping[str, str] = {"image_url": "url", "file": "file_data"}


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


@dataclass(frozen=True, slots=True)
class BlobRefPart:
    """A Case file in the gateway's own memory, named by the SHA-256 of its bytes (OME-1970).

    ``mime`` and ``size_bytes`` are what the caller declared (``x_media_type``, ``x_size``); the
    route checks both against the stored file before anything is keyed or sent.
    """

    kind: Literal["image", "file"]
    mime: str
    sha256: str
    size_bytes: int
    filename: str | None = None
    detail: str | None = None


# What an adapter carries: references are swapped for inline parts before any adapter runs.
ContentPart = TextPart | MediaPart | RemoteImagePart
# What the admission checks judge, before that swap.
AdmittedPart = ContentPart | BlobRefPart


@dataclass(frozen=True, slots=True)
class DataUri:
    """A validated inline payload: lowercase MIME and the base64 text, verbatim."""

    mime: str
    data: str


def parse_data_uri(value: str) -> DataUri | None:
    """The ONE `data:` URI validator — the ingress guard and the parser both call it (OME-1542).

    # INVARIANT: accepts exactly the engine-conformant envelope (`_DATA_URI_RE`) whose payload is
    # non-empty, strictly valid base64 (standard alphabet, correct padding, no whitespace).
    # INVARIANT: linear-time. The header is bounded before the regex sees it, and the payload is
    # checked by `binascii` in C, never by a pattern.
    # WHY decode only to validate: the payload is still carried verbatim; the decoded bytes are
    # discarded. Measured ~6 ms for an 8 MiB payload.
    """
    comma = value.find(",", 0, _MAX_DATA_URI_HEADER + 1)
    if comma < 0:
        return None
    match = _DATA_URI_RE.match(value)
    if match is None:
        return None
    data = match["data"]
    try:
        binascii.a2b_base64(data, strict_mode=True)
    except ValueError:  # binascii.Error, and non-ASCII text
        return None
    return DataUri(mime=match["mime"].lower(), data=data)


def remote_url_scheme(url: str) -> str | None:
    """``"http"`` / ``"https"`` for a remote URL in ANY case (RFC 3986 §3.1), else ``None``.

    # WHY shared (OME-1542 review 2): the ingress guard lowercased the scheme and this parser did
    # not, so `HTTPS://` passed ingress for Codex and was refused after credential resolution.
    """
    head = url[:8].lower()
    for scheme in _REMOTE_SCHEMES:
        if head.startswith(scheme):
            return scheme[:-3]
    return None


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

    INVARIANT (OME-1970): this is the adapters' parser, which runs after the in-slot swap, so a
    reference part reaching it is a gateway bug; it is refused, never sent upstream as text.
    """
    parts: list[ContentPart] = []
    for part in _admitted_parts(content, provider):
        if isinstance(part, BlobRefPart):
            raise UnsupportedContentPart(
                provider=provider,
                part_type="image_url" if part.kind == "image" else "file",
                reason="unresolved_blob_reference",
            )
        parts.append(part)
    return parts


def _admitted_parts(content: Any, provider: str) -> list[AdmittedPart]:
    """`parse_content` for the admission checks: reference parts are kept as `BlobRefPart`."""
    if content is None:
        return []
    if isinstance(content, str):
        return [TextPart(content)]
    if not isinstance(content, list):
        return [TextPart(str(content))]
    parts: list[AdmittedPart] = []
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


def has_media(parts: Iterable[AdmittedPart]) -> bool:
    """Whether any part is not text."""
    return any(not isinstance(part, TextPart) for part in parts)


def check_messages(
    messages: Iterable[Any],
    *,
    provider: str,
    media_roles: frozenset[str],
    allow_remote_images: bool,
    allow_files: bool = True,
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
        # WHY the admitting parser: a reference part is judged as the inline part it stands for.
        for part in _admitted_parts(message.get("content"), provider):
            if isinstance(part, TextPart):
                continue
            part_type = "image_url" if part_kind(part) == "image" else "file"
            if role not in media_roles:
                raise UnsupportedContentPart(
                    provider=provider, part_type=part_type, reason=f"media in a {role} message"
                )
            if part_type == "file" and not allow_files:
                # WHY: some adapters (Ollama via LiteLLM) carry images but discard file parts;
                # refusing here is what keeps a PDF from vanishing behind a 200.
                raise UnsupportedContentPart(
                    provider=provider, part_type=part_type, reason="files_unsupported"
                )
            if isinstance(part, RemoteImagePart) and not allow_remote_images:
                raise UnsupportedContentPart(
                    provider=provider, part_type=part_type, reason="remote_url"
                )


_PART_MODALITY: Mapping[str, str] = {"image_url": "image", "file": "pdf"}


def check_input_modalities(messages: Iterable[Any], *, provider: str, modalities: object) -> None:
    """Refuse, before dispatch, a media part the routed model is PUBLISHED not to take (OME-1807).

    # FEATURE: the gateway modality backstop. Engine admission (OME-1803) is the primary,
    # fail-closed refusal; this catches every other caller before a paid upstream call — an
    # OpenRouter PDF to an image-only model answered 200, billed, then failed as retryable.
    # INVARIANT (owner decision A, 2026-11-02): ``modalities is None`` means unknown and admits
    # everything, exactly as before. Only published evidence refuses.
    # WHY no `parse_content`: it fails closed on part types it does not model (Anthropic
    # `thinking`, OpenAI `input_audio`), which the providers without `check_messages` carry
    # today. This judges `image_url` and `file` by type alone and leaves every other part to the
    # data:-only guard and the adapters.
    """
    if modalities is None:
        return
    published = normalize_input_modalities(modalities)
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            part_type = part.get("type")
            needed = _PART_MODALITY.get(part_type) if isinstance(part_type, str) else None
            if needed is not None and needed not in published:
                raise UnsupportedContentPart(
                    provider=provider,
                    part_type=cast("str", part_type),
                    reason=f"modality_unsupported {needed}",
                )


_UNSUPPORTED_MEDIA_TYPE = 415
_MEDIA_PART_TYPES = ("image_url", "file")


def provider_media_refusal(
    status: object, messages: object, *, provider: str
) -> UnsupportedContentPart | None:
    """The content-part refusal for a provider's 415 on a request that carries media (OME-1946).

    # WHY: a provider that answers HTTP 415 to a request with image/file parts is refusing a
    # part's media type (seen: HF router -> DeepInfra on a GIF) — the same fact the admission
    # refusals above state before dispatch, so the caller gets the same typed 422 (the Engine
    # translates it to url4 `intent_error`) instead of a generic `provider_error`.
    # INVARIANT: only a 415, and only with at least one `image_url`/`file` part; anything else
    # returns None and keeps the existing mapping. Never raises on malformed messages.
    # WHY no upstream text in `reason`: it is provider-influenced; the reason names only the
    # request's own MIME types (distinct, request order). A remote image's MIME is unknown.
    # The upstream does not say WHICH part it refused, so `part_type` is the first media part's.
    """
    if type(status) is not int or status != _UNSUPPORTED_MEDIA_TYPE:
        return None
    part_types: list[str] = []
    mimes: list[str] = []
    for part in _media_parts(messages):
        part_type = cast("str", part["type"])
        part_types.append(part_type)
        mime = _declared_mime(part, part_type)
        if mime is not None and mime not in mimes:
            mimes.append(mime)
    if not part_types:
        return None
    reason = "provider_unsupported_media"
    if mimes:
        reason = f"{reason} {','.join(mimes)}"
    return UnsupportedContentPart(provider=provider, part_type=part_types[0], reason=reason)


def _media_parts(messages: object) -> Iterable[Mapping[str, Any]]:
    if not isinstance(messages, list):
        return
    for message in cast("list[object]", messages):
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            continue
        for part in cast("list[object]", content):
            if isinstance(part, Mapping) and part.get("type") in _MEDIA_PART_TYPES:
                yield cast("Mapping[str, Any]", part)


def _declared_mime(part: Mapping[str, Any], part_type: str) -> str | None:
    """The MIME a media part declares: its `data:` header, or a reference's ``x_media_type``."""
    value = part.get(part_type)
    if part_type == "image_url":
        raw = value.get("url") if isinstance(value, Mapping) else value
    else:
        raw = value.get("file_data") if isinstance(value, Mapping) else None
    if isinstance(raw, str) and raw.startswith(BLOB_REFERENCE_PREFIX):
        declared = part.get("x_media_type")
        return declared.lower() if isinstance(declared, str) else None
    inline = parse_data_uri(raw) if isinstance(raw, str) else None
    return inline.mime if inline is not None else None


def part_kind(part: MediaPart | RemoteImagePart | BlobRefPart) -> Literal["image", "file"]:
    """Whether a media part is an image or a file (a PDF)."""
    return "image" if isinstance(part, RemoteImagePart) else part.kind


def parse_blob_reference(item: Mapping[str, Any], *, provider: str) -> BlobRefPart | None:
    """The reference part ``item`` is, ``None`` for any other part, or a typed 422 (OME-1970).

    The wire shape is the inline part's, with the reference where the ``data:`` URI stands:

        {"type": "image_url", "image_url": {"url": "blob:sha256/<64 hex>", "detail": "high"},
         "x_media_type": "image/png", "x_size": 7900000}
        {"type": "file", "file": {"file_data": "blob:sha256/<64 hex>", "filename": "a.pdf"},
         "x_media_type": "application/pdf", "x_size": 1200000}

    A part is a reference when that one value is a string starting ``blob:``; it is then held to
    a closed shape: 64 lowercase hex characters, ``x_media_type`` fitting the part type as an
    inline part's MIME must (``image/*``, or ``application/pdf``), ``x_size`` a positive int (the
    decoded size), and no key beyond those shown. ``blob:`` is not a URL: nothing is fetched.
    """
    declared_type = item.get("type")
    if not isinstance(declared_type, str) or declared_type not in _REFERENCE_VALUE_KEY:
        return None
    part_type: str = declared_type
    inner = item.get(part_type)
    if not isinstance(inner, Mapping):
        return None
    raw = cast("Mapping[str, Any]", inner).get(_REFERENCE_VALUE_KEY[part_type])
    if not isinstance(raw, str) or not raw.startswith("blob:"):
        return None
    kind: Literal["image", "file"] = "image" if part_type == "image_url" else "file"

    def refuse(reason: str) -> UnsupportedContentPart:
        return UnsupportedContentPart(provider=provider, part_type=part_type, reason=reason)

    match = _BLOB_REFERENCE_RE.fullmatch(raw)
    if match is None:
        raise refuse("malformed_blob_reference")
    if (
        not set(item) <= {"type", part_type, *REFERENCE_FIELDS}
        or not set(inner) <= (_REFERENCE_INNER_KEYS[part_type])
    ):
        raise refuse("blob_reference_unexpected_field")
    mime = item.get("x_media_type")
    fits = isinstance(mime, str) and (
        mime.lower().startswith("image/") if kind == "image" else mime.lower() in _FILE_MIMES
    )
    if not fits:
        raise refuse("blob_reference_x_media_type")
    size = item.get("x_size")
    # WHY `type(...) is int`: `True` is an int to `isinstance`, and is no size.
    if type(size) is not int or size <= 0:
        raise refuse("blob_reference_x_size")
    filename = inner.get("filename")
    if filename is not None and not isinstance(filename, str):
        raise refuse("blob_reference_filename")
    return BlobRefPart(
        kind=kind,
        mime=cast("str", mime).lower(),
        sha256=match["sha256"],
        size_bytes=size,
        filename=filename or None,
        detail=_image_detail(inner, provider) if kind == "image" else None,
    )


def reference_digest_of(item: object) -> str | None:
    """The SHA-256 an already-admitted reference part names, or ``None`` for any other part.

    WHY no shape check: `parse_blob_reference` held the part to its closed shape at admission;
    this only finds the part again, in the swap and the key form (`core/blob_refs.py`).
    """
    if not isinstance(item, Mapping):
        return None
    part_type = cast("Mapping[str, Any]", item).get("type")
    if not isinstance(part_type, str) or part_type not in _REFERENCE_VALUE_KEY:
        return None
    inner = cast("Mapping[str, Any]", item).get(part_type)
    raw = (
        cast("Mapping[str, Any]", inner).get(_REFERENCE_VALUE_KEY[part_type])
        if isinstance(inner, Mapping)
        else None
    )
    match = _BLOB_REFERENCE_RE.fullmatch(raw) if isinstance(raw, str) else None
    return match["sha256"] if match is not None else None


def _parse_item(item: Mapping[str, Any], provider: str) -> AdmittedPart | None:
    """One content part, typed; an unknown typed part is refused (fail closed)."""
    reference = parse_blob_reference(item, provider=provider)
    if reference is not None:
        return reference
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
        inline = parse_data_uri(url)
        if inline is not None:
            if not inline.mime.startswith("image/"):
                raise UnsupportedContentPart(
                    provider=provider,
                    part_type="image_url",
                    reason=f"unsupported_mime {inline.mime}",
                )
            return MediaPart(kind="image", mime=inline.mime, data=inline.data, detail=detail)
        scheme = remote_url_scheme(url)
        if scheme is not None:
            # WHY normalize: the scheme is case-insensitive, and the upstream gets one spelling.
            return RemoteImagePart(scheme + url[len(scheme) :], detail=detail)
    raise UnsupportedContentPart(
        provider=provider, part_type="image_url", reason="expected a base64 data URI or http(s) URL"
    )


def _image_detail(value: Any, provider: str) -> str | None:
    detail = value.get("detail") if isinstance(value, Mapping) else None
    # WHY isinstance first: `detail` is untrusted JSON; a list/dict is unhashable, and set
    # membership on it would raise TypeError (a 500) instead of the typed 422.
    if detail is None or (isinstance(detail, str) and detail in _IMAGE_DETAILS):
        return detail
    raise UnsupportedContentPart(
        provider=provider, part_type="image_url", reason=f"invalid detail {detail!r}"
    )


def _parse_file(value: Any, provider: str) -> MediaPart:
    data = value.get("file_data") if isinstance(value, Mapping) else None
    inline = parse_data_uri(data) if isinstance(data, str) else None
    if inline is None:
        # WHY: `file_id` refers to an OpenAI Files upload, and a URL would need a fetch — the
        # gateway holds neither, so only inline base64 is carried.
        raise UnsupportedContentPart(
            provider=provider, part_type="file", reason="expected base64 file_data"
        )
    if inline.mime not in _FILE_MIMES:
        raise UnsupportedContentPart(
            provider=provider, part_type="file", reason=f"unsupported_mime {inline.mime}"
        )
    filename = value.get("filename") if isinstance(value, Mapping) else None
    return MediaPart(
        kind="file",
        mime=inline.mime,
        data=inline.data,
        filename=filename if isinstance(filename, str) and filename else None,
    )


def text_only(content: Any, *, provider: str, role: str) -> str:
    """Flatten ``content`` where the provider's slot holds text only (system, tool result).

    # INVARIANT: refuses media rather than dropping it — `check_messages` normally refuses
    # first; this keeps the adapter itself from ever being the silent drop.
    """
    parts = _admitted_parts(content, provider)
    texts: list[TextPart] = []
    for part in parts:
        if not isinstance(part, TextPart):
            raise UnsupportedContentPart(
                provider=provider,
                part_type="image_url" if part_kind(part) == "image" else "file",
                reason=f"media in a {role} message",
            )
        texts.append(part)
    return text_of(texts)


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
