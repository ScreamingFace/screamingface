"""E14 F-B3 — `X-Capture` and `X-Replay-Frozen-Copy` reach the run, and the start route echoes them.

FEATURE: OME-1307 (design §5.1). The two headers travel exactly as `X-Answer-Seed` does: header
(sync surface and start route) -> job env -> the run's request scope. `X-Capture: true` is
capture mode; `X-Replay-Frozen-Copy: <uuid>` is replay mode; both at once is a 400
`malformed_header`, and so is a replay value that is not a UUID. The start response echoes the
header that was accepted, which is how an SDK talking to an older engine can tell it was ignored.

A separate module (append-only gate).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from frozen_copy_support import COPY
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.request_scope import (
    CAPTURE_HEADER,
    REPLAY_FROZEN_COPY_HEADER,
    FrozenCopyHeaderError,
    frozen_copy_mode_from_headers,
)
from screamingface_engine.runner.main import RunnerConfigError, request_scope_from_env
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import (
    CachePolicy,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)

_BAD_COPIES = [
    "garbage",
    "6F1C2B0E-4C0A-4D7E-9A53-2F4F0F3A9B11",
    "6f1c2b0e4c0a4d7e9a532f4f0f3a9b11",
    "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b1",
    "{6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11}",
    "cr-0123456789ab",
]
_BAD_CAPTURES = ["false", "1", "yes", "True?"]

SECRET = "frozen-copy-header-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)


# ── the header reader (the start route's one reader) ───────────────────────────────────────


def test_the_reader_reads_the_capture_header() -> None:
    assert frozen_copy_mode_from_headers("true", None) == (True, None)


def test_the_reader_reads_the_replay_header() -> None:
    assert frozen_copy_mode_from_headers(None, COPY) == (False, COPY)


def test_the_reader_accepts_true_in_any_case_with_blanks() -> None:
    assert frozen_copy_mode_from_headers(" TRUE ", None) == (True, None)


@pytest.mark.parametrize("raw", [(None, None), ("  ", " "), ("", "")])
def test_no_header_or_a_blank_one_is_a_normal_run(raw: tuple[str | None, str | None]) -> None:
    assert frozen_copy_mode_from_headers(*raw) == (False, None)


@pytest.mark.parametrize("value", _BAD_COPIES)
def test_a_malformed_replay_header_is_a_loud_refusal(value: str) -> None:
    with pytest.raises(FrozenCopyHeaderError):
        frozen_copy_mode_from_headers(None, value)


@pytest.mark.parametrize("value", _BAD_CAPTURES)
def test_a_capture_header_that_is_not_true_is_a_loud_refusal(value: str) -> None:
    with pytest.raises(FrozenCopyHeaderError):
        frozen_copy_mode_from_headers(value, None)


def test_both_headers_at_once_is_a_loud_refusal() -> None:
    with pytest.raises(FrozenCopyHeaderError):
        frozen_copy_mode_from_headers("true", COPY)


# ── the job env ────────────────────────────────────────────────────────────────────────────


def test_the_job_env_keys_are_declared_and_written_by_the_app() -> None:
    assert job_env.CAPTURE == "URL4_CLOUD_CAPTURE"
    assert job_env.REPLAY_FROZEN_COPY == "URL4_CLOUD_REPLAY_FROZEN_COPY"
    assert {job_env.CAPTURE, job_env.REPLAY_FROZEN_COPY} <= job_env.WRITTEN_BY_APP


def test_an_undeclared_mode_renders_nothing() -> None:
    assert job_env.capture_env(False) == {}
    assert job_env.replay_frozen_copy_env(None) == {}


def test_a_mode_round_trips_through_the_env() -> None:
    capture = job_env.capture_env(True)
    replay = job_env.replay_frozen_copy_env(COPY)

    assert capture == {"URL4_CLOUD_CAPTURE": "1"}
    assert replay == {"URL4_CLOUD_REPLAY_FROZEN_COPY": COPY}
    assert job_env.capture_from_env(capture) is True
    assert job_env.replay_frozen_copy_from_env(replay) == COPY


def test_an_absent_env_key_is_a_normal_run() -> None:
    assert job_env.capture_from_env({}) is False
    assert job_env.replay_frozen_copy_from_env({}) is None


@pytest.mark.parametrize("value", _BAD_COPIES + [""])
def test_a_malformed_replay_env_value_raises(value: str) -> None:
    with pytest.raises(ValueError, match="URL4_CLOUD_REPLAY_FROZEN_COPY"):
        job_env.replay_frozen_copy_from_env({job_env.REPLAY_FROZEN_COPY: value})


@pytest.mark.parametrize("value", ["true", "0", "", "yes"])
def test_a_malformed_capture_env_value_raises(value: str) -> None:
    with pytest.raises(ValueError, match="URL4_CLOUD_CAPTURE"):
        job_env.capture_from_env({job_env.CAPTURE: value})


def test_the_run_producer_reads_the_modes_into_the_scope() -> None:
    capture = request_scope_from_env(job_env.capture_env(True))
    replay = request_scope_from_env(job_env.replay_frozen_copy_env(COPY))

    assert (capture.capture, capture.replay_frozen_copy) == (True, None)
    assert (replay.capture, replay.replay_frozen_copy) == (False, COPY)


def test_a_run_without_the_env_keys_is_a_normal_run() -> None:
    scope = request_scope_from_env({})

    assert (scope.capture, scope.replay_frozen_copy) == (False, None)


@pytest.mark.parametrize(
    "env",
    [
        {job_env.REPLAY_FROZEN_COPY: "garbage"},
        {job_env.CAPTURE: "true"},
        {job_env.CAPTURE: "1", job_env.REPLAY_FROZEN_COPY: COPY},
    ],
    ids=["bad-uuid", "bad-capture", "both"],
)
def test_a_malformed_or_conflicting_env_refuses_the_run(env: dict[str, str]) -> None:
    with pytest.raises(RunnerConfigError, match="URL4_CLOUD_"):
        request_scope_from_env(env)


# ── the two job-runner renderings ──────────────────────────────────────────────────────────


class _NeverExecutor(Executor):
    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> Any:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield ExecStep  # pragma: no cover


def _inprocess_env(
    *,
    capture: bool = False,
    replay_frozen_copy: str | None = None,
    base: Mapping[str, str] | None = None,
) -> dict:
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        base_env=base,
    )
    return runner._env(  # noqa: SLF001
        "topic-a",
        "'hi'!'go'",
        60,
        None,
        None,
        CachePolicy(),
        capture=capture,
        replay_frozen_copy=replay_frozen_copy,
    )


def test_the_queue_message_carries_the_mode_and_an_absent_one_adds_nothing() -> None:
    capture = decode_message(encode_message("t", "'hi'", 60, capture=True))
    replay = decode_message(encode_message("t", "'hi'", 60, replay_frozen_copy=COPY))
    plain = decode_message(encode_message("t", "'hi'", 60))

    assert capture[job_env.CAPTURE] == "1"
    assert replay[job_env.REPLAY_FROZEN_COPY] == COPY
    assert job_env.CAPTURE not in plain
    assert job_env.REPLAY_FROZEN_COPY not in plain


def test_the_inprocess_env_carries_the_mode() -> None:
    assert _inprocess_env(capture=True)[job_env.CAPTURE] == "1"
    assert _inprocess_env(replay_frozen_copy=COPY)[job_env.REPLAY_FROZEN_COPY] == COPY


def test_an_ambient_mode_never_reaches_a_run_that_declared_none() -> None:
    # `_base_env` is shared by every local run: a leftover value would turn the next caller's
    # normal run into a capture or a replay.
    env = _inprocess_env(base={job_env.CAPTURE: "1", job_env.REPLAY_FROZEN_COPY: COPY})

    assert job_env.CAPTURE not in env
    assert job_env.REPLAY_FROZEN_COPY not in env


# ── the start route ────────────────────────────────────────────────────────────────────────


class _ModeRecordingRunner(RecordingJobRunner):
    """Records the mode the route hands the port. A subclass, as `_fakes` asks."""

    def __init__(self) -> None:
        super().__init__()
        self.modes: list[tuple[bool, str | None]] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        self.modes.append((kwargs.pop("capture", False), kwargs.pop("replay_frozen_copy", None)))
        return await super().schedule(topic, url4, deadline_s, **kwargs)


async def _start(
    runner: RecordingJobRunner,
    topic: str,
    *,
    prefer: str = "respond-async",
    stream: InMemoryEventStream | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    app: FastAPI = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=stream or InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": JwtCodec(
                    secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
                ).sign(topic, T0),
                "Prefer": prefer,
                **(headers or {}),
            },
        )


_MODES = [
    ({CAPTURE_HEADER: "true"}, (True, None)),
    ({REPLAY_FROZEN_COPY_HEADER: COPY}, (False, COPY)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("headers", "mode"), _MODES, ids=["capture", "replay"])
async def test_headers_travel_header_env_scope_and_the_start_response_echoes_them(
    headers: dict[str, str], mode: tuple[bool, str | None]
) -> None:
    runner = _ModeRecordingRunner()

    resp = await _start(runner, "mode-ok", headers=headers)

    assert resp.status_code == 202
    for name, value in headers.items():
        assert resp.headers[name] == value
    # The mode the run was scheduled with is the one echoed: one decision, made before the run.
    assert runner.modes == [mode]


@pytest.mark.asyncio
async def test_a_start_without_the_headers_carries_no_ack_and_no_mode() -> None:
    runner = _ModeRecordingRunner()

    resp = await _start(runner, "mode-absent")

    assert resp.status_code == 202
    assert CAPTURE_HEADER not in resp.headers
    assert REPLAY_FROZEN_COPY_HEADER not in resp.headers
    assert runner.modes == [(False, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [{REPLAY_FROZEN_COPY_HEADER: value} for value in _BAD_COPIES]
    + [{CAPTURE_HEADER: value} for value in _BAD_CAPTURES]
    + [{CAPTURE_HEADER: "true", REPLAY_FROZEN_COPY_HEADER: COPY}],
)
async def test_a_bad_or_conflicting_header_is_a_400_and_nothing_is_scheduled(
    headers: dict[str, str],
) -> None:
    runner = _ModeRecordingRunner()

    resp = await _start(runner, "mode-bad", headers=headers)

    assert resp.status_code == 400
    assert resp.json()["code"] == "malformed_header"
    assert runner.modes == []
    assert runner.scheduled == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("headers", "mode"), _MODES, ids=["capture", "replay"])
async def test_the_sync_hold_fallback_echoes_the_header_too(
    headers: dict[str, str], mode: tuple[bool, str | None]
) -> None:
    # `Prefer: wait=0` makes the sync hold give up at once: the 202 fallback is also a start
    # response, and it must carry the same acknowledgement.
    resp = await _start(_ModeRecordingRunner(), "mode-sync", prefer="wait=0", headers=headers)

    assert resp.status_code == 202
    for name, value in headers.items():
        assert resp.headers[name] == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [{CAPTURE_HEADER: "true"}, {REPLAY_FROZEN_COPY_HEADER: COPY}, {}],
    ids=["capture", "replay", "normal"],
)
async def test_a_finished_sync_run_echoes_the_header_only_for_a_mode(
    headers: dict[str, str],
) -> None:
    topic = "mode-finished"
    stream = InMemoryEventStream()
    await stream.publish(
        topic,
        ResultEvent(
            id="res",
            source=f"/trace/{topic}/node/root",
            subject=topic,
            data=ResultData(body="{}", media_type="application/json"),
        ),
    )
    await stream.publish(
        topic,
        TerminatedEvent(
            id="term",
            source=f"/trace/{topic}/node/root",
            subject=topic,
            data=TerminatedData(status="succeeded"),
        ),
    )

    resp = await _start(_ModeRecordingRunner(), topic, prefer="", stream=stream, headers=headers)

    assert resp.status_code == 200
    for name in (CAPTURE_HEADER, REPLAY_FROZEN_COPY_HEADER):
        assert resp.headers.get(name) == headers.get(name)
