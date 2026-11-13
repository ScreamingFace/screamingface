"""E5 P2 spec §4.1 and §6 (Context, Detached): `POST /runs` with every Candidate's start, the
Client's context, `detach` and `deadline_s`, and the Run as `GET /runs/{id}` reads it.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I send my evaluation once and leave;
the Engine keeps what it needs to start my Candidates, and only I can read it back.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, BOB, BODY, _Engine

from screamingface_engine.artifacts.ports import ArtifactContent, LocalFile
from screamingface_engine.artifacts.run_results import FilesystemRunResultStore, context_key
from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

EMAIL = ALICE["X-User-Email"]


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def starts(*names: str, **flags: Any) -> list[dict[str, Any]]:
    return [{"name": name, "url4": f"gpt({name})", **flags} for name in names or ("a", "b")]


class _Results:
    """A run-results store that records what it is asked, and refuses every put when ``down``."""

    def __init__(self, root: Path, *, down: bool = False) -> None:
        self._folder = FilesystemRunResultStore(root)
        self.down = down
        self.deleted: list[str] = []

    def put(self, key: str, body: bytes) -> None:
        if self.down:
            raise OSError("the store is down")
        self._folder.put(key, body)

    def open(self, key: str) -> ArtifactContent | None:
        return self._folder.open(key)

    def delete(self, keys: Iterable[str]) -> None:
        keys = list(keys)
        self.deleted.extend(keys)
        self._folder.delete(keys)

    def delete_older_than(self, cutoff: datetime) -> int:
        return 0


class _Drivers:
    def __init__(self) -> None:
        self.woken = 0

    def wake(self) -> None:
        self.woken += 1


def _engine(registry: Registry | None, tmp_path: Path, **settings: Any) -> _Engine:
    engine = _Engine(registry)
    engine.app.state.run_results = _Results(tmp_path / "results")
    engine.app.state.run_drivers = _Drivers()
    if settings:
        engine.app.state.settings = engine.app.state.settings.model_copy(update=settings)
    return engine


def _problem(resp: Any) -> tuple[int, str | None]:
    return resp.status_code, resp.json().get("code")


# --- the Run and its starts --------------------------------------------------------------


async def test_a_run_with_starts_reads_them_back_to_its_owner(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    sent = starts("a", "b", answer_seed=7, use_cache=False)

    created = await engine.create(candidates=sent)
    body = (await engine.client.get(f"/runs/{created.json()['id']}", headers=ALICE)).json()

    assert created.status_code == 201
    assert (body["detached"], body["deadline_at"], body["stopped_by"]) == (False, None, None)
    assert body["context"] is None
    assert [c["index"] for c in body["candidates"]] == [0, 1]
    assert [c["start"] for c in body["candidates"]] == [
        {**start, "capture": False, "replay_frozen_copy": None} for start in sent
    ]
    assert [c["record"] for c in body["candidates"]] == [None, None]


async def test_a_registered_run_wakes_the_drivers(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path)

    await engine.create(candidates=starts())

    assert engine.app.state.run_drivers.woken == 1


async def test_the_driver_gets_the_owners_email_and_no_answer_carries_it(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    created = await engine.create(candidates=starts(), context="ctx")
    run_id = created.json()["id"]

    answers = [
        created,
        await engine.client.get(f"/runs/{run_id}", headers=ALICE),
        await engine.client.get(f"/runs/{run_id}?view=summary", headers=ALICE),
        await engine.client.get("/runs", headers=ALICE),
    ]

    plan = await registry.store.pending_starts(run_id)
    assert plan is not None and plan.owner_email == EMAIL
    for answer in answers:
        assert answer.status_code in (200, 201)
        assert EMAIL not in answer.text
        assert "owner" not in answer.text


async def test_a_local_run_keeps_no_email(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path)
    engine.app.state.runs_require_identity = False

    run_id = (await engine.create(headers={}, candidates=starts())).json()["id"]

    plan = await registry.store.pending_starts(run_id)
    assert plan is not None and plan.owner_email is None


async def test_the_list_and_the_summary_carry_no_start_or_record(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = (await engine.create(candidates=starts())).json()["id"]

    summary = (await engine.client.get(f"/runs/{run_id}?view=summary", headers=ALICE)).json()
    listed = (await engine.client.get("/runs", headers=ALICE)).json()["runs"]

    assert listed == [summary]
    for candidate in summary["candidates"]:
        assert "start" not in candidate and "record" not in candidate
        assert candidate["index"] in (0, 1)


async def test_a_repeated_client_key_with_other_starts_is_409(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    await engine.create(candidates=starts("a"))

    refused = await engine.create(candidates=[{"name": "a", "url4": "claude(a)"}])

    assert _problem(refused) == (409, "client_key_conflict")


# --- detach and the deadline (spec D11) --------------------------------------------------


async def test_a_detached_run_gets_its_deadline(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path)

    named = (await engine.create(candidates=starts(), detach=True, deadline_s=3600)).json()
    default = (await engine.create(client_key="key-2", candidates=starts(), detach=True)).json()

    def lasts(run: dict[str, Any]) -> timedelta:
        return datetime.fromisoformat(run["deadline_at"]) - datetime.fromisoformat(
            run["created_at"]
        )

    assert named["detached"] is True
    assert lasts(named) == timedelta(hours=1)
    assert lasts(default) == timedelta(hours=48)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"detach": True, "deadline_s": 7 * 86_400 + 1}, "deadline_too_long"),
        ({"deadline_s": 3600}, "deadline_needs_detach"),
    ],
)
async def test_a_deadline_the_engine_cannot_keep_is_422(
    registry: Registry, tmp_path: Path, body: dict[str, Any], code: str
) -> None:
    engine = _engine(registry, tmp_path)

    refused = await engine.create(candidates=starts(), **body)

    assert _problem(refused) == (422, code)
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []


# --- every refusal has a code (spec D16) --------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"case_count": "3"},
        {"candidates": []},
        {"retries": 3},
        {"candidates": [{"name": "a", "url4": " "}]},
        {"candidates": [{"name": "a", "url4": "gpt(a)", "colour": "red"}]},
        {"candidates": [{"name": "a", "url4": "gpt(a)", "answer_seed": "7"}]},
        {"candidates": [{"name": "a", "url4": "gpt(a)", "replay_frozen_copy": "nope"}]},
        {
            "candidates": [
                {
                    "name": "a",
                    "url4": "gpt(a)",
                    "capture": True,
                    "replay_frozen_copy": "0f8fad5b-d9cb-469f-a165-70867728950e",
                }
            ]
        },
        {"deadline_s": 0, "detach": True, "candidates": [{"name": "a", "url4": "gpt(a)"}]},
    ],
    ids=[
        "count-as-text",
        "no-candidates",
        "unknown-field",
        "blank-url4",
        "unknown-start-field",
        "seed-as-text",
        "bad-frozen-copy",
        "capture-and-replay",
        "zero-deadline",
    ],
)
async def test_every_422_carries_a_code(
    registry: Registry, tmp_path: Path, body: dict[str, Any]
) -> None:
    engine = _engine(registry, tmp_path)

    refused = await engine.create(**body)

    assert refused.status_code == 422
    assert refused.json()["code"]


async def test_runs_off_answers_404_runs_off(tmp_path: Path) -> None:
    engine = _engine(None, tmp_path)

    assert _problem(await engine.create(candidates=starts())) == (404, "runs_off")


# --- the body cap (spec §4.1) -------------------------------------------------------------


async def test_a_body_over_the_cap_is_413_whether_or_not_it_declares_its_length(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path, run_request_max_bytes=1_100, run_context_max_bytes=1_000)
    body = {**BODY, "candidates": starts(), "context": "x" * 1_000}
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", **ALICE}
    assert len(raw) > 1_100

    async def chunked() -> AsyncIterator[bytes]:
        for start in range(0, len(raw), 512):
            yield raw[start : start + 512]

    declared = await engine.client.post("/runs", content=raw, headers=headers)
    streamed = await engine.client.post("/runs", content=chunked(), headers=headers)

    for refused in (declared, streamed):
        assert _problem(refused) == (413, "request_too_large")
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []


# --- the context (spec D9b, §6 Context) ---------------------------------------------------


async def test_the_context_is_stored_under_the_run_with_its_checksum(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    context = '{"cases": ["ünïcode"]}'
    data = context.encode()

    run = (await engine.create(candidates=starts(), context=context)).json()

    assert run["context"] == {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    stored = engine.app.state.run_results.open(context_key(run["id"]))
    assert isinstance(stored, LocalFile) and stored.path.read_bytes() == data


async def test_a_context_over_its_cap_is_422(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path, run_context_max_bytes=8)

    refused = await engine.create(candidates=starts(), context="é" * 5)

    assert _problem(refused) == (422, "context_too_large")


@pytest.mark.parametrize("store", ["down", "absent"])
async def test_a_run_whose_context_cannot_be_stored_is_not_registered(
    registry: Registry, tmp_path: Path, store: str
) -> None:
    engine = _engine(registry, tmp_path)
    if store == "down":
        engine.app.state.run_results.down = True
    else:
        engine.app.state.run_results = None

    refused = await engine.create(candidates=starts(), context="ctx")

    assert _problem(refused) == (503, "result_store_unavailable")
    assert refused.headers["Retry-After"]
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []
    assert engine.app.state.run_drivers.woken == 0


async def test_a_stated_x_profile_is_refused_before_anything_is_kept(
    registry: Registry, tmp_path: Path
) -> None:
    """`POST /runs` feeds the driver, so it refuses a selector as the start route does
    (OME-1381): no Run, no context, no driver woken."""
    engine = _engine(registry, tmp_path)

    refused = await engine.create({**ALICE, "X-Profile": "a"}, candidates=starts(), context="ctx")

    assert _problem(refused) == (400, "x_profile_unsupported")
    assert refused.headers["Cache-Control"] == "private, no-store"
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []
    assert list((tmp_path / "results").rglob("*")) == []
    assert engine.app.state.run_drivers.woken == 0


async def test_post_runs_documents_the_x_profile_refusal(
    registry: Registry, tmp_path: Path
) -> None:
    operation = _engine(registry, tmp_path).app.openapi()["paths"]["/runs"]["post"]

    (header,) = [p for p in operation["parameters"] if p["name"] == "X-Profile"]
    assert (header["in"], header["deprecated"]) == ("header", True)
    assert "x_profile_unsupported" in operation["responses"]["400"]["description"]


async def test_a_context_sent_again_for_the_same_run_is_deleted(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    first = (await engine.create(candidates=starts(), context="ctx")).json()

    again = await engine.create(candidates=starts(), context="ctx")

    results = engine.app.state.run_results
    assert (again.status_code, again.json()["id"]) == (200, first["id"])
    (deleted,) = results.deleted
    assert deleted != context_key(first["id"]) and deleted.endswith("/context")
    assert results.open(context_key(first["id"])) is not None


class _RegisterFails:
    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def register(self, *args: Any) -> Any:
        raise ConnectionError("the database is down")


async def test_a_context_whose_run_failed_to_register_is_deleted(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    engine.app.state.run_registry = _RegisterFails(registry.store)

    refused = await engine.create(candidates=starts(), context="ctx")

    assert refused.status_code == 503
    (deleted,) = engine.app.state.run_results.deleted
    assert deleted.endswith("/context")
    assert engine.app.state.run_results.open(deleted) is None


async def test_a_foreign_owner_cannot_read_the_run(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path)
    run_id = (await engine.create(candidates=starts(), context="ctx")).json()["id"]

    for path in (f"/runs/{run_id}", f"/runs/{run_id}?view=summary"):
        resp = await engine.client.get(path, headers=BOB)
        assert _problem(resp) == (404, "run_not_found")
    assert await registry.store.get(owner_key(EMAIL), run_id) is not None


async def test_a_names_only_body_is_refused_with_a_code(registry: Registry, tmp_path: Path) -> None:
    """E5 P2 spec D1, D16: the Engine starts every Candidate, so a Run must carry their starts.
    A Client from before P2 reads the refusal as "not recorded" and runs as before."""
    engine = _engine(registry, tmp_path)
    names_only = {**BODY, "candidates": ["alpha", "beta"]}

    refused = await engine.client.post("/runs", json=names_only, headers=ALICE)

    assert _problem(refused) == (422, "invalid_request")
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []


@pytest.mark.parametrize(
    ("url4", "status"),
    [
        ("gpt(" + "x" * 500_000 + ")", 201),
        ("gpt(" + "x" * 530_000 + ")", 422),
        # Counted as the run queue carries it: a control character is six bytes there.
        ("gpt(" + "\x01" * 100_000 + ")", 422),
        # An emoji is twelve bytes there, two escaped UTF-16 halves.
        ("gpt(" + "\U0001f600" * 50_000 + ")", 422),
    ],
    ids=["under", "over", "over-once-escaped", "over-as-astral"],
)
async def test_a_start_too_large_for_the_run_queue_is_refused(
    registry: Registry, tmp_path: Path, url4: str, status: int
) -> None:
    """A start is one run-queue message, which the broker bounds (1 MiB by default). INVARIANT:
    a Run is never registered with a Candidate the Engine could not start."""
    engine = _engine(registry, tmp_path)

    resp = await engine.create(candidates=[{"name": "a", "url4": url4}])

    assert resp.status_code == status
    if status == 422:
        assert resp.json()["code"] == "invalid_request"
        assert len(resp.content) < 4_096


@pytest.mark.parametrize(
    "body",
    [
        {"candidates": [{"name": "a", "url4": "gpt(half an emoji \ud83d)"}]},
        {"candidates": [{"name": "a\ud83d", "url4": "gpt(a)"}]},
        {"benchmark": "gsm8k\udc00"},
    ],
    ids=["url4", "name", "benchmark"],
)
async def test_a_lone_surrogate_is_a_coded_422_on_every_database(
    registry: Registry, tmp_path: Path, body: dict[str, Any]
) -> None:
    """A truncated emoji leaves half a UTF-16 pair, which PostgreSQL text cannot hold. INVARIANT:
    a body that can never be stored is the caller's 422, not a 503 that invites a retry."""
    engine = _engine(registry, tmp_path)

    # WHY encoded here: httpx cannot encode a lone surrogate; a client's JSON escapes it.
    resp = await engine.client.post(
        "/runs",
        content=json.dumps({**BODY, **body}),
        headers={**ALICE, "Content-Type": "application/json"},
    )

    assert _problem(resp) == (422, "invalid_request")
    assert (await engine.client.get("/runs", headers=ALICE)).json()["runs"] == []


@pytest.mark.parametrize("since", ["9999-12-31T23:59:59-12:00", "0001-01-01T00:00:00+14:00"])
async def test_a_since_no_database_can_hold_is_a_coded_422(
    registry: Registry, tmp_path: Path, since: str
) -> None:
    """Out of range once in UTC: Postgres cannot encode it. INVARIANT: a query that can never be
    answered is the caller's 422, not a 503 that invites a retry."""
    engine = _engine(registry, tmp_path)

    resp = await engine.client.get("/runs", params={"since": since}, headers=ALICE)

    assert _problem(resp) == (422, "invalid_request")


async def test_a_non_ascii_candidate_name_reads_back_as_sent(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)

    created = await engine.create(candidates=starts("α-модель", "b"))
    run = (await engine.client.get(f"/runs/{created.json()['id']}", headers=ALICE)).json()

    assert [c["name"] for c in run["candidates"]] == ["α-модель", "b"]


async def test_a_deadline_no_duration_can_hold_is_a_coded_422(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)

    refused = await engine.create(candidates=starts(), detach=True, deadline_s=-(10**20))

    assert _problem(refused) == (422, "invalid_request")


async def test_a_retry_matches_its_run_when_a_name_has_outer_spaces(
    registry: Registry, tmp_path: Path
) -> None:
    """A name is kept stripped, so the same body sent again must still read as the same Run."""
    engine = _engine(registry, tmp_path)
    spaced = [{"name": " a ", "url4": "gpt(a)"}]

    first = await engine.create(candidates=spaced)
    again = await engine.create(candidates=spaced)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]


class _RegistersThenLosesTheAnswer(_RegisterFails):
    """A registry whose register commits, but whose answer never arrives."""

    async def register(self, *args: Any) -> Any:
        await self._store.register(*args)
        raise ConnectionError("the answer was lost")


async def test_a_run_that_registered_keeps_its_context_when_its_answer_is_lost(
    registry: Registry, tmp_path: Path
) -> None:
    """INVARIANT: a registered Run's context is never deleted, so its Report can be built on
    another machine. The route cannot tell a failed register from a lost answer, so it asks."""
    engine = _engine(registry, tmp_path)
    engine.app.state.run_registry = _RegistersThenLosesTheAnswer(registry.store)

    lost = await engine.create(candidates=starts(), context="ctx")
    engine.app.state.run_registry = registry.store
    again = await engine.create(candidates=starts(), context="ctx")

    assert (lost.status_code, again.status_code) == (503, 200)
    run_id = again.json()["id"]
    served = await engine.client.get(f"/runs/{run_id}/context", headers=ALICE)
    assert (served.status_code, served.content) == (200, b"ctx")
