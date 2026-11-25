"""Stages 1 to 3 of POST /v1/chat/completions: media type, body read, validation and checks.

The route declares no body parameter, so it reads the body itself with a running cap
(CC-S35) and answers each refusal in the OpenAI envelope. Each body must arrive in full within
`BODY_READ_TIMEOUT_S` (30 s) from its start (RR-S10). At most four bodies above 1,000,000 bytes
are in the read-and-parse phase at one time; such a body is parsed in a worker thread. When a
body gets its parse place, the read limit changes: the rest of the body must arrive within
`_PARSE_PLACE_READ_TIMEOUT_S` from that time. The parsed request lives only until its CHAT_INPUT
record is encoded, and the record only until its write.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError
from starlette.requests import ClientDisconnect, Request

from screamingface_engine.chat.input import (
    ChatInputTooLarge,
    chat_input_from_request,
    encode_chat_input,
)
from screamingface_engine.chat.wire import (
    AssistantMessage,
    ChatCompletionRequest,
    ChatMessage,
    FilePart,
    ImagePart,
    ToolMessage,
    UserMessage,
)
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_ignored import ignored_parameters

__all__ = [
    "BODY_READ_TIMEOUT_S",
    "LARGE_BODY_BYTES",
    "MAX_BODY_BYTES",
    "MAX_MODEL_CHARS",
    "PARSE_RETRY_AFTER_S",
    "ChatBody",
    "ParseGate",
    "check_media_type",
    "read_chat_body",
]

# WHY: RR-S10, each body has a total read limit from its start; a body that stalls gets 408.
BODY_READ_TIMEOUT_S = 30.0
MAX_BODY_BYTES = 8_000_000
LARGE_BODY_BYTES = 1_000_000
MAX_MODEL_CHARS = 32_000
PARSE_PLACES = 4
PARSE_WAIT_S = 5.0
PARSE_RETRY_AFTER_S = 5
_PARSE_PLACE_READ_TIMEOUT_S = 30.0
_JSON_MEDIA_TYPE = "application/json"
_DATA_URI = "data:"


class ParseGate:
    """At most `places` large bodies in the read-and-parse phase at one time (CC-S35)."""

    def __init__(self, places: int = PARSE_PLACES, wait_s: float = PARSE_WAIT_S) -> None:
        self._places = asyncio.Semaphore(places)
        self._wait_s = wait_s

    async def acquire(self) -> bool:
        """Take one place; False when none is free within the wait."""
        try:
            await asyncio.wait_for(self._places.acquire(), self._wait_s)
        except TimeoutError:
            return False
        return True

    def release(self) -> None:
        """Give one place back."""
        self._places.release()


class ChatBody:
    """What the later stages need from the body: the model value, the stream flags, the facts of
    the log line, and the encoded record.

    INVARIANT (CC-S35): the record is handed over once (`take_record`), so nothing holds it after
    the blob write while the request waits for its run.
    """

    __slots__ = (
        "_record",
        "digest",
        "has_tools",
        "ignored_parameters",
        "include_usage",
        "messages",
        "model",
        "size",
        "stream",
    )

    def __init__(
        self,
        model: str,
        record: bytes,
        *,
        size: int,
        messages: int,
        stream: bool,
        include_usage: bool,
        has_tools: bool,
        ignored_parameters: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.has_tools = has_tools
        self.ignored_parameters = ignored_parameters
        self.size = size
        self.messages = messages
        self.stream = stream
        self.include_usage = include_usage
        self.digest = hashlib.sha256(record).hexdigest()
        self._record: bytes | None = record

    def take_record(self) -> bytes:
        """The encoded CHAT_INPUT record; this body no longer holds it."""
        record, self._record = self._record, None
        if record is None:
            raise RuntimeError("the chat input record was already taken")
        return record


class _Place:
    """The parse place of one request: taken once, given back once."""

    def __init__(self, gate: ParseGate) -> None:
        self._gate = gate
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    async def take(self) -> None:
        if self._held:
            return
        if not await self._gate.acquire():
            raise ChatError(429, "overloaded", retry_after=PARSE_RETRY_AFTER_S, should_retry=True)
        self._held = True

    def give_back(self) -> None:
        if self._held:
            self._held = False
            self._gate.release()

    def keep_until(self, work: asyncio.Future[Any]) -> None:
        """Hold the place until `work` ends, even when the request ends first."""
        if self._held:
            self._held = False
            work.add_done_callback(self._release_after)

    def _release_after(self, work: asyncio.Future[Any]) -> None:
        if not work.cancelled():
            # WHY: marks the outcome as read, so a parse whose request was cancelled does not
            # log "exception was never retrieved".
            work.exception()
        self._gate.release()


def check_media_type(content_type: str | None) -> None:
    """CC-S34: 415 unless the media type is application/json; parameters are ignored."""
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type != _JSON_MEDIA_TYPE:
        raise ChatError(415, "unsupported_media_type")


async def read_chat_body(request: Request, gate: ParseGate) -> ChatBody:
    """Read, validate and check the body, then encode its CHAT_INPUT record."""
    place = _Place(gate)
    try:
        raw = await _capped_body(request, place)
        if not place.held:
            return _checked(raw)
        # WHY a thread: the validation and the encode of a large body block the event loop
        # (about 0.6 s for 7.5 MB). The place stays held until the parse ends, also when the
        # request is cancelled first, so at most four large parses run at one time (CC-S35).
        parse = asyncio.ensure_future(asyncio.to_thread(_checked, raw))
        place.keep_until(parse)
        return await asyncio.shield(parse)
    finally:
        place.give_back()


def _too_large(param: str | None = None) -> ChatError:
    return ChatError(413, "request_too_large", param=param)


async def _capped_body(request: Request, place: _Place) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    try:
        async with asyncio.timeout(BODY_READ_TIMEOUT_S) as limit:
            return await _read(request, place, limit)
    except TimeoutError:
        # WHY: the total read limit of each body, or the limit of a large body from its parse place
        # (RR-S10, review F9).
        raise ChatError(408, "request_timeout") from None
    except ClientDisconnect:
        # WHY not an error: the client left during the read, so no blob and no run exist yet.
        raise ChatError(499, "client_disconnected") from None


async def _read(request: Request, place: _Place, limit: asyncio.Timeout) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _too_large()
        if size > LARGE_BODY_BYTES and not place.held:
            # INVARIANT: a request that waits for a place holds at most about 1 MB (CC-S35).
            await place.take()
            # INVARIANT: a slow client cannot hold one of the 4 places for ever (review F9).
            loop = asyncio.get_running_loop()
            limit.reschedule(loop.time() + _PARSE_PLACE_READ_TIMEOUT_S)
        chunks.append(chunk)
    return b"".join(chunks)


def _checked(raw: bytes) -> ChatBody:
    ignored = ignored_parameters(raw)
    try:
        parsed = ChatCompletionRequest.model_validate_json(raw)
    except ValidationError as exc:
        # WHY from None: a validation error quotes the input, which must not reach a log.
        raise ChatError(400, "invalid_request", param=_param(exc)) from None
    if len(parsed.model) > MAX_MODEL_CHARS:
        raise _too_large("model")
    refused = _unsupported_parameter(parsed)
    if refused is not None:
        raise ChatError(400, "unsupported_parameter", param=refused)
    tool_use = _tool_use(parsed)
    if tool_use is not None:
        raise ChatError(400, "tools_not_available", param=tool_use)
    remote = _remote_part(parsed.messages)
    if remote is not None:
        raise ChatError(400, "unsupported_content", param=remote)
    try:
        record = encode_chat_input(chat_input_from_request(parsed))
    except ChatInputTooLarge:
        raise _too_large() from None
    return ChatBody(
        parsed.model,
        record,
        size=len(raw),
        messages=len(parsed.messages),
        stream=parsed.stream,
        include_usage=parsed.stream_options is not None and parsed.stream_options.include_usage,
        # INVARIANT (TC-S13): `tools: []` is no tools.
        has_tools=bool(parsed.tools),
        ignored_parameters=ignored,
    )


def _param(exc: ValidationError) -> str | None:
    """The top-level field of the first error, or None for a body that is not a JSON object."""
    errors = exc.errors()
    loc = errors[0]["loc"] if errors else ()
    return loc[0] if loc and isinstance(loc[0], str) else None


def _unsupported_parameter(request: ChatCompletionRequest) -> str | None:
    """CC-S16: the first refused field (n above 1, logprobs, an audio modality), or None."""
    refused = (
        ("n", (request.n or 1) > 1),
        ("logprobs", request.logprobs is True),
        ("modalities", "audio" in (request.modalities or [])),
        ("audio", request.audio is not None),
    )
    return next((name for name, refuse in refused if refuse), None)


def _tool_use(request: ChatCompletionRequest) -> str | None:
    """TC-S23: the first place of the request that declares or uses a tool, or None.

    WHY: tool calls are turned off for now (owner decision of 2026-11-24, prd/tool-calls.md
    section 0). This check is fixed: no setting turns it off. The tool code behind it stays, and
    no request can reach it. `tools: []` and `functions: []` declare no tool (TC-S13).
    """
    if request.tools:
        return "tools"
    if request.functions:
        return "functions"
    return next(_tool_turns(request.messages), None)


def _tool_turns(messages: list[ChatMessage]) -> Iterator[str]:
    """The place of each message that is a tool result or that has tool calls."""
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            yield f"messages[{index}]"
        elif isinstance(message, AssistantMessage) and message.tool_calls:
            yield f"messages[{index}].tool_calls"


def _remote_part(messages: list[ChatMessage]) -> str | None:
    """CC-S18: the place of the first picture or file part that is not a data: URI, or None."""
    for index, message in enumerate(messages):
        if not isinstance(message, UserMessage) or isinstance(message.content, str):
            continue
        for position, part in enumerate(message.content):
            if not _inline(part):
                return f"messages[{index}].content[{position}]"
    return None


def _inline(part: object) -> bool:
    if isinstance(part, ImagePart):
        return part.image_url.url.startswith(_DATA_URI)
    if isinstance(part, FilePart):
        return part.file.file_data.startswith(_DATA_URI)
    return True
