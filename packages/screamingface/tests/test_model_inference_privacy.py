"""MI-25 (prd/model-inference.md MI-S21, P9): no content of an inference call leaves through a
side channel.

FEATURE: SDK model inference, unit U7. The SDK sends no analytics event for an inference call,
writes no reply to disk, and no SDK log line has a message text or a header value.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from _chat_engine import (
    CHAT_PATH,
    ENGINE_URL,
    Handler,
    envelope,
    recording_client,
    reply_body,
    sse,
)
from _chat_stream import async_recording_client
from _endpoint_access import TOKEN_HEADER, challenge, hosted_client, signed_in

import screamingface as sf
from screamingface._analytics import wiring
from screamingface._analytics.core import Coordinator
from screamingface._analytics.ports import Consent
from screamingface.errors import PlanningError

PROMPT = "prompt-secret-5d1c"
REPLY = "reply-secret-8e2a"


class Store:
    def read(self) -> Consent:
        return Consent("accepted")


class Sink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    sink = Sink()
    core = Coordinator(Store(), sink, version="0.1.0")
    monkeypatch.setattr(wiring, "coordinator", lambda: core)
    return sink.events


def _calls(client: sf.Client) -> None:
    llm = sf.InferenceClient("openrouter/a", client=client)
    llm.chat.completions.create(PROMPT)
    list(llm.chat.completions.create(PROMPT, stream=True))
    llm.chat.completions.create(PROMPT, use_cache=False)
    llm.endpoint()


async def _async_calls(client: sf.AsyncClient) -> None:
    llm = sf.InferenceClient("openrouter/a", client=client)
    await llm.chat.completions.create(PROMPT)
    stream = await llm.chat.completions.create(PROMPT, stream=True)
    async for _ in stream:
        pass


def _engine(_request: httpx.Request) -> httpx.Response:
    return sse(reply_body(REPLY))


def _challenge_then_engine() -> Handler:
    """The first chat POST gets the sign-in challenge of Access; the next ones get the reply."""

    challenged = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal challenged
        if not challenged:
            challenged = True
            return challenge(request)
        return _engine(request)

    return respond


def _refuse(_request: httpx.Request) -> httpx.Response:
    return envelope(400, "recipe_invalid", message="refused")


def _files(*roots: Path) -> dict[str, int]:
    return {
        str(path): path.stat().st_size
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_no_analytics_event_is_sent(events: list[Any]) -> None:
    # WHY: the positive control proves that this fixture records events at all, so the
    # empty list below is not vacuous.
    with sf.Client(engine_url="http://localhost:9108") as control:
        with pytest.raises(TypeError):
            control.evaluate(cast(Any, []))
    assert events
    events.clear()

    requests: list[httpx.Request] = []
    async_requests: list[httpx.Request] = []

    async def _run_async() -> None:
        async with async_recording_client(_engine, async_requests) as aclient:
            await _async_calls(aclient)

    with recording_client(_engine, requests) as client:
        _calls(client)
    asyncio.run(_run_async())

    assert events == []
    assert {r.url.path for r in requests + async_requests} == {CHAT_PATH}


def test_nothing_is_written_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    tmp = tmp_path / "tmp"
    for folder in (home, work, tmp):
        folder.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    data_dir = Path(os.environ["SCREAMINGFACE_DATA_DIR"])

    # WHY: the default save_results=True is kept, so a result written to disk would be caught.
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _engine(request)

    with sf.Client(
        engine_url=ENGINE_URL,
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(record),
    ) as client:
        before = _files(home, work, tmp, data_dir)
        _calls(client)
        with sf.Client(
            engine_url=ENGINE_URL,
            scoreboard_url="http://scoreboard.test",
            http_transport=httpx.MockTransport(_refuse),
        ) as refusing:
            with pytest.raises(PlanningError):
                sf.InferenceClient("openrouter/a", client=refusing).chat.completions.create(PROMPT)
        after = _files(home, work, tmp, data_dir)

    assert requests
    assert after == before


def test_log_lines_have_no_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token, _ = signed_in(monkeypatch)
    requests: list[httpx.Request] = []
    with hosted_client(_challenge_then_engine(), requests) as client:
        _calls(client)
    with hosted_client(_refuse, []) as refusing:
        with pytest.raises(PlanningError):
            sf.InferenceClient("openrouter/a", client=refusing).chat.completions.create(PROMPT)

    records = [
        r
        for r in caplog.records
        if r.name == "screamingface" or r.name.startswith("screamingface.")
    ]
    for record in records:
        text = record.getMessage() + (record.exc_text or "")
        assert PROMPT not in text
        assert REPLY not in text
        assert token not in text
    # WHY: the token must have been on the wire, so a leak into a log line would be possible.
    assert any(r.headers.get(TOKEN_HEADER) == token for r in requests)
