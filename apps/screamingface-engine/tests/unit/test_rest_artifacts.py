"""REST redemption of result claim tickets: `GET /artifacts/{id}` (OME-892).

FEATURE: deliver large results in full instead of cutting them off at 1 MiB.
INVARIANT: the route serves exactly the complete stored bytes or a problem — never a
partial body — and fetching NEVER deletes: one file may back many claim tickets (content
addressing dedupes identical results), a dropped connection must be retryable, and a
Range request must leave the rest fetchable. Artifacts die by TTL alone (startup +
periodic sweep), so crashed runs cannot leak disk forever.
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.artifacts import ArtifactStore
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.rest.routes import _result_response
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import ResultData, ResultEvent

SECRET = "rest-artifacts-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
# WHY a past instant: pyjwt refuses an `iat` in the future, so the fake clock must lag
# real UTC or every minted capability is rejected before our own window checks run.
T0 = datetime(2026, 8, 18, 9, 0, 0, tzinfo=UTC)


def _cap(topic: str) -> dict[str, str]:
    return {
        "URL4-Capability": JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, T0)
    }


def _make_app(
    tmp_path: Path,
    *,
    artifact_ttl_s: int = 172_800,
    artifact_sweep_interval_s: float = 3600.0,
) -> FastAPI:
    settings = Settings(
        jwt_secret=SECRET,
        iat_window_s=WINDOW_S,
        artifacts_dir=str(tmp_path / "artifacts"),
        artifact_ttl_s=artifact_ttl_s,
        artifact_sweep_interval_s=artifact_sweep_interval_s,
    )
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_get_artifact_serves_complete_bytes_and_stays_refetchable(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    body = '{"cases":[' + "1," * 5000 + "1]}"
    ref = store.write_text(body)

    async with _client(app) as client:
        first = await client.get(f"/artifacts/{ref.id}", headers=_cap("t" * 64))
        # INVARIANT: fetching never deletes — a retry after a dropped connection, or a
        # second ticket deduped onto the same file, must find the parcel still there.
        second = await client.get(f"/artifacts/{ref.id}", headers=_cap("t" * 64))

    assert first.status_code == 200
    assert first.text == body
    assert int(first.headers["content-length"]) == ref.size_bytes
    assert second.status_code == 200
    assert second.text == body
    assert store.path_for(ref.id) is not None


@pytest.mark.asyncio
async def test_a_range_request_does_not_consume_the_artifact(tmp_path: Path) -> None:
    # WHY: Range is the resume mechanism — a partial read must leave the rest fetchable.
    # Under delete-on-fetch a `bytes=0-9` request destroyed the other 99% of the result.
    app = _make_app(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    body = "R" * 4096
    ref = store.write_text(body)

    async with _client(app) as client:
        partial = await client.get(
            f"/artifacts/{ref.id}", headers={**_cap("t" * 64), "Range": "bytes=0-9"}
        )
        rest = await client.get(f"/artifacts/{ref.id}", headers=_cap("t" * 64))

    assert partial.status_code == 206
    assert partial.text == "R" * 10
    assert rest.status_code == 200
    assert rest.text == body


@pytest.mark.asyncio
async def test_get_unknown_artifact_is_404_problem(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with _client(app) as client:
        resp = await client.get(f"/artifacts/{'9f' * 32}", headers=_cap("t" * 64))
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_get_artifact_with_traversal_id_cannot_escape_the_store(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("nope")
    app = _make_app(tmp_path)
    async with _client(app) as client:
        # INVARIANT: a malformed id resolves to nothing — never to a file outside the store.
        resp = await client.get("/artifacts/..%2Fsecret.txt", headers=_cap("t" * 64))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_artifact_without_capability_is_401(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text("guarded")
    async with _client(app) as client:
        resp = await client.get(f"/artifacts/{ref.id}")
    assert resp.status_code == 401
    # The parcel survives an unauthorized knock.
    assert store.path_for(ref.id) is not None


def test_startup_sweeps_stale_artifacts_but_keeps_fresh_ones(tmp_path: Path) -> None:
    import os
    import time

    store = ArtifactStore(tmp_path / "artifacts")
    stale = store.write_text("stale parcel")
    fresh = store.write_text("fresh parcel")
    stale_path = store.path_for(stale.id)
    assert stale_path is not None
    old = time.time() - 3 * 86_400
    os.utime(stale_path, (old, old))

    app = _make_app(tmp_path, artifact_ttl_s=86_400)
    with TestClient(app):  # entering the context runs startup hooks
        assert store.path_for(stale.id) is None
        assert store.path_for(fresh.id) is not None


def test_sync_result_response_serves_artifact_content(tmp_path: Path) -> None:
    # WHY: the transactional HTTP-GET path is the SECOND consumer of the result frame; an
    # artifact result must resolve to the same complete bytes there, not to an empty body.
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text('{"score":1}')
    event = ResultEvent(
        id="res-x",
        source="/trace/x/node/root",
        subject="x",
        data=ResultData(artifact=ref),
    )
    response = _result_response(event, store)
    assert response.status_code == 200


def test_sync_result_response_of_redeemed_artifact_is_a_problem(tmp_path: Path) -> None:
    from screamingface_engine.auth.problem import ProblemException

    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text("gone soon")
    store.delete(ref.id)
    event = ResultEvent(
        id="res-y",
        source="/trace/y/node/root",
        subject="y",
        data=ResultData(artifact=ref),
    )
    with pytest.raises(ProblemException):
        _result_response(event, store)


def test_sweep_runs_periodically_while_the_app_stays_up(tmp_path: Path) -> None:
    import os
    import time

    # WHY: a hosted Engine pod can stay up for weeks — a startup-only sweep would let
    # abandoned parcels pool until the next redeploy. The sweep must recur while alive.
    store = ArtifactStore(tmp_path / "artifacts")
    app = _make_app(tmp_path, artifact_ttl_s=86_400, artifact_sweep_interval_s=0.05)
    with TestClient(app):
        # Born AFTER startup, so the boot sweep cannot have been the one to collect it.
        stale = store.write_text("abandoned while the app is running")
        stale_path = store.path_for(stale.id)
        assert stale_path is not None
        old = time.time() - 3 * 86_400
        os.utime(stale_path, (old, old))

        deadline = time.time() + 5.0
        while store.path_for(stale.id) is not None and time.time() < deadline:
            time.sleep(0.05)
        assert store.path_for(stale.id) is None

    # Shutdown cancels the sweeper: no background task survives the app.
    task = getattr(app.state, "artifact_sweep_task", None)
    assert task is None or task.cancelled() or task.done()
