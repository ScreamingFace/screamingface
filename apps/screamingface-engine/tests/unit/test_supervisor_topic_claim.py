"""E5 P2 spec R3 in the worker: the claim step of an `exclusive` start.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a Candidate the Engine started twice
runs once, and a second copy of a live run never ends it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from test_supervisor_terminal_root_source import _Launcher, _Msg, _Proc, _Publisher, _worker

from screamingface_engine import job_env
from screamingface_engine.adapters.memory import InMemoryTopicClaims
from screamingface_engine.subjects import claim_subject_for
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.topic_claim import ClaimGate

pytestmark = pytest.mark.asyncio

TOPIC = "t-exclusive"


class _Holder:
    """A live holder that answers on `url4.runclaim.<topic>`, and records every ask."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, bytes]] = []

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        self.asked.append((subject, payload))
        return SimpleNamespace(data=payload)


def _exclusive(msg: _Msg, **changes: str) -> _Msg:
    body = json.loads(msg.data)
    body.update({job_env.EXCLUSIVE: "1", job_env.SPEC_VERSION: "3", **changes})
    msg.data = json.dumps(body).encode()
    return msg


def _gated(worker: Worker, claims: InMemoryTopicClaims, ask: Any, launcher: _Launcher) -> Worker:
    gate = ClaimGate(
        claims=claims,
        worker_id="w-here",
        ask=ask,
        ended=lambda topic: _never(),
        claimed=set(),
    )
    worker._supervisor._claim_gate = gate  # noqa: SLF001 - the seam under test
    worker._supervisor._launcher = launcher  # noqa: SLF001
    return worker


async def _never() -> bool:
    return False


class _Counting(_Launcher):
    def __init__(self, proc: Any) -> None:
        super().__init__(proc)
        self.launches = 0

    async def launch(self, env: Any, *, io_budget: Any) -> Any:
        self.launches += 1
        return await super().launch(env, io_budget=io_budget)


@pytest.mark.parametrize(
    ("msg", "label"),
    [
        (_Msg(TOPIC), "live"),
        (_Msg(TOPIC, deadline_s=1, queued_for_s=60), "expired"),
        (_Msg(TOPIC), "unknown version"),
    ],
)
async def test_a_copy_of_a_live_run_is_acked_away_without_a_terminal_frame(
    msg: _Msg, label: str
) -> None:
    """INVARIANT (R3): the claim comes before every check that could end the run, so a duplicate
    copy never publishes a terminal frame onto a live run."""
    claims = InMemoryTopicClaims()
    await claims.claim(TOPIC, "w-elsewhere")
    publisher, launcher, holder = _Publisher(), _Counting(_Proc(code=0)), _Holder()
    changes = {job_env.SPEC_VERSION: "9"} if label == "unknown version" else {}
    copy = _exclusive(msg, **changes)
    worker = _gated(_worker(publisher, launcher), claims, holder, launcher)

    await worker._supervisor.supervise(copy)  # type: ignore[arg-type]

    assert copy.acked
    assert publisher.published == []
    assert launcher.launches == 0
    assert holder.asked == [(claim_subject_for(TOPIC), b"w-elsewhere")]


async def test_a_copy_from_another_world_config_is_acked_away_without_a_terminal_frame() -> None:
    claims = InMemoryTopicClaims()
    await claims.claim(TOPIC, "w-elsewhere")
    publisher, launcher = _Publisher(), _Counting(_Proc(code=0))
    worker = _gated(_worker(publisher, launcher), claims, _Holder(), launcher)
    worker._supervisor._world_digest = "b" * 64  # noqa: SLF001
    copy = _exclusive(_Msg(TOPIC), **{job_env.WORLD_DIGEST: "a" * 64})

    await worker._supervisor.supervise(copy)  # type: ignore[arg-type]

    assert copy.acked and publisher.published == [] and launcher.launches == 0


async def test_the_winning_copy_runs_and_marks_its_claim_finished_before_the_ack() -> None:
    claims = InMemoryTopicClaims()
    publisher, launcher = _Publisher(), _Counting(_Proc(code=0))
    worker = _gated(_worker(publisher, launcher), claims, None, launcher)
    acked_after_finish: list[bool] = []
    copy = _exclusive(_Msg(TOPIC))
    original_ack = copy.ack

    async def ack() -> None:
        acked_after_finish.append((await claims.claim(TOPIC, "probe")).finished)
        await original_ack()

    copy.ack = ack  # type: ignore[method-assign]

    await worker._supervisor.supervise(copy)  # type: ignore[arg-type]

    assert launcher.launches == 1
    assert acked_after_finish == [True]
    assert (await claims.claim(TOPIC, "probe")).holder == "w-here"


async def test_a_message_without_the_flag_never_touches_the_bucket() -> None:
    """INVARIANT (plan E2): every run the driver did not start is claimed as today."""
    claims = InMemoryTopicClaims()
    publisher, launcher = _Publisher(), _Counting(_Proc(code=0))
    worker = _gated(_worker(publisher, launcher), claims, _Holder(), launcher)

    await worker._supervisor.supervise(_Msg(TOPIC))  # type: ignore[arg-type]

    assert launcher.launches == 1
    assert (await claims.claim(TOPIC, "probe")).holder == "probe"


async def test_a_worker_answers_only_for_a_claim_it_holds_under_its_own_id() -> None:
    worker = _worker(_Publisher(), _Launcher(_Proc(code=0)))
    answered: list[bytes] = []

    def _probe(holder: bytes) -> Any:
        async def respond(data: bytes) -> None:
            answered.append(data)

        return SimpleNamespace(subject=claim_subject_for(TOPIC), data=holder, respond=respond)

    me = worker._worker_id.encode()  # noqa: SLF001
    await worker._handle_claim(_probe(me))  # noqa: SLF001
    worker._claimed.add(TOPIC)  # noqa: SLF001
    await worker._handle_claim(_probe(b"someone-else"))  # noqa: SLF001
    await worker._handle_claim(_probe(me))  # noqa: SLF001

    assert answered == [me]
