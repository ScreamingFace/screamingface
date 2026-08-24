"""Route-level evidence for the admin cache-snapshot upload (OME-952).

What is pinned here is the ROUTE layer: the admin gate applies to every route exactly as it
does to the account routes, the synchronous refusals answer their HTTP codes (400 mode /
400 dialect / 413 size / 409 busy), the upload hands the runner a spooled file plus a digest,
and the job/job-list endpoints serialize records with the fields the console polls. The load
itself is the runner's decision (pinned in `test_cache_upload_job_runner.py`) and Postgres's
behaviour (pinned in the integration module).

The fixture database is SQLite, so every upload test patches the route module's Postgres
guard — the guard's own answer is pinned unpatched in `test_the_dialect_guard_answers_400`.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from ipaddress import ip_network
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import aigateway.routes.admin_cache as admin_cache
from aigateway.core.request_cache.bulk_loader import LoadOutcome
from aigateway.core.request_cache.upload_job import (
    CacheJobRecord,
    CacheUploadBusy,
    CacheUploadRunner,
    UploadAcceptance,
)

ADMIN = "admin@openmined.org"
POD_NETWORK = ip_network("10.0.0.0/8")


class ImmediateLoader:
    """Completes synchronously, capturing the spooled bytes at call time (they are deleted)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, path: Path, **kwargs: Any) -> LoadOutcome:
        self.calls.append({"path": path, "content": path.read_bytes(), **kwargs})
        return LoadOutcome(staged_rows=1, live_before=0, live_after=1)


def _runner() -> tuple[CacheUploadRunner, ImmediateLoader]:
    loader = ImmediateLoader()
    return (
        CacheUploadRunner(
            loader=loader,
            revisions=lambda: {"parameter_contract": "aigw-parameter-contract-2026-08b"},
        ),
        loader,
    )


def _admin_client(client: TestClient, runner: CacheUploadRunner | None = None) -> TestClient:
    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (POD_NETWORK,)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    if runner is not None:
        client.app.state.cache_upload_runner = runner
    return TestClient(client.app, client=("10.1.2.3", 50000))


def _headers() -> dict[str, str]:
    return {"X-User-Email": ADMIN}


def _files(payload: bytes = b"--\npayload\n") -> list[tuple[str, tuple[str, bytes, str]]]:
    import gzip

    return [("snapshot", ("snap.sql.gz", gzip.compress(payload), "application/gzip"))]


def _poll_terminal(runner: CacheUploadRunner, job_id: uuid.UUID) -> CacheJobRecord:
    """Wait for the app-loop-driven job to finish; the record is shared state."""
    for _ in range(10_000):
        job = runner.get(job_id)
        assert job is not None
        if job.finished_at is not None:
            return job
        time.sleep(0.001)
    raise AssertionError("job never reached a terminal state")


# --- auth --------------------------------------------------------------------------------------


def test_every_cache_route_requires_an_admin(client) -> None:
    unauthenticated = TestClient(client.app, client=("10.1.2.3", 50000))
    for method, path in (
        ("get", "/v1/admin/cache/info"),
        ("get", "/v1/admin/cache/snapshots/jobs"),
        ("post", "/v1/admin/cache/snapshots"),
        ("get", f"/v1/admin/cache/snapshots/jobs/{uuid.uuid4()}"),
    ):
        if method == "post":
            resp = unauthenticated.post(path, files=_files(), headers=_headers())
        else:
            resp = unauthenticated.get(path, headers=_headers())
        assert resp.status_code in (401, 403, 503), (method, path, resp.status_code)


def test_a_non_admin_is_refused_exactly_like_the_account_routes(client) -> None:
    admin_client = _admin_client(client, _runner()[0])
    resp = admin_client.get("/v1/admin/cache/info", headers={"X-User-Email": "stranger@x.org"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This account is not an administrator of this gateway."


# --- info --------------------------------------------------------------------------------------


def test_info_reports_serving_state_count_and_live_revisions(client) -> None:
    admin_client = _admin_client(client, _runner()[0])
    resp = admin_client.get("/v1/admin/cache/info", headers=_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["serving"] is False  # the client fixture's default setting is cache-off
    assert body["row_count"] == 0
    assert body["revisions"]["parameter_contract"] == "aigw-parameter-contract-2026-08b"
    assert body["revisions"]["openrouter_adapter"] == "openrouter-global-cache-2026-08d"


# --- upload ------------------------------------------------------------------------------------


def test_an_upload_spools_the_archive_and_records_the_job(client, monkeypatch) -> None:
    monkeypatch.setattr(admin_cache, "_postgres_active", lambda: True)
    import gzip

    runner, loader = _runner()
    admin_client = _admin_client(client, runner)
    resp = admin_client.post(
        "/v1/admin/cache/snapshots",
        files=_files(b"payload-bytes"),
        data={"mode": "merge"},
        headers=_headers(),
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["actor"] == ADMIN
    record = _poll_terminal(runner, uuid.UUID(job["id"]))
    assert record.state == "complete"
    # The spool holds the upload VERBATIM (the loader opens/gunzips it itself), and deletes
    # it once terminal.
    assert gzip.decompress(loader.calls[0]["content"]) == b"payload-bytes"
    assert not Path(loader.calls[0]["path"]).exists()


def test_an_unknown_mode_is_a_400(client, monkeypatch) -> None:
    monkeypatch.setattr(admin_cache, "_postgres_active", lambda: True)
    admin_client = _admin_client(client, _runner()[0])
    resp = admin_client.post(
        "/v1/admin/cache/snapshots",
        files=_files(),
        data={"mode": "append"},
        headers=_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "cache_upload_bad_mode"


def test_a_snapshot_over_the_cap_is_a_413(client, monkeypatch) -> None:
    monkeypatch.setattr(admin_cache, "_postgres_active", lambda: True)
    runner, _ = _runner()
    runner.max_upload_bytes = 8
    admin_client = _admin_client(client, runner)
    resp = admin_client.post(
        "/v1/admin/cache/snapshots",
        files=_files(b"this payload is far beyond eight bytes"),
        headers=_headers(),
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "cache_upload_too_large"


def test_a_running_load_makes_a_second_upload_409(client, monkeypatch) -> None:
    monkeypatch.setattr(admin_cache, "_postgres_active", lambda: True)

    class BusyRunner:
        max_upload_bytes = 1024 * 1024

        def start(self, acceptance: UploadAcceptance) -> None:
            raise CacheUploadBusy("occupied")

        def jobs(self) -> list[CacheJobRecord]:
            return []

        def get(self, job_id: uuid.UUID) -> CacheJobRecord | None:
            return None

        def busy(self) -> bool:
            return True

    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (POD_NETWORK,)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    client.app.state.cache_upload_runner = BusyRunner()  # type: ignore[assignment]
    admin_client = TestClient(client.app, client=("10.1.2.3", 50000))
    resp = admin_client.post("/v1/admin/cache/snapshots", files=_files(), headers=_headers())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cache_load_in_progress"


def test_the_dialect_guard_answers_400_on_non_postgres(client) -> None:
    admin_client = _admin_client(client, _runner()[0])
    resp = admin_client.post("/v1/admin/cache/snapshots", files=_files(), headers=_headers())
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "cache_upload_unsupported_database"


# --- jobs --------------------------------------------------------------------------------------


def test_jobs_list_and_job_by_id_serialize_the_record(client) -> None:
    runner, _ = _runner()
    record = CacheJobRecord(
        id=uuid.uuid4(),
        actor=ADMIN,
        mode="merge",
        created_at=datetime.now(UTC),
        state="complete",
        staged_rows=10,
        live_before=4,
        live_after=10,
        inserted_rows=6,
        updated_rows=4,
        warnings=["revisions_unverified"],
    )
    runner._jobs.append(record)
    admin_client = _admin_client(client, runner)

    listed = admin_client.get("/v1/admin/cache/snapshots/jobs", headers=_headers())
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["id"] == str(record.id)
    assert listed.json()["jobs"][0]["warnings"] == ["revisions_unverified"]

    one = admin_client.get(f"/v1/admin/cache/snapshots/jobs/{record.id}", headers=_headers())
    assert one.status_code == 200
    assert one.json()["inserted_rows"] == 6

    missing = admin_client.get(f"/v1/admin/cache/snapshots/jobs/{uuid.uuid4()}", headers=_headers())
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "cache_job_not_found"


@pytest.mark.parametrize(
    "refusal", ["checksum_mismatch", "revision_mismatch", "newer_rows_would_be_lost"]
)
def test_refusal_codes_round_trip_through_the_job_record(client, refusal) -> None:
    """The console renders `refusal` verbatim — the codes are API and must not be renamed."""
    from aigateway.core.request_cache.upload_job import REFUSAL_CODES

    assert refusal in REFUSAL_CODES
