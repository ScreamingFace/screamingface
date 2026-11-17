"""OME-1909 — a re-grade replays a pinned run but sends the named Cases' judge calls live.

FEATURE: OME-1909. A replay run (`X-Replay-Frozen-Copy`) answers every model call from the sealed
frozen copy. `X-Replay-Live-Judge` (`all`, or a comma list of Case ids) rides the same path —
header -> job env -> the run's request scope — and makes the connector send a GRADING call for a
named Case to the provider instead. A Candidate call always replays: a re-grade makes no Candidate
model call. Without the header, every judge call replays too.

STORY: as a maintainer who bumped a Benchmark's grading, I re-grade a published run from its
pinned cache, paying only for the judge calls of the Cases I name.

A separate module (append-only gate). The end-to-end judged-recipe cases need the inspect extra,
so they live in `tests/unit/inspect/test_replay_live_judge_recipe.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from frozen_copy_support import (
    CHAT,
    COPY,
    REPLAY_CHAT,
    Gateway,
    chat,
    replay_scope,
    run_call,
)
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.config import Settings
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine.job_env import LiveJudge
from screamingface_engine.request_scope import (
    REPLAY_FROZEN_COPY_HEADER,
    REPLAY_LIVE_JUDGE_HEADER,
    FrozenCopyHeaderError,
    RequestScope,
    parse_live_judge,
)
from screamingface_engine.runner.main import RunnerConfigError, request_scope_from_env
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import CachePolicy

# The gateway answers a live call and a replayed call with different text, so the answer alone
# says which route served it; the recorded paths say it a second way.
LIVE_ANSWER = "a fresh judge reply"
RECORDED_ANSWER = "the pinned reply"

SECRET = "replay-live-judge-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 11, 17, 9, 0, 0, tzinfo=UTC)


def _gateway() -> Gateway:
    """A gateway whose live route and replay route answer with telling text."""
    return Gateway([chat(LIVE_ANSWER)], replay_steps=[chat(RECORDED_ANSWER)])


async def _call_as_judge_of(case: int | str, live: LiveJudge | None) -> tuple[Gateway, str | None]:
    """One model call made while Case ``case`` is being graded, in a replay run."""
    gateway: Gateway = _gateway()
    with grading_call_scope(case):
        _tally, answer, failure = await run_call(
            gateway, replay_scope(replay_live_judge=live), web_search=False
        )
    assert failure is None
    return gateway, answer


# ── the header reader ──────────────────────────────────────────────────────────────────────


def test_the_reader_reads_all_or_a_list_of_case_ids() -> None:
    assert parse_live_judge(None, COPY) is None
    assert parse_live_judge("all", COPY) == "all"
    # Blanks around each id are trimmed; a Case id is compared as text, as `str(case)`.
    assert parse_live_judge(" 3, q-9 ", COPY) == frozenset({"3", "q-9"})


@pytest.mark.parametrize("raw", ["7", "all"])
def test_live_judge_without_a_replay_is_refused(raw: str) -> None:
    # Outside a replay every call is live already, so the header would mean nothing — and a caller
    # who sent it believes the run is a re-grade. Refused, never ignored.
    with pytest.raises(FrozenCopyHeaderError, match=REPLAY_LIVE_JUDGE_HEADER):
        parse_live_judge(raw, None)


@pytest.mark.parametrize("raw", ["", "  ", ",", " , ", "3,,4", "3,"])
def test_a_blank_live_judge_list_is_refused(raw: str) -> None:
    # WHY presence counts here (unlike the other optional headers): an SDK that joined an empty
    # list sends "", and reading that as "no live judge" would quietly re-grade nothing.
    with pytest.raises(FrozenCopyHeaderError, match=REPLAY_LIVE_JUDGE_HEADER):
        parse_live_judge(raw, COPY)


@pytest.mark.parametrize("raw", ["ALL", "All", "all,3", "3, ALL"])
def test_all_in_another_case_or_inside_a_list_is_refused(raw: str) -> None:
    # Read as a Case id, `ALL` or `all,3` would send almost no judge live for a caller who meant
    # every Case. The header and env readers share one grammar, so both refuse it.
    with pytest.raises(FrozenCopyHeaderError, match=REPLAY_LIVE_JUDGE_HEADER):
        parse_live_judge(raw, COPY)
    with pytest.raises(ValueError, match=job_env.REPLAY_LIVE_JUDGE):
        job_env.replay_live_judge_from_env({job_env.REPLAY_LIVE_JUDGE: raw})


def test_a_scope_cannot_name_live_judges_without_a_replay() -> None:
    with pytest.raises(ValueError, match="replay_live_judge"):
        RequestScope(origin="run", replay_live_judge="all")


# ── the connector rule ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_named_cases_judge_call_goes_live_during_a_replay() -> None:
    gateway, answer = await _call_as_judge_of(7, frozenset({"7"}))

    assert answer == LIVE_ANSWER
    assert gateway.paths() == [CHAT]


@pytest.mark.asyncio
async def test_an_unnamed_cases_judge_call_still_replays() -> None:
    gateway, answer = await _call_as_judge_of(8, frozenset({"7"}))

    assert answer == RECORDED_ANSWER
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
async def test_a_judge_call_replays_when_the_header_was_not_sent() -> None:
    gateway, answer = await _call_as_judge_of(7, None)

    assert answer == RECORDED_ANSWER
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [frozenset({"7"}), "all"], ids=["named", "all"])
async def test_a_candidate_call_always_replays_even_when_its_case_is_named(
    live: LiveJudge,
) -> None:
    # A Candidate invocation that still sees a grading Case (the grade hook's tag is inherited by
    # the tasks it spawns) is a Candidate call: a re-grade must make no Candidate model call.
    gateway: Gateway = _gateway()
    with grading_call_scope(7), candidate_invocation_scope():
        _tally, answer, failure = await run_call(
            gateway, replay_scope(replay_live_judge=live), web_search=False
        )

    assert failure is None
    assert answer == RECORDED_ANSWER
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [3, "q-9"])
async def test_all_sends_every_judge_call_live(case: int | str) -> None:
    gateway, answer = await _call_as_judge_of(case, "all")

    assert answer == LIVE_ANSWER
    assert gateway.paths() == [CHAT]


@pytest.mark.asyncio
async def test_a_call_outside_grading_replays_even_under_all() -> None:
    gateway: Gateway = _gateway()

    _tally, answer, failure = await run_call(
        gateway, replay_scope(replay_live_judge="all"), web_search=False
    )

    assert failure is None
    assert answer == RECORDED_ANSWER
    assert gateway.paths() == [REPLAY_CHAT]


# ── the job env (the carrier between the App and the run) ──────────────────────────────────


def test_the_env_key_is_written_by_the_app() -> None:
    assert job_env.REPLAY_LIVE_JUDGE == "URL4_CLOUD_REPLAY_LIVE_JUDGE"
    assert job_env.REPLAY_LIVE_JUDGE in job_env.WRITTEN_BY_APP


@pytest.mark.parametrize(
    ("live", "text"),
    [("all", "all"), (frozenset({"q-9", "3"}), "3,q-9")],
    ids=["all", "list"],
)
def test_live_judge_travels_the_queue_message_into_the_run_scope(
    live: LiveJudge, text: str
) -> None:
    env: dict[str, str] = decode_message(
        encode_message("t", "'hi'", 60, replay_frozen_copy=COPY, replay_live_judge=live)
    )

    assert env[job_env.REPLAY_LIVE_JUDGE] == text
    scope: RequestScope = request_scope_from_env(env)
    assert (scope.replay_frozen_copy, scope.replay_live_judge) == (COPY, live)


def test_a_plain_replay_message_carries_no_live_judge_key() -> None:
    env: dict[str, str] = decode_message(encode_message("t", "'hi'", 60, replay_frozen_copy=COPY))

    assert job_env.REPLAY_LIVE_JUDGE not in env
    assert request_scope_from_env(env).replay_live_judge is None


@pytest.mark.parametrize(
    "env",
    [
        {job_env.REPLAY_LIVE_JUDGE: "all"},
        {job_env.REPLAY_FROZEN_COPY: COPY, job_env.REPLAY_LIVE_JUDGE: ""},
        {job_env.REPLAY_FROZEN_COPY: COPY, job_env.REPLAY_LIVE_JUDGE: "3,,4"},
    ],
    ids=["no-replay", "blank", "empty-id"],
)
def test_a_malformed_live_judge_env_refuses_the_run(env: dict[str, str]) -> None:
    with pytest.raises(RunnerConfigError, match=job_env.REPLAY_LIVE_JUDGE):
        request_scope_from_env(env)


class _NeverExecutor(Executor):
    """An executor the env tests build but never start."""

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> Any:  # pragma: no cover - the run is never started
        """Never called: the env tests read the env the runner builds and start no run."""
        raise NotImplementedError
        yield ExecStep  # pragma: no cover


def _inprocess_env(
    *, live: LiveJudge | None, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The env local mode builds for one replay run."""
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
        replay_frozen_copy=COPY,
        replay_live_judge=live,
    )


def test_the_inprocess_env_carries_live_judge_and_drops_an_ambient_one() -> None:
    assert _inprocess_env(live="all")[job_env.REPLAY_LIVE_JUDGE] == "all"
    # `_base_env` is shared by every local run: a leftover value would turn the next caller's
    # plain replay into a paid re-grade.
    ambient: dict[str, str] = _inprocess_env(live=None, base={job_env.REPLAY_LIVE_JUDGE: "all"})
    assert job_env.REPLAY_LIVE_JUDGE not in ambient


# ── the start route ────────────────────────────────────────────────────────────────────────


class _LiveJudgeRecordingRunner(RecordingJobRunner):
    """Records whether, and with what, the route handed the port a live-judge set."""

    def __init__(self) -> None:
        super().__init__()
        self.live: list[tuple[bool, LiveJudge | None]] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        """Note the live-judge argument, then schedule as the recording fake does."""
        passed: bool = "replay_live_judge" in kwargs
        self.live.append((passed, kwargs.pop("replay_live_judge", None)))
        return await super().schedule(topic, url4, deadline_s, **kwargs)


async def _start(
    runner: RecordingJobRunner, topic: str, headers: Mapping[str, str]
) -> httpx.Response:
    """Start ``topic`` on a fresh App, async, with ``headers``."""
    app: FastAPI = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
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
                "Prefer": "respond-async",
                **headers,
            },
        )


@pytest.mark.asyncio
async def test_the_start_route_schedules_and_echoes_the_live_judge_cases() -> None:
    runner: _LiveJudgeRecordingRunner = _LiveJudgeRecordingRunner()

    resp: httpx.Response = await _start(
        runner,
        "live-ok",
        {REPLAY_FROZEN_COPY_HEADER: COPY, REPLAY_LIVE_JUDGE_HEADER: "q-9, 3"},
    )

    assert resp.status_code == 202
    # The echo is the acknowledgement: an engine that ignores the header sends none back.
    assert resp.headers[REPLAY_LIVE_JUDGE_HEADER] == "3,q-9"
    assert runner.live == [(True, frozenset({"3", "q-9"}))]


@pytest.mark.asyncio
async def test_a_plain_replay_calls_the_port_without_a_live_judge_argument() -> None:
    # WHY pinned: a run that names no live judge reaches the job runner port exactly as before
    # OME-1909, so a substrate that predates the argument still schedules it.
    runner: _LiveJudgeRecordingRunner = _LiveJudgeRecordingRunner()

    resp: httpx.Response = await _start(runner, "live-absent", {REPLAY_FROZEN_COPY_HEADER: COPY})

    assert resp.status_code == 202
    assert REPLAY_LIVE_JUDGE_HEADER not in resp.headers
    assert runner.live == [(False, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {REPLAY_LIVE_JUDGE_HEADER: "all"},
        {REPLAY_FROZEN_COPY_HEADER: COPY, REPLAY_LIVE_JUDGE_HEADER: ","},
    ],
    ids=["no-replay", "blank-list"],
)
async def test_a_bad_live_judge_header_is_a_400_and_nothing_is_scheduled(
    headers: dict[str, str],
) -> None:
    runner: _LiveJudgeRecordingRunner = _LiveJudgeRecordingRunner()

    resp: httpx.Response = await _start(runner, "live-bad", headers)

    assert resp.status_code == 400
    assert resp.json()["code"] == "malformed_header"
    assert runner.live == []
    assert runner.scheduled == []
