# pyright: reportMissingImports=false
# WHY file-level: the capture path imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A Case whose prompt holds pictures, saved with the pictures inside it (OME-1271).

FEATURE: Task replay captures what the eval's own solvers hand the model at their first
``generate``. Some evals hand it pictures (LAB-Bench FigQA: one figure, then the question).
Think of it as stapling the photo to the exam paper: the Case input becomes the v2
candidate-input envelope, each picture inline as a ``data:`` URI (RFC 2397), so every run
serves the picture in place and nothing is ever fetched or read from disk again.

Stages, in execution order (``picture_case_text``):

    Stage 1 — any picture at all? A Case whose parts are all text is not this module's: the
              caller writes it exactly as before, so no text Benchmark changes.
    Stage 2 — the shape: only text and pictures; pictures only in a user message; and the
              one-prompt shape, leading system messages then one user message. Anything else
              is refused by name.
    Stage 3 — the parts, in inspect's order: the system text first, as its own text part
              (the fold a text Case makes, since a Benchmark cannot address the Candidate's
              system role), then the user message's text and pictures as inspect left them.
              Each picture's bytes come from its ``data:`` URI, or from a file the eval wrote
              into this import's own cache, and its type is read from the bytes, not from
              the label.
    Stage 4 — the limits: at most 20 pictures; each picture under the hosts' floor (5 MiB
              of base64, 8000 px a side, 30,000 patches of 32 px), read from its header without
              decoding a pixel; and 8 MB for the whole Case with its pictures inline. WHY a
              limit per picture now: OpenRouter picks the host for each call, and the
              smallest host refuses a picture the Case limit lets through (OME-1970; this
              reverses the 2026-10-26 "no limit per picture" decision).
    Stage 5 — seal the envelope and read it back with the shared parser, so a Case the
              importer writes is always one the connector and the scorer can open.

Example: FigQA's figure, which inspect_evals labels ``image/jpeg`` without looking (its
bytes decide the type), then the question rendered by ``multiple_choice`` →
``{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":[
{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,/9j/4AAQ…"}},
{"type":"text","text":"Answer the following multiple choice question. …"}]}]}``.

INVARIANT: a Case this module cannot carry fails the import, naming the Case and the reason;
it is never dropped (the Case count is part of the published score's denominator), and a
refusal never quotes a URL, a path or the picture's bytes.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    ContentPart,
    ImageDetail,
    ImagePart,
    ImageUrl,
    PartsMessage,
    TextPart,
    parse_candidate_input,
)
from screamingface_engine_inspect.conversation_input import picture_case_input
from screamingface_engine_inspect.picture_size import picture_size
from screamingface_engine_inspect.prepare import PrepareError

if TYPE_CHECKING:
    from inspect_ai.model import ChatMessage, Content, ContentImage

#: The most bytes one Case input may take with its pictures inline: 8 MB, which leaves room
#: under the gateway's 8 MiB request cap for the rest of a request
#: (``test_picture_case_limits_fit_the_gateway.py``). MMMU's largest Case is 3.78 MB.
MAX_CASE_BYTES: int = 8_000_000
#: The most pictures one Case may carry.
MAX_PICTURES: int = 20

# FEATURE: the hosts' floor (OME-1970) — a sealed Case passes on every host OpenRouter can pick.
#: The most base64 text one picture may take: 5 MiB. Amazon Bedrock, which OpenRouter can pick
#: for any Claude call, counts the base64 text, not the file (probed 24 and 26 Nov 2026:
#: "image exceeds 5 MB maximum: 5599764 bytes > 5242880 bytes"), so about 3.93 MB of file.
MAX_PICTURE_BASE64_BYTES: int = 5 * 1024 * 1024
#: The longest side one picture may have. Claude's documented limit on every route
#: (https://platform.claude.com/docs/en/build-with-claude/vision); HLE's Case 250, 14950 px wide,
#: failed on every Claude Candidate on 6 Nov 2026 with a provider 400.
MAX_PICTURE_SIDE_PX: int = 8000
#: The side of one GPT patch, the square GPT cuts a picture into before counting it.
PICTURE_PATCH_SIDE_PX: int = 32
#: The most patches one picture may take: GPT's limit. GPT-6 Astra Pro refused HLE's Case 250
#: (14950 × 2780 px) on 6 Nov 2026: "requires 40716 patches ... exceeding the limit of 30000",
#: and 40,716 is ⌈14950/32⌉ × ⌈2780/32⌉ = 468 × 87, so each side rounds up to a whole patch.
#: WHY patches, not pixels: a pixel budget (30,000 × 32 × 32) lets 7985 × 3847 px through,
#: 30,718,295 pixels but 250 × 121 = 30,250 patches, which GPT refuses.
MAX_PICTURE_PATCHES: int = 30_000

#: How system text joins the prompt, the same blank line a text Case folds it with.
#: AIDEV-NOTE: twin of capture.py's ``_MESSAGE_SEPARATOR``; capture imports this module, so they
#: cannot share one constant. Change both together, or the fold differs by Case kind.
_SYSTEM_SEPARATOR: str = "\n\n"

#: The leading bytes of each picture type the envelope accepts, checked in order.
#: WHY bytes, not inspect's label: inspect_evals labels every FigQA figure image/jpeg and
#: every TableQA table image/png without looking, and a provider can reject a picture whose
#: label does not match its bytes.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
#: WebP is a RIFF file whose form type, at bytes 8 to 12, is WEBP.
_WEBP_RIFF: bytes = b"RIFF"
_WEBP_FORM: bytes = b"WEBP"

#: inspect's detail values the envelope keeps; ``auto`` is inspect's default and the
#: provider's, so it is left out.
_KEPT_DETAILS: frozenset[str] = frozenset({"low", "high"})


class PictureCaseError(PrepareError):
    """A Case's pictures break a rule the envelope or the limits set. Names the Case."""


def picture_case_text(messages: Sequence[ChatMessage], case_id: int) -> str | None:
    """The v2 envelope for messages that hold a picture, or ``None`` when every part is text.

    ``messages`` is what the eval's solvers handed the model; ``case_id`` names the Case in a
    refusal. See the module docstring for the stages.

    Raises:
        PictureCaseError: the messages hold something a Case cannot carry, or are over a limit.
    """

    # Stage 1 — any picture at all?
    if all(
        part.type == "text"
        for message in messages
        if not isinstance(message.content, str)
        for part in message.content
    ):
        return None

    # Stage 2 — the shape.
    system_count: int = _one_prompt_system_count(messages, case_id)

    # Stage 3 — the parts, in inspect's order.
    parts: list[ContentPart] = []
    system_text: str = _SYSTEM_SEPARATOR.join(message.text for message in messages[:system_count])
    if system_text:
        parts.append({"type": "text", "text": system_text})
    parts.extend(_user_parts(messages[-1], case_id))

    # Stages 4 and 5 — the limits, then read it back with the shared parser.
    return _sealed_within_limits(parts, case_id)


def _one_prompt_system_count(messages: Sequence[ChatMessage], case_id: int) -> int:
    """Stage 2 — how many system messages lead the one user message, after refusing every
    shape a picture Case cannot take."""

    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    for message in messages:
        for part in [] if isinstance(message.content, str) else message.content:
            if part.type not in ("text", "image"):
                _refuse(
                    case_id,
                    f"a {message.role} message carries a {part.type} part; a Case carries text "
                    "and pictures only",
                )
            # WHY user only: Anthropic's OAuth route drops non-text parts from system
            # messages (spec §1), so the envelope takes pictures in user messages only.
            if part.type == "image" and not isinstance(message, ChatMessageUser):
                _refuse(
                    case_id,
                    f"a picture is in a {message.role} message; pictures go in the user message "
                    "only",
                )
    system_count: int = 0
    while system_count < len(messages) and isinstance(messages[system_count], ChatMessageSystem):
        system_count += 1
    if len(messages) != system_count + 1:
        roles: str = ", ".join(message.role for message in messages)
        _refuse(
            case_id,
            f"a picture is inside a conversation ({roles}); a picture Case is leading system "
            "text, then one user message",
        )
    return system_count


def _user_parts(user: ChatMessage, case_id: int) -> list[ContentPart]:
    """Stage 3 — the user message's text and pictures, in the order inspect left them."""

    content: str | list[Content] = user.content
    # WHY an assert: Stage 1 found a part that is not text, Stage 2 allows it only as a
    # picture in a user message, and the one message after the system ones is that message.
    assert not isinstance(content, str)
    # WHY count first: a Case with a hundred pictures is refused before any is decoded.
    count: int = sum(part.type != "text" for part in content)
    if count > MAX_PICTURES:
        _refuse(case_id, f"{count} pictures; a Case carries at most {MAX_PICTURES}")
    parts: list[ContentPart] = []
    pictures: int = 0
    for part in content:
        if part.type == "text":
            if not part.text.strip():
                _refuse(case_id, "a text part of the user message is empty")
            parts.append(TextPart(type="text", text=part.text))
            continue
        pictures += 1
        parts.append(_picture_part(cast("ContentImage", part), case_id, pictures))
    return parts


def _sealed_within_limits(parts: list[ContentPart], case_id: int) -> str:
    """Stages 4 and 5 — the envelope, refused over the Case limit or when the shared parser
    would not open it."""

    case_message: PartsMessage = {"role": "user", "content": parts}
    text: str = picture_case_input([case_message])
    size: int = len(text.encode("utf-8"))
    if size > MAX_CASE_BYTES:
        _refuse(
            case_id,
            f"the Case is {size:,} bytes with its pictures inline; the limit is {MAX_CASE_BYTES:,}",
        )
    try:
        parse_candidate_input(text)
    except CandidateInputError as exc:
        _refuse(case_id, f"the picture Case breaks the envelope's rules: {exc}")
    return text


def _picture_part(image: ContentImage, case_id: int, number: int) -> ImagePart:
    """One picture as an envelope part: its bytes inline, typed by their signature.

    ``number`` counts the Case's pictures from 1, for the refusal.
    """

    data: bytes = _picture_bytes(image.image, case_id, number)
    media_type: str | None = _media_type(data)
    if media_type is None:
        _refuse(case_id, f"picture {number} is not a PNG, JPEG, GIF or WebP")
    encoded: str = base64.b64encode(data).decode("ascii")
    _within_picture_floor(encoded, picture_size(data), case_id, number)
    image_url: ImageUrl = {"url": f"data:{media_type};base64,{encoded}"}
    if image.detail == "original":
        _refuse(
            case_id,
            f"picture {number} asks for detail original; the envelope takes auto, low or high",
        )
    if image.detail in _KEPT_DETAILS:
        image_url["detail"] = cast(ImageDetail, image.detail)
    return {"type": "image_url", "image_url": image_url}


def _picture_bytes(source: str, case_id: int, number: int) -> bytes:
    """The picture's bytes, from its ``data:`` URI or a file in this import's own cache.

    e.g. ``data:image/jpeg;base64,iVBORw0KGgo=`` → the 8 bytes of a PNG signature;
    ``/tmp/task-replay-import-x/cache/inspect_evals/mmmu/validation_1.png`` → that file's bytes.
    """

    if source.startswith("data:"):
        header, comma, payload = source.partition(",")
        if not comma or not header.endswith(";base64"):
            _refuse(case_id, f"picture {number} is a data: URI that is not base64")
        try:
            return base64.b64decode(payload, validate=True)
        except binascii.Error:
            _refuse(case_id, f"picture {number} is not valid base64")
    if "://" in source:
        _refuse(
            case_id,
            f"picture {number} is given by URL; a Case carries its pictures inline, and building "
            "one never fetches",
        )
    root: Path | None = _import_cache_root()
    path: Path = Path(source).resolve()
    if root is None or not path.is_relative_to(root.resolve()):
        _refuse(case_id, f"picture {number} is a file outside the import's cache")
    if not path.is_file():
        _refuse(case_id, f"picture {number} names a file that is not there")
    return path.read_bytes()


def _import_cache_root() -> Path | None:
    """This import's fresh cache folder, or ``None`` outside an import.

    WHY the parent of ``INSPECT_EVALS_CACHE_DIR``: the import child's environment points that
    variable, like every other cache it reads, at a folder directly under one new temporary
    cache root (``replay_environment`` in ``task_replay.py``, pinned by
    ``test_the_replay_cache_root_is_the_parent_of_inspect_evals_cache``). A picture file under
    that root was written by this import, so it is never a file from the builder's disk.
    """

    evals_cache: str | None = os.environ.get("INSPECT_EVALS_CACHE_DIR")
    return Path(evals_cache).parent if evals_cache else None


def picture_patches(width: int, height: int) -> int:
    """How many 32 px patches GPT counts for a picture, each side rounded up to a whole patch.

    e.g. HLE's knot picture, 14950 × 2780 px → 468 × 87 = 40,716 patches, the number GPT's
    refusal quoted; 8000 × 3840 → 250 × 120 = 30,000, exactly the limit.
    """

    across: int = -(-width // PICTURE_PATCH_SIDE_PX)
    down: int = -(-height // PICTURE_PATCH_SIDE_PX)
    return across * down


def _within_picture_floor(
    encoded: str, size: tuple[int, int] | None, case_id: int, number: int
) -> None:
    """Stage 4 — refuse one picture over any host's floor, naming the limit it breaks.

    e.g. Case 4's figure, 5,530,200 bytes of base64 → "picture 1 is 5,530,200 bytes as base64;
    a picture carries at most 5,242,880"; HLE's knot picture, 14950 × 2780 px → over 8000 px.
    """

    if len(encoded) > MAX_PICTURE_BASE64_BYTES:
        _refuse(
            case_id,
            f"picture {number} is {len(encoded):,} bytes as base64; a picture carries at most "
            f"{MAX_PICTURE_BASE64_BYTES:,}",
        )
    # WHY a header we cannot read passes: the seal names a type from its signature and never
    # decodes the picture (the provider does), so an unreadable header carries no size to check.
    if size is None:
        return
    width, height = size
    if max(width, height) > MAX_PICTURE_SIDE_PX:
        _refuse(
            case_id,
            f"picture {number} is {width} × {height} px; a side is at most {MAX_PICTURE_SIDE_PX}",
        )
    patches: int = picture_patches(width, height)
    if patches > MAX_PICTURE_PATCHES:
        _refuse(
            case_id,
            f"picture {number} is {width} × {height} px, {patches:,} patches of "
            f"{PICTURE_PATCH_SIDE_PX} px; a picture takes at most {MAX_PICTURE_PATCHES:,}",
        )


def _media_type(data: bytes) -> str | None:
    """The picture type the bytes start with, or ``None`` when they are none of the four."""

    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data.startswith(_WEBP_RIFF) and data[8:12] == _WEBP_FORM:
        return "image/webp"
    return None


def _refuse(case_id: int, detail: str) -> NoReturn:
    """Stop the import with the rule this Case's pictures broke."""

    raise PictureCaseError(f"case {case_id}: {detail}")


__all__ = [
    "MAX_CASE_BYTES",
    "MAX_PICTURES",
    "MAX_PICTURE_BASE64_BYTES",
    "MAX_PICTURE_PATCHES",
    "MAX_PICTURE_SIDE_PX",
    "PICTURE_PATCH_SIDE_PX",
    "PictureCaseError",
    "picture_patches",
    "picture_case_text",
]
