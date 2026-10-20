"""Image and file parts are accepted only as `data:` URIs (OME-1542).

FEATURE: image and file input across the gateway (OME-1529). The engine resolves every reference
to inline bytes before it calls the gateway (OME-1545), so the gateway has no reason to follow one.

STORY: as the gateway operator, a caller can never make our process dial a URL of their choosing.
LiteLLM would: `http://` images for Anthropic (`convert_url_to_base64`), any `http*` image for
Ollama (`convert_to_ollama_image`), and `file_id`s starting `http(s)://` or `www.` on the OpenAI
wire (`_handle_pdf_url`). See `docs/spec/2026-10-20-harden-file-intake.md` for the survey.

INVARIANT: an `image_url` or `file` part carries a `data:` URI or is refused; any other non-text
part is refused when a URL-bearing key, at any depth, holds an `http(s)://` / `www.` reference.
Text is never inspected — a URL in prose is prose. The refusal is `content_parts`'s typed 422.

WHY a guard of its own and not `content_parts.check_messages` on every provider: that parser fails
closed on every part type it does not model, which would newly refuse what the LiteLLM-backed
providers carry today (Anthropic `thinking` blocks on replayed turns, OpenAI `input_audio`). This
refuses references and nothing else; the per-plugin `check_messages` calls are unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final, NoReturn

from .content_parts import UnsupportedContentPart

__all__ = ["refuse_remote_media"]

_HTTP_SCHEMES: Final = ("http://", "https://")
# WHY `www.`: LiteLLM's OpenAI wire treats a `file_id` starting `www.` as a URL and fetches it.
_URL_PREFIXES: Final = (*_HTTP_SCHEMES, "www.")
_TEXT_TYPES: Final = frozenset({"text", "input_text", "output_text", "refusal"})
# The keys a content part can carry a reference under, across the OpenAI, LiteLLM and Anthropic
# shapes. Text-bearing keys (`text`, `thinking`, `content` strings) are deliberately absent.
_URL_KEYS: Final = frozenset(
    {
        "url",
        "uri",
        "image_url",
        "file_url",
        "file_uri",
        "file_id",
        "file_data",
        "video_url",
        "audio_url",
    }
)
# Bounded walk: a caller's JSON can nest arbitrarily; refusing is cheaper than recursing forever.
_MAX_DEPTH: Final = 32


def refuse_remote_media(
    messages: Iterable[Any], *, provider: str, allow_remote_image_urls: bool
) -> None:
    """Raise `UnsupportedContentPart` (422) for the first non-inline media reference.

    ``allow_remote_image_urls`` relaxes `http(s)` **image** URLs only — for a provider whose
    upstream, not our process, fetches them (Codex, OME-1541). Files stay data:-only.
    """
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping):
                _check_part(part, provider, allow_remote_image_urls)


def _check_part(part: Mapping[str, Any], provider: str, allow_remote_image_urls: bool) -> None:
    part_type = part.get("type")
    if part_type in _TEXT_TYPES:
        return
    if part_type == "image_url":
        _check_image(part.get("image_url"), provider, allow_remote_image_urls)
        return
    if part_type == "file":
        _check_file(part.get("file"), provider)
        return
    label = part_type if isinstance(part_type, str) else "untyped"
    _scan(part, provider=provider, part_type=label, depth=0)


def _check_image(value: Any, provider: str, allow_remote: bool) -> None:
    url = value.get("url") if isinstance(value, Mapping) else value
    if isinstance(url, str):
        stripped = url.strip()
        if stripped.startswith("data:"):
            return
        if stripped.lower().startswith(_HTTP_SCHEMES):
            if allow_remote:
                return
            _refuse(provider, "image_url", "remote_url")
    _refuse(provider, "image_url", "not_data_uri")


def _check_file(value: Any, provider: str) -> None:
    file = value if isinstance(value, Mapping) else {}
    file_id = file.get("file_id")
    if file_id is not None:
        # WHY refuse every id: the gateway holds no Files upload, and LiteLLM FETCHES a URL-shaped
        # one. Naming the URL case `remote_url` keeps the reason honest for the caller.
        _refuse(provider, "file", "remote_url" if _is_url(file_id) else "file_id")
    data = file.get("file_data")
    if isinstance(data, str) and data.strip().startswith("data:"):
        _scan(file, provider=provider, part_type="file", depth=0, skip=frozenset({"file_data"}))
        return
    _refuse(provider, "file", "remote_url" if _is_url(data) else "not_data_uri")


def _scan(
    value: Any,
    *,
    provider: str,
    part_type: str,
    depth: int,
    skip: frozenset[str] = frozenset(),
) -> None:
    if depth > _MAX_DEPTH:
        _refuse(provider, part_type, "too_deep")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in skip:
                continue
            if key in _URL_KEYS and _is_url(nested):
                _refuse(provider, part_type, "remote_url")
            if isinstance(nested, (Mapping, list)):
                _scan(nested, provider=provider, part_type=part_type, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (Mapping, list)):
                _scan(item, provider=provider, part_type=part_type, depth=depth + 1)


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(_URL_PREFIXES)


def _refuse(provider: str, part_type: str, reason: str) -> NoReturn:
    raise UnsupportedContentPart(provider=provider, part_type=part_type, reason=reason)
