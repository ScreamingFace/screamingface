"""Test support for POST /v1/chat/completions: a scripted runner that plays a chat run's frames,
a fake model-parameter source, and an App built on create_app with an in-memory chat-input store.

Test-only, the `_chat_world` pattern. `chat_app` builds the App; `ScriptedRunner` publishes the
frames of each run onto the stream; `LookupSource` answers the model lookup; `post` sends one
request through the ASGI transport.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, cast

import httpx
from _chat_world import MemoryObjects
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.artifacts.chat_inputs import chat_input_store
from screamingface_engine.catalog.port import (
    Credential,
    ModelCatalog,
    ModelParameterResponse,
    compute_etag,
)
from screamingface_engine.chat.result import CHAT_RESULT_MEDIA_TYPE, ChatResult, encode_chat_result
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.models.registry import encode_route_id
from url4.streaming.interfaces import JobAlreadyExists, JobRunnerAtCapacity
from url4.streaming.protocol import (
    CostUsageEvent,
    ErrorInfo,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for
from url4.streaming.protocol.signals import CostUsageData, ResultArtifact
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage
from url4.streaming.trace import parse_traceparent

__all__ = [
    "EMAIL",
    "MESSAGES",
    "MODEL",
    "PATH",
    "SECRET",
    "TRACEPARENT",
    "TRACE_ID",
    "ChatApp",
    "LookupSource",
    "Receive",
    "Script",
    "ScriptedRunner",
    "ToolCatalog",
    "answered",
    "asgi_call",
    "asgi_scope",
    "body",
    "body_then",
    "chat_app",
    "chat_result",
    "client",
    "cost_frame",
    "ended",
    "error",
    "padded",
    "post",
    "result_frame",
    "sent_body",
    "sent_status",
    "stored_bytes",
    "stored_record",
    "terminated_frame",
]

PATH = "/v1/chat/completions"
EMAIL = {"X-User-Email": "caller@example.com"}
MODEL = "prov/a"
MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "Capital of France?"}]
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
_TRACE_ID = parse_traceparent(TRACEPARENT)
if _TRACE_ID is None:
    raise RuntimeError("TRACEPARENT does not parse")
TRACE_ID: str = _TRACE_ID
SECRET = "chat-route-secret-0000000000000000"

Script = Callable[[str], list[Any]]
Receive = Callable[[], Awaitable[dict[str, Any]]]


def chat_result(**fields: Any) -> ChatResult:
    """A CHAT_RESULT with the answered defaults, overridden by `fields`."""
    return ChatResult(
        **{"status": "answered", "content": "Paris", "finish_reason": "stop", **fields}
    )


def result_frame(
    topic: str,
    result: ChatResult | None = None,
    *,
    body: str | None = None,
    media_type: str | None = CHAT_RESULT_MEDIA_TYPE,
    artifact: ResultArtifact | None = None,
) -> ResultEvent:
    """The run's result frame, inline or as an artifact claim ticket."""
    if artifact is None and body is None:
        body = encode_chat_result(result or chat_result()).decode("utf-8")
    data = (
        ResultData(artifact=artifact, media_type=media_type)
        if artifact is not None
        else ResultData(body=body, media_type=media_type)
    )
    return ResultEvent(id=f"res-{topic}", source=source_for(topic), subject=topic, data=data)


def cost_frame(
    topic: str,
    *,
    scope: Literal["self", "subtree"] = "subtree",
    input_tokens: int = 30,
    output_tokens: int = 12,
    total_usd: str = "0.003",
    pricing_version: str = "v1",
    n: int = 0,
) -> CostUsageEvent:
    """A cost and usage frame for one scope of the run."""
    return CostUsageEvent(
        id=f"cost-{topic}-{n}",
        source=source_for(topic),
        subject=topic,
        data=CostUsageData(
            scope=scope,
            provider="test",
            model="test-model",
            pricing_version=pricing_version,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            cost=CostBreakdown(total_usd=Decimal(total_usd)),
        ),
    )


def terminated_frame(
    topic: str,
    status: Literal["succeeded", "failed", "stopped", "timed_out"] = "succeeded",
    *,
    code: str | None = None,
    message: str = "",
    permanent: bool = False,
    traceparent: str | None = TRACEPARENT,
) -> TerminatedEvent:
    """The run's terminal frame, with an error when `code` is given."""
    error = ErrorInfo(code=code, message=message, permanent=permanent) if code is not None else None
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        subject=topic,
        traceparent=traceparent,
        data=TerminatedData(status=status, error=error),
    )


def answered(result: ChatResult | None = None, *, cost: bool = True) -> Script:
    """A script whose run answers with `result`, after one cost frame when `cost` is set."""

    def frames(topic: str) -> list[Any]:
        head = [cost_frame(topic)] if cost else []
        return [*head, result_frame(topic, result), terminated_frame(topic)]

    return frames


def ended(
    status: Literal["succeeded", "failed", "stopped", "timed_out"],
    code: str | None = None,
    *,
    message: str = "",
    permanent: bool = False,
) -> Script:
    """A script whose run ends with `status` and no result frame."""
    return lambda topic: [
        terminated_frame(topic, status, code=code, message=message, permanent=permanent)
    ]


class ScriptedRunner:
    """Records what the App scheduled and plays `script` onto the stream for each run."""

    def __init__(
        self,
        stream: InMemoryEventStream,
        script: Script | None,
        objects: MemoryObjects,
        *,
        full: bool = False,
        retry_after_s: int | None = 42,
        queue_down: bool = False,
        conflict: bool = False,
        stop_delay_s: float = 0.0,
        stop_error: Exception | None = None,
    ) -> None:
        self._stream, self._script, self._objects = stream, script, objects
        self._full, self.retry_after_s, self._queue_down = full, retry_after_s, queue_down
        self._conflict, self._stop_delay_s = conflict, stop_delay_s
        self._stop_error = stop_error
        self.attempted: list[str] = []
        self.scheduled: list[dict[str, Any]] = []
        self.stopped: list[str] = []
        self.inputs: list[dict[str, bytes]] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        """Queues one run; plays its script onto the stream when one is set."""
        self.attempted.append(topic)
        if self._full:
            raise JobRunnerAtCapacity(4, 4, retry_after_s=self.retry_after_s)
        if self._queue_down:
            raise RunQueueUnavailable("the broker is down")
        if self._conflict:
            raise JobAlreadyExists(topic)
        self.inputs.append(dict(self._objects.objects))
        self.scheduled.append({"topic": topic, "url4": url4, "deadline_s": deadline_s, **kwargs})
        if self._script is not None:
            for frame in self._script(topic):
                await self._stream.publish(topic, frame)
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        """Records a stop; waits `stop_delay_s` first when set, then raises `stop_error` if set."""
        if self._stop_delay_s:
            await asyncio.sleep(self._stop_delay_s)
        self.stopped.append(topic)
        if self._stop_error is not None:
            raise self._stop_error

    async def exists(self, topic: str) -> bool:
        """No run exists before it is scheduled."""
        return False

    async def status(self, topic: str) -> str:
        """Every run reports as running."""
        return "running"


class LookupSource:
    """A fake model-parameter source: `known` models answer 200, the others `unknown_status`."""

    def __init__(
        self,
        known: tuple[str, ...] | set[str] = (MODEL,),
        *,
        error: Exception | None = None,
        unknown_status: int = 404,
    ) -> None:
        self.known: set[str] = set(known)
        self.error = error
        self.unknown_status = unknown_status
        self.calls: list[str] = []
        self.callers: list[str] = []

    async def fetch_model_parameters(
        self,
        credential: Credential,
        model: str,
        *,
        traceparent: str | None = None,
    ) -> ModelParameterResponse:
        """Answers one lookup, or raises the configured error."""
        self.calls.append(model)
        self.callers.append(credential.key)
        if self.error is not None:
            raise self.error
        status = 200 if model in self.known else self.unknown_status
        return ModelParameterResponse(status=status, content=b"{}")


class ToolCatalog:
    """A fake model catalogue: one row per model, in route form, with its supported parameters."""

    def __init__(
        self, supported: Mapping[str, list[str]], *, error: Exception | None = None
    ) -> None:
        self.supported = dict(supported)
        self.error = error
        self.calls: list[str] = []

    async def fetch(self, credential: Credential) -> ModelCatalog:
        """The catalogue of every caller, or the configured error."""
        self.calls.append(credential.key)
        if self.error is not None:
            raise self.error
        data = [
            {"id": encode_route_id(model), "object": "model", "supported_parameters": params}
            for model, params in self.supported.items()
        ]
        body: dict[str, object] = {"object": "list", "data": data}
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        """The fixed cache age of the fake."""
        return 60


@dataclass
class ChatApp:
    """An App built by `chat_app`, with the fakes it was built over."""

    app: Any
    runner: ScriptedRunner
    stream: InMemoryEventStream
    objects: MemoryObjects
    source: LookupSource | None


def chat_app(
    script: Script | None = None,
    *,
    chat_max_wait_s: float = 5.0,
    chat_keepalive_s: float = 15.0,
    known: tuple[str, ...] = (MODEL,),
    with_source: bool = True,
    blob_store: bool = True,
    job_runner: bool = True,
    catalog: Any = None,
    **runner_flags: Any,
) -> ChatApp:
    """An App on create_app with a scripted runner and an in-memory chat-input store.

    `catalog`, when given, replaces the App's model catalogue (the tool-support check).
    """
    stream = InMemoryEventStream()
    objects = MemoryObjects()
    runner = ScriptedRunner(stream, script, objects, **runner_flags)
    source = LookupSource(known) if with_source else None
    app = create_app(
        Settings(
            jwt_secret=SECRET, chat_max_wait_s=chat_max_wait_s, chat_keepalive_s=chat_keepalive_s
        ),
        stream=stream,
        job_runner=cast(Any, runner) if job_runner else None,
        model_parameters=source,
    )
    app.state.chat_input_store = chat_input_store(objects) if blob_store else None
    if catalog is not None:
        app.state.catalog = catalog
    return ChatApp(app, runner, stream, objects, source)


def client(app: Any) -> httpx.AsyncClient:
    """An HTTP client over the App's ASGI transport."""
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def body(
    model: str = MODEL, messages: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    """A chat completion request body with the default messages."""
    return {
        "model": model,
        "messages": messages if messages is not None else list(MESSAGES),
        **extra,
    }


def padded(payload: dict[str, Any], total_bytes: int) -> bytes:
    """A JSON object of exactly `total_bytes` bytes, padded with spaces before the closing brace."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    if len(raw) > total_bytes:
        raise ValueError("the payload is larger than total_bytes")
    return raw[:-1] + b" " * (total_bytes - len(raw)) + b"}"


async def post(
    app: Any,
    payload: dict[str, Any] | bytes,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POSTs one request to the chat route; the identity header is sent unless `headers` is set."""
    sent = dict(EMAIL) if headers is None else dict(headers)
    async with client(app) as c:
        if isinstance(payload, bytes):
            sent.setdefault("Content-Type", "application/json")
            return await c.post(PATH, content=payload, headers=sent)
        return await c.post(PATH, json=payload, headers=sent)


def error(resp: httpx.Response) -> dict[str, Any]:
    """The OpenAI error envelope's `error` object."""
    return resp.json()["error"]


def stored_bytes(snapshot: dict[str, bytes]) -> bytes:
    """The bytes of the one stored object whose key does not end with `.json`."""
    values = [data for key, data in snapshot.items() if not key.endswith(".json")]
    if len(values) != 1:
        raise AssertionError(f"expected one stored object, found {len(values)}")
    return values[0]


def stored_record(snapshot: dict[str, bytes]) -> dict[str, Any]:
    """The stored object of `snapshot`, decoded as JSON."""
    return json.loads(stored_bytes(snapshot))


def asgi_scope(content_length: int | None, *, email: bool = True) -> dict[str, Any]:
    """The ASGI scope of one JSON chat request; `content_length` None sends no length header."""
    headers = [(b"host", b"test"), (b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    if email:
        headers.append((b"x-user-email", EMAIL["X-User-Email"].encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": PATH,
        "raw_path": PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }


def body_then(raw: bytes, gone: asyncio.Event, *, more_body: bool = False) -> Receive:
    """A receive that gives `raw` once, then reports a disconnect when `gone` is set."""
    first = [True]

    async def receive() -> dict[str, Any]:
        if first[0]:
            first[0] = False
            return {"type": "http.request", "body": raw, "more_body": more_body}
        await gone.wait()
        return {"type": "http.disconnect"}

    return receive


async def asgi_call(app: Any, scope: dict[str, Any], receive: Receive) -> list[dict[str, Any]]:
    """Runs one raw ASGI request on the App; the messages that the App sent."""
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def sent_status(sent: list[dict[str, Any]]) -> int:
    """The HTTP status of a raw ASGI answer."""
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def sent_body(sent: list[dict[str, Any]]) -> dict[str, Any]:
    """The JSON body of a raw ASGI answer."""
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return json.loads(raw)
