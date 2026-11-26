"""A mock Engine for the chat call tests: the answers, a recording client, a stream that records
its close, and a fake clock. It also holds the shared recipes and URL4 texts of the model tests.

AIDEV-NOTE: the wire bytes come from tests/_chat_frames.py, a hand copy of the Engine wire.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from _chat_frames import engine_stream, wire
from _combine_contract import ENGINE_OPERATOR_NAMES, operators_wire

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.linking import link_candidate
from screamingface._evaluation.operators import decode_operator_catalog
from screamingface._inference import transport
from screamingface.recipe import Recipe

ENGINE_URL = "http://engine.test"
CHAT_PATH = transport.CHAT_PATH

type Handler = Callable[[httpx.Request], httpx.Response]
type Part = bytes | BaseException | Callable[[], None]


def reply_body(text: str = "Hello") -> bytes:
    return wire(engine_stream({"role": "assistant", "content": text}, "stop"))


def sse(body: bytes) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def ok(_request: httpx.Request) -> httpx.Response:
    return sse(reply_body())


def envelope(
    status: int,
    code: str,
    *,
    message: str = "refused",
    param: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        json={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "code": code,
                "param": param,
            }
        },
    )


def answers(*responses: httpx.Response) -> Handler:
    """A handler that gives the responses in order."""

    queue = list(responses)

    def respond(_request: httpx.Request) -> httpx.Response:
        assert queue, "the test Engine got more requests than it has answers"
        return queue.pop(0)

    return respond


def recording_client(handler: Handler, requests: list[httpx.Request]) -> sf.Client:
    """A Client whose Engine is `handler`; every request it receives lands in `requests`."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return sf.Client(
        engine_url=ENGINE_URL,
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )


def sent_body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def trace_id_of(request: httpx.Request) -> str:
    return request.headers["traceparent"].split("-")[1]


class RecordingStream(httpx.SyncByteStream):
    """A stream that gives its parts in order and appends True to `closed` when it is closed."""

    def __init__(self, parts: list[Part], closed: list[bool]) -> None:
        self._parts = parts
        self._closed = closed

    def __iter__(self) -> Iterator[bytes]:
        for part in self._parts:
            if isinstance(part, bytes):
                yield part
            elif isinstance(part, BaseException):
                raise part
            else:
                part()

    def close(self) -> None:
        self._closed.append(True)


def streamed(parts: list[Part], closed: list[bool]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=RecordingStream(parts, closed),
    )


class FakeTime:
    """A clock that moves only when a test or the transport sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def fake_time(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(transport, "_clock", fake.clock)
    monkeypatch.setattr(transport, "_sleep", fake.sleep)
    return fake


# Shared recipes and URL4 texts of the model tests.
CATALOG = decode_operator_catalog(operators_wire(ENGINE_OPERATOR_NAMES))
CAND = compile_candidate(sf.Model("openrouter/a")).url4
BENCH = (
    "(answer:0.0:/candidate(question)!'$candidate', grade:0.0:/provider/judge($answer)!'Grade.')"
    "!'$grade'"
)
EVAL = link_candidate(CAND, BENCH).url4
BENCH_ROUTE = "(cases:0.0:/benchmarks/demo/v1/cases($input)!'Answer.')!'$cases'"
# WHY: a 'candidate' binding that is not Text is a plain binding (the Engine rule), so it is sent
# unchanged.
NOT_TEXT = "(candidate:0.0:/prov/a($input)!'x')!'$candidate'"


def catalogue_engine(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/operators":
        return httpx.Response(
            200,
            json=operators_wire(ENGINE_OPERATOR_NAMES),
            headers={"ETag": '"v1"', "Cache-Control": "public, max-age=300, must-revalidate"},
        )
    return ok(request)


def model() -> Recipe:
    return sf.Model("openrouter/a")


def fusion() -> Recipe:
    return sf.Fanout(["openrouter/a", "openrouter/b"]) >> sf.Synthesize("openrouter/c")


def pipeline() -> Recipe:
    return sf.Pipeline(["openrouter/a", "openrouter/b"], name="p")


def vote() -> Recipe:
    return sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote()


def gate() -> Recipe:
    return sf.Fanout(["prov/a", "prov/b"], name="vote") >> sf.Gate(
        when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise="prov/large"
    )


def cascade() -> Recipe:
    return sf.Cascade("prov/a", sf.escalate_if(sf.unanswered()), "prov/b")


def self_corrective() -> Recipe:
    return sf.SelfCorrective("provider/a")


def corrective_loop() -> Recipe:
    return sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j")
