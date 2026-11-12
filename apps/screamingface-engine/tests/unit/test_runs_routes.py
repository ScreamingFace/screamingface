"""E5 P1 spec §6, the routes: `/runs` (§4.1, D6, D12) and binding a start to its Candidate (R2).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, I list last week's runs from
another notebook, read one, and cancel one still running, and only I can see mine.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from _fakes import FixedGate, RecordingJobRunner
from httpx import ASGITransport
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.config import Settings
from screamingface_engine.runs.records import RunRecord, owner_key
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.tracing.accept import ACCEPT_SPAN_NAME
from url4.streaming.interfaces import JobRunnerAtCapacity
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

SECRET = "runs-routes-secret-of-32-bytes-or-more"
WINDOW_S = 60
LIFETIME_S = 58_800
# A PAST instant: pyjwt checks `iat` against the real clock.
TOKEN_T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
ALICE = {"X-User-Email": "alice@example.org"}
BOB = {"X-User-Email": "bob@example.org"}
UNKNOWN = "run_" + "0" * 32
BODY: dict[str, Any] = {
    "client_key": "key-1",
    "benchmark": "gsm8k",
    "case_count": 3,
    "candidates": ["alpha", "beta"],
    "client_version": "1.2.3",
}


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


class _Engine:
    """An App on the test registry, with a recording runner, and a client to call it."""

    def __init__(
        self,
        registry: Registry | None,
        *,
        local: bool = False,
        runner: RecordingJobRunner | None = None,
    ) -> None:
        self.runner = runner or RecordingJobRunner()
        self.app = create_app(
            Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
            stream=InMemoryEventStream(),
            job_runner=self.runner,
            clock=lambda: TOKEN_T0,
            interest=FixedGate(),
        )
        self.app.state.run_registry = None if registry is None else registry.store
        self.app.state.runs_require_identity = not local
        self.client = httpx.AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        )

    async def create(self, headers: Mapping[str, str] = ALICE, **body: Any) -> httpx.Response:
        return await self.client.post("/runs", json={**BODY, **body}, headers=dict(headers))

    async def start(
        self, topic: str, run_id: str | None = None, candidate: str | None = "0", **headers: str
    ) -> httpx.Response:
        binding = {} if run_id is None else {"X-SF-Run": run_id}
        if run_id is not None and candidate is not None:
            binding["X-SF-Run-Candidate"] = candidate
        token = JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, TOKEN_T0)
        return await self.client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": token,
                "Prefer": "respond-async",
                **ALICE,
                **binding,
                **headers,
            },
        )


async def _record(registry: Registry, run_id: str, owner: str = "alice@example.org") -> RunRecord:
    record = await registry.store.get(owner_key(owner), run_id)
    assert record is not None
    return record


# --- who is asking (spec D6) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/runs"),
        ("GET", "/runs"),
        ("GET", f"/runs/{UNKNOWN}"),
        ("DELETE", f"/runs/{UNKNOWN}"),
    ],
)
async def test_a_hosted_call_without_identity_is_401(
    registry: Registry, method: str, path: str
) -> None:
    engine = _Engine(registry)

    resp = await engine.client.request(method, path, json=BODY if method == "POST" else None)

    assert resp.status_code == 401


async def test_local_mode_owns_runs_as_local(registry: Registry) -> None:
    engine = _Engine(registry, local=True)

    resp = await engine.create(headers={})

    assert resp.status_code == 201
    assert await registry.store.get(owner_key("local"), resp.json()["id"]) is not None


@pytest.mark.parametrize(("method", "path"), [("POST", "/runs"), ("GET", "/runs")])
async def test_runs_off_answers_a_plain_404(method: str, path: str) -> None:
    """Spec D2, D7: the answer of an Engine without `/runs`, so the Client falls back."""
    engine = _Engine(None)

    resp = await engine.client.request(
        method, path, json=BODY if method == "POST" else None, headers=ALICE
    )

    assert resp.status_code == 404
    assert resp.json().get("code") != "run_not_found"


# --- register, read, list ----------------------------------------------------------------


async def test_a_repeated_post_returns_the_same_run_with_200(registry: Registry) -> None:
    engine = _Engine(registry)

    first = await engine.create()
    again = await engine.create()

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]


async def test_the_record_never_carries_the_owner(registry: Registry) -> None:
    engine = _Engine(registry)

    body = (await engine.create()).json()

    assert set(body) == {
        "id",
        "state",
        "created_at",
        "finished_at",
        "benchmark",
        "case_count",
        "candidates",
    }
    assert [c["name"] for c in body["candidates"]] == ["alpha", "beta"]
    assert body["candidates"][0]["state"] == "pending"


async def test_list_and_get_agree_on_state_and_cost(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    await registry.store.bind(owner_key("alice@example.org"), run_id, 0, "topic-a")
    await registry.store.settle("topic-a", CandidateOutcome("succeeded", cost_usd=Decimal("0.5")))

    one = (await engine.client.get(f"/runs/{run_id}", headers=ALICE)).json()
    listed = (await engine.client.get("/runs", headers=ALICE)).json()

    assert listed == {"runs": [one], "next_cursor": None}
    assert one["state"] == "running"
    assert one["candidates"][0]["cost_usd"] == "0.5"
    filtered = (await engine.client.get("/runs?state=complete", headers=ALICE)).json()
    assert filtered["runs"] == []


@pytest.mark.parametrize("run_id", [UNKNOWN, "not-a-run-id"])
@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_an_unknown_id_is_run_not_found(registry: Registry, method: str, run_id: str) -> None:
    engine = _Engine(registry)

    resp = await engine.client.request(method, f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_a_foreign_id_reads_as_unknown(registry: Registry, method: str) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]

    resp = await engine.client.request(method, f"/runs/{run_id}", headers=BOB)

    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"
    assert (await _record(registry, run_id)).state == "running"


@pytest.mark.parametrize(
    "body",
    [{"case_count": "3"}, {"candidates": []}, {"candidates": ["a", "a"]}, {"client_key": " "}],
)
async def test_an_invalid_run_is_422(registry: Registry, body: dict[str, Any]) -> None:
    engine = _Engine(registry)

    assert (await engine.create(**body)).status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "cursor=nope", "state=done"])
async def test_an_invalid_query_is_422(registry: Registry, query: str) -> None:
    engine = _Engine(registry)

    assert (await engine.client.get(f"/runs?{query}", headers=ALICE)).status_code == 422


# --- cancel (spec D12) -------------------------------------------------------------------


async def test_cancel_stops_live_topics_and_pending_candidates(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a", "b", "c"])).json()["id"]
    alice = owner_key("alice@example.org")
    await registry.store.bind(alice, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")
    await registry.store.bind(alice, run_id, 1, "topic-b")
    await registry.store.mark_scheduled("topic-b")
    await registry.store.settle("topic-b", CandidateOutcome("succeeded"))

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 202
    assert engine.runner.stopped == ["topic-a"]
    states = [c.state for c in (await _record(registry, run_id)).candidates]
    assert states == ["scheduled", "succeeded", "stopped"]


async def test_cancel_of_a_finished_run_changes_nothing(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(owner_key("alice@example.org"), run_id, 0, "topic-a")
    await registry.store.settle("topic-a", CandidateOutcome("succeeded"))

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 204
    assert engine.runner.stopped == []
    assert (await _record(registry, run_id)).state == "complete"


# --- binding a start (spec R2) -----------------------------------------------------------


async def test_a_bound_start_schedules_its_candidate(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["α-модель", "b"])).json()["id"]

    resp = await engine.start("topic-a", run_id, candidate="0")

    assert resp.status_code == 202
    candidate = (await _record(registry, run_id)).candidates[0]
    assert (candidate.name, candidate.state, candidate.attempt_id) == (
        "α-модель",
        "scheduled",
        "topic-a",
    )


async def test_a_start_without_the_headers_is_unbound(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a")

    assert resp.status_code == 202
    assert [s.topic for s in engine.runner.scheduled] == ["topic-a"]
    assert {c.attempt_id for c in (await _record(registry, run_id)).candidates} == {None}


async def test_a_start_with_runs_off_runs_unbound() -> None:
    engine = _Engine(None)

    resp = await engine.start("topic-a", UNKNOWN)

    assert resp.status_code == 202
    assert [s.topic for s in engine.runner.scheduled] == ["topic-a"]


async def test_a_start_under_a_canceled_run_is_409_before_scheduling(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    resp = await engine.start("topic-a", run_id)

    assert resp.status_code == 409
    assert resp.json()["code"] == "run_canceled"
    assert engine.runner.scheduled == []


@pytest.mark.parametrize(
    ("unknown", "headers"),
    [(True, ALICE), (False, BOB), (False, {"X-User-Email": ""})],
    ids=["unknown-run", "foreign-run", "no-identity"],
)
async def test_a_start_under_a_run_not_the_callers_is_404(
    registry: Registry, unknown: bool, headers: dict[str, str]
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a", UNKNOWN if unknown else run_id, **headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"
    assert engine.runner.scheduled == []


@pytest.mark.parametrize("candidate", [None, "x", "-1", "1.5", "2"])
async def test_a_bad_candidate_index_is_400(registry: Registry, candidate: str | None) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a", run_id, candidate=candidate)

    assert resp.status_code == 400
    assert resp.json()["code"] == "malformed_header"
    assert engine.runner.scheduled == []


async def test_a_second_topic_for_a_started_candidate_is_409(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    await engine.start("topic-a", run_id)

    resp = await engine.start("topic-b", run_id)

    assert resp.status_code == 409
    assert resp.json()["code"] == "candidate_already_started"
    assert [s.topic for s in engine.runner.scheduled] == ["topic-a"]


class _BusyOnceRunner(RecordingJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.busy = True

    async def schedule(self, topic: str, *args: Any, **kwargs: Any) -> str:
        if self.busy:
            self.busy = False
            raise JobRunnerAtCapacity(1, 1)
        return await super().schedule(topic, *args, **kwargs)


async def test_a_refused_start_stays_pending_and_its_resend_schedules(registry: Registry) -> None:
    engine = _Engine(registry, runner=_BusyOnceRunner())
    run_id = (await engine.create()).json()["id"]

    refused = await engine.start("topic-a", run_id)
    pending = (await _record(registry, run_id)).candidates[0]
    resent = await engine.start("topic-a", run_id)

    assert (refused.status_code, resent.status_code) == (503, 202)
    assert (pending.state, pending.attempt_id) == ("pending", "topic-a")
    assert (await _record(registry, run_id)).candidates[0].state == "scheduled"


class _FailingBinds:
    """The registry with its database gone for binds."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def bind(self, *args: Any) -> None:
        raise ConnectionError("database down")


async def test_a_bind_that_fails_on_the_database_still_schedules(
    registry: Registry, caplog: pytest.LogCaptureFixture
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    engine.app.state.run_registry = _FailingBinds(registry.store)

    with caplog.at_level(logging.WARNING):
        resp = await engine.start("topic-a", run_id)

    assert resp.status_code == 202
    assert [s.topic for s in engine.runner.scheduled] == ["topic-a"]
    assert "run bind failed" in caplog.text


class _CanceledWhileScheduling(RecordingJobRunner):
    """A `DELETE /runs/{id}` lands between the start's bind and its schedule."""

    def __init__(self, registry: Registry) -> None:
        super().__init__()
        self.registry = registry
        self.run_id = ""

    async def schedule(
        self, topic: str, *args: Any, cache: CachePolicy | None = None, **kwargs: Any
    ) -> str:
        await self.registry.store.cancel(owner_key("alice@example.org"), self.run_id)
        return await super().schedule(topic, *args, cache=cache, **kwargs)


async def test_a_start_that_loses_to_a_cancel_stops_itself(registry: Registry) -> None:
    runner = _CanceledWhileScheduling(registry)
    engine = _Engine(registry, runner=runner)
    runner.run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a", runner.run_id)

    assert resp.status_code == 409
    assert resp.json()["code"] == "run_canceled"
    assert runner.stopped == ["topic-a"]
    # E5 P2 spec R9: the Run is canceled once the stopped Candidate's outcome lands.
    await registry.store.settle("topic-a", CandidateOutcome("stopped"))
    assert (await _record(registry, runner.run_id)).state == "canceled"


# --- the accept span and caching ----------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.spans: list[Any] = []

    def emit(self, span: Any) -> None:
        self.spans.append(span)

    def close(self) -> None:
        pass


async def test_the_accept_span_ends_at_enqueue_before_the_registry_write(
    registry: Registry,
) -> None:
    """INVARIANT (OME-1218 D2): a cancel answered after enqueue is not an accept refusal."""
    runner = _CanceledWhileScheduling(registry)
    engine = _Engine(registry, runner=runner)
    sink = _Sink()
    engine.app.state.span_sink = sink
    runner.run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a", runner.run_id)

    assert resp.status_code == 409
    (accept,) = [s for s in sink.spans if s.name == ACCEPT_SPAN_NAME]
    assert accept.attributes["url4.accept.outcome"] == "scheduled"


@pytest.mark.parametrize("path", ["/runs", "/runs/{id}"])
async def test_run_answers_are_private_to_their_owner(registry: Registry, path: str) -> None:
    """A shared cache in front of the Engine must never serve one owner's Runs to another."""
    engine = _Engine(registry)
    created = await engine.create()

    resp = await engine.client.get(path.format(id=created.json()["id"]), headers=ALICE)

    for answer in (created, resp):
        assert answer.headers["Cache-Control"] == "private, no-store"
        assert answer.headers["Vary"] == "X-User-Email"


@pytest.mark.parametrize(
    ("stored", "wire"),
    [
        ("0.5", "0.5"),
        ("0.500000000000", "0.5"),
        ("100.000000", "100"),
        ("0.000000000001", "0.000000000001"),
    ],
)
async def test_a_cost_reads_the_same_on_either_database(
    registry: Registry, stored: str, wire: str
) -> None:
    """Postgres returns the column's full scale; the wire must not depend on the database."""
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(owner_key("alice@example.org"), run_id, 0, "topic-a")
    await registry.store.settle("topic-a", CandidateOutcome("succeeded", cost_usd=Decimal(stored)))

    body = (await engine.client.get(f"/runs/{run_id}", headers=ALICE)).json()

    assert body["candidates"][0]["cost_usd"] == wire


async def test_a_repeated_client_key_for_another_evaluation_is_409(registry: Registry) -> None:
    engine = _Engine(registry)
    await engine.create()

    refused = await engine.create(candidates=["gamma"])

    assert (refused.status_code, refused.json()["code"]) == (409, "client_key_conflict")


async def test_a_cursor_that_names_no_run_of_yours_is_422(registry: Registry) -> None:
    engine = _Engine(registry)
    await engine.create()

    refused = await engine.client.get(f"/runs?cursor={UNKNOWN}", headers=ALICE)

    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_cursor")


# --- review follow-ups on #1648 ------------------------------------------------------------

# Pairs that Unicode case folding would merge into one owner (ligature, sharp s, long s), and
# the Kelvin sign, which `str.lower()` maps to "k" in text but not as the edge sends it.
_LOOKALIKES = [
    ("finance@corp.org", "ﬁnance@corp.org"),
    ("strasse@corp.org", "straße@corp.org"),
    ("sam@corp.org", "ſam@corp.org"),
    ("kim@corp.org", "Kim@corp.org"),
]


@pytest.mark.parametrize(("owner", "other"), _LOOKALIKES, ids=["fi", "sharp-s", "long-s", "kelvin"])
async def test_a_lookalike_email_is_another_owner(
    registry: Registry, owner: str, other: str
) -> None:
    """INVARIANT (spec D6): only the owner key authorizes a Run, so two addresses that fold
    together must still be two owners. The edge sends the email as UTF-8 bytes."""
    engine = _Engine(registry)
    run_id = (await engine.create(headers={"X-User-Email": owner})).json()["id"]
    # `cast`: httpx sends a bytes header value as it is, as the edge sends a UTF-8 email.
    as_other = cast("dict[str, str]", {"X-User-Email": other.encode()})

    read = await engine.client.get(f"/runs/{run_id}", headers=as_other)
    cancel = await engine.client.delete(f"/runs/{run_id}", headers=as_other)
    start = await engine.start("topic-a", run_id, **as_other)

    for resp in (read, cancel, start):
        assert (resp.status_code, resp.json()["code"]) == (404, "run_not_found")
    assert engine.runner.scheduled == []
    assert (await _record(registry, run_id, owner)).state == "running"


class _SlowStops(RecordingJobRunner):
    """Stops that take a while, recording how many run at once; one topic's stop can fail."""

    def __init__(self, failing: str | None = None) -> None:
        super().__init__()
        self.failing = failing
        self.in_flight = 0
        self.most_at_once = 0

    async def stop(self, topic: str) -> None:
        self.in_flight += 1
        self.most_at_once = max(self.most_at_once, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            if topic == self.failing:
                raise QueueReadError(topic)
            self.stopped.append(topic)
        finally:
            self.in_flight -= 1


async def _live_run(engine: _Engine, registry: Registry, count: int) -> str:
    names = [f"c{i}" for i in range(count)]
    run_id = (await engine.create(candidates=names)).json()["id"]
    alice = owner_key("alice@example.org")
    for index in range(count):
        await registry.store.bind(alice, run_id, index, f"topic-{index}")
        await registry.store.mark_scheduled(f"topic-{index}")
    return run_id


async def test_cancel_stops_live_topics_together_but_bounded(registry: Registry) -> None:
    runner = _SlowStops()
    engine = _Engine(registry, runner=runner)
    run_id = await _live_run(engine, registry, 40)

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 202
    assert sorted(runner.stopped) == sorted(f"topic-{i}" for i in range(40))
    assert 1 < runner.most_at_once <= 16


async def test_a_failed_stop_still_tries_the_others_and_answers_503(registry: Registry) -> None:
    runner = _SlowStops(failing="topic-1")
    engine = _Engine(registry, runner=runner)
    run_id = await _live_run(engine, registry, 4)

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert sorted(runner.stopped) == ["topic-0", "topic-2", "topic-3"]
    runner.failing = None
    retried = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    assert retried.status_code == 202
    assert "topic-1" in runner.stopped


async def test_a_run_with_a_field_this_engine_does_not_know_is_422(registry: Registry) -> None:
    engine = _Engine(registry)

    assert (await engine.create(retries=3)).status_code == 422
