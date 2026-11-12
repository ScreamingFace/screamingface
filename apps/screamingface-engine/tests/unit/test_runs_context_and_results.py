"""E5 P2 spec §4.1 and §6 (Context, Results): a Run's context and each Candidate's result, served
to the Run's owner from the run-results store.

FEATURE: a detached Run (OME-1837). STORY: as a researcher on a second machine, I read back my
Run's context and each Candidate's result to build its Report, and nobody else can.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
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
from test_runs_create_p2 import starts
from test_runs_routes import ALICE, BOB, _Engine

from screamingface_engine.artifacts.run_results import (
    FilesystemRunResultStore,
    context_key,
    result_key,
    result_prefix,
)
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

OWNER = owner_key(ALICE["X-User-Email"])
RESULT = b'{"answer": "42 \xe2\x9c\x93"}'
DIGEST = hashlib.sha256(RESULT).hexdigest()


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _engine(registry: Registry, tmp_path: Path) -> _Engine:
    engine = _Engine(registry)
    engine.app.state.run_results = FilesystemRunResultStore(tmp_path / "results")
    return engine


async def _run(engine: _Engine, **body: Any) -> str:
    created = await engine.create(candidates=starts("a", "b"), **body)
    assert created.status_code == 201
    return created.json()["id"]


async def _settle(registry: Registry, run_id: str, index: int, record: dict[str, Any]) -> None:
    topic = f"t-{run_id}-{index}"
    await registry.store.bind(OWNER, run_id, index, topic)
    await registry.store.mark_scheduled(topic)
    await registry.store.settle(topic, CandidateOutcome("succeeded", record=record))


def _with_result(digest: str = DIGEST, media_type: str = "application/json") -> dict[str, Any]:
    return {"result": {"media_type": media_type, "size_bytes": len(RESULT), "sha256": digest}}


def _code(resp: Any) -> tuple[int, str | None]:
    return resp.status_code, resp.json().get("code")


# --- the context -------------------------------------------------------------------------


async def test_the_context_is_served_to_its_owner_byte_for_byte(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    context = '{"cases": ["ünïcode", "\\u0000"]}'
    run_id = await _run(engine, context=context)

    resp = await engine.client.get(f"/runs/{run_id}/context", headers=ALICE)
    run = (await engine.client.get(f"/runs/{run_id}", headers=ALICE)).json()

    assert resp.status_code == 200
    assert resp.content == context.encode()
    assert hashlib.sha256(resp.content).hexdigest() == run["context"]["sha256"]
    assert (resp.headers["Cache-Control"], resp.headers["Vary"]) == (
        "private, no-store",
        "X-User-Email",
    )


async def test_a_run_without_a_context_has_none_to_serve(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine)

    resp = await engine.client.get(f"/runs/{run_id}/context", headers=ALICE)

    assert _code(resp) == (404, "context_not_found")
    assert resp.headers["Cache-Control"] == "private, no-store"


async def test_a_context_gone_from_the_store_is_not_found(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine, context="ctx")
    engine.app.state.run_results.delete([context_key(run_id)])

    resp = await engine.client.get(f"/runs/{run_id}/context", headers=ALICE)

    assert _code(resp) == (404, "context_not_found")


# --- results -----------------------------------------------------------------------------


async def test_a_result_is_served_from_the_key_its_record_names(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine)
    engine.app.state.run_results.put(result_key(result_prefix(run_id, 1), DIGEST), RESULT)
    await _settle(registry, run_id, 1, _with_result(media_type="text/markdown"))

    resp = await engine.client.get(f"/runs/{run_id}/candidates/1/result", headers=ALICE)

    assert resp.status_code == 200
    assert resp.content == RESULT
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "case", ["not-ended", "no-result", "gone-from-store", "unknown-index", "foreign-digest"]
)
async def test_a_result_the_run_does_not_name_is_not_found(
    registry: Registry, tmp_path: Path, case: str
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine)
    store = engine.app.state.run_results
    index = 5 if case == "unknown-index" else 0
    if case == "no-result":
        await _settle(registry, run_id, 0, {"usage": {}})
    elif case in ("gone-from-store", "unknown-index"):
        await _settle(registry, run_id, 0, _with_result())
    elif case == "foreign-digest":
        # The bytes exist under another Run's key; this Run's record names its own key only.
        other = await _run(engine, client_key="key-2")
        store.put(result_key(result_prefix(other, 0), DIGEST), RESULT)
        await _settle(registry, run_id, 0, _with_result())

    resp = await engine.client.get(f"/runs/{run_id}/candidates/{index}/result", headers=ALICE)

    assert _code(resp) == (404, "result_not_found")


async def test_a_record_with_a_malformed_digest_serves_nothing(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine, context="ctx")
    await _settle(registry, run_id, 0, _with_result(digest="../../context"))

    resp = await engine.client.get(f"/runs/{run_id}/candidates/0/result", headers=ALICE)

    assert _code(resp) == (404, "result_not_found")


async def test_a_negative_index_is_a_coded_422(registry: Registry, tmp_path: Path) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine)

    resp = await engine.client.get(f"/runs/{run_id}/candidates/-1/result", headers=ALICE)

    assert resp.status_code == 422
    assert resp.json()["code"]


# --- the owner check (spec D5) -----------------------------------------------------------


@pytest.mark.parametrize("path", ["context", "candidates/0/result"])
@pytest.mark.parametrize("who", ["foreign", "unknown", "malformed"])
async def test_only_the_owner_reads_a_runs_objects(
    registry: Registry, tmp_path: Path, path: str, who: str
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine, context="ctx")
    engine.app.state.run_results.put(result_key(result_prefix(run_id, 0), DIGEST), RESULT)
    await _settle(registry, run_id, 0, _with_result())
    target = {"foreign": run_id, "unknown": "run_" + "0" * 32, "malformed": "x" * 300}[who]

    resp = await engine.client.get(
        f"/runs/{target}/{path}", headers=BOB if who == "foreign" else ALICE
    )

    assert _code(resp) == (404, "run_not_found")
    assert "x" * 300 not in resp.text


# --- the registry's record read (spec §4.2) ---------------------------------------------


async def test_records_reads_the_named_candidates_of_the_owners_run(
    registry: Registry, tmp_path: Path
) -> None:
    engine = _engine(registry, tmp_path)
    run_id = await _run(engine)
    await _settle(registry, run_id, 1, _with_result())

    assert await registry.store.records(OWNER, run_id, [1]) == {1: _with_result()}
    assert await registry.store.records(OWNER, run_id, [0, 1, 9]) == {0: None, 1: _with_result()}
    assert await registry.store.records(owner_key("bob@example.org"), run_id, [1]) is None
