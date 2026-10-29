"""`PUT|GET /blob/sha256/<hex>` — the blob store's HTTP surface (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529). STORY: as a url4 client I upload a picture with my
run's capability token, get back `blob:sha256/<hex>`, and name it in the expression I then start
with the same token.

INVARIANT (owner decision 2026-10-28, Q1a/Q2a): both routes need `URL4-Capability`; a blob is
stored under the token's topic (the run) and the caller's verified `X-User-Email` (or the fixed
`anonymous` partition). A digest from another run or tenant is 404 `source_not_found`, the same
answer as a digest nobody uploaded.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

SECRET = "rest-blob-routes-secret-0123456789abcdef0123"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=UTC)
RUN_A = "a" * 64
RUN_B = "b" * 64
PDF = b"%PDF-1.7\n" + b"page" * 50
PDF_HEX = hashlib.sha256(PDF).hexdigest()
PATH = f"/blob/sha256/{PDF_HEX}"


def _cap(topic: str = RUN_A, email: str | None = "alice@example.org") -> dict[str, str]:
    headers = {
        "URL4-Capability": JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, T0)
    }
    if email is not None:
        headers["X-User-Email"] = email
    return headers


def _app(tmp_path: Path, **overrides: object) -> FastAPI:
    settings = Settings.model_validate(
        {
            "jwt_secret": SECRET,
            "iat_window_s": WINDOW_S,
            "artifacts_dir": str(tmp_path / "artifacts"),
            **overrides,
        }
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner(), clock=lambda: T0
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _put(
    client: httpx.AsyncClient,
    *,
    body: bytes = PDF,
    path: str = PATH,
    media_type: str = "application/pdf",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    sent = {**(_cap() if headers is None else headers), "Content-Type": media_type}
    return await client.put(path, content=body, headers=sent)


@pytest.mark.asyncio
async def test_upload_then_fetch_round_trips_bytes_and_media_type(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        put = await _put(client)
        got = await client.get(PATH, headers=_cap())

    assert put.status_code == 201, put.text
    assert put.json() == {
        "ref": f"blob:sha256/{PDF_HEX}",
        "sha256": PDF_HEX,
        "size_bytes": len(PDF),
        "media_type": "application/pdf",
    }
    assert got.status_code == 200, got.text
    assert got.content == PDF
    assert got.headers["content-type"] == "application/pdf"
    # WHY: user-supplied bytes are served back; a browser must not sniff them into HTML.
    assert got.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_a_repeat_upload_is_200_with_the_same_ref(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        first = await _put(client)
        again = await _put(client)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "GET"])
async def test_both_routes_need_a_capability_token(tmp_path: Path, method: str) -> None:
    async with _client(_app(tmp_path)) as client:
        response = await client.request(method, PATH, content=PDF if method == "PUT" else None)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_digest_mismatch_at_ingest_is_422(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        response = await _put(client, path=f"/blob/sha256/{'0' * 64}")
    assert response.status_code == 422
    assert response.json()["code"] == "x.blob_digest_mismatch"
    assert response.json()["permanent"] is True


@pytest.mark.asyncio
async def test_an_oversize_upload_is_413(tmp_path: Path) -> None:
    async with _client(_app(tmp_path, blob_max_bytes=len(PDF) - 1)) as client:
        response = await _put(client)
    assert response.status_code == 413
    assert response.json()["code"] == "x.blob_too_large"


@pytest.mark.asyncio
async def test_a_disallowed_media_type_is_415(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        response = await _put(client, media_type="text/html")
    assert response.status_code == 415
    assert response.json()["code"] == "x.blob_unsupported_media_type"


@pytest.mark.asyncio
async def test_the_media_type_allowlist_is_configurable(tmp_path: Path) -> None:
    async with _client(_app(tmp_path, blob_media_types=["image/png"])) as client:
        response = await _put(client)
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_an_unknown_digest_is_404_source_not_found(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        response = await client.get(f"/blob/sha256/{'0' * 64}", headers=_cap())
    assert response.status_code == 404
    assert response.json()["code"] == "source_not_found"


@pytest.mark.asyncio
async def test_a_digest_from_another_run_is_the_same_404(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        await _put(client)
        unknown = await client.get(f"/blob/sha256/{'0' * 64}", headers=_cap(RUN_B))
        other_run = await client.get(PATH, headers=_cap(RUN_B))
    assert other_run.status_code == 404
    # INVARIANT (F3): indistinguishable from a missing blob — same status, same body.
    assert other_run.json() == unknown.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["bob@example.org", None])
async def test_a_digest_from_another_tenant_is_404(tmp_path: Path, email: str | None) -> None:
    async with _client(_app(tmp_path)) as client:
        await _put(client)
        response = await client.get(PATH, headers=_cap(RUN_A, email))
    assert response.status_code == 404
    assert response.json()["code"] == "source_not_found"


@pytest.mark.asyncio
async def test_a_caller_without_identity_reads_back_its_own_upload(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        await _put(client, headers=_cap(RUN_A, None))
        response = await client.get(PATH, headers=_cap(RUN_A, None))
    assert response.status_code == 200
    assert response.content == PDF


@pytest.mark.asyncio
async def test_corrupted_stored_bytes_are_500_digest_mismatch(tmp_path: Path) -> None:
    async with _client(_app(tmp_path)) as client:
        await _put(client)
        [data] = [p for p in (tmp_path / "artifacts").rglob(PDF_HEX) if p.is_file()]
        data.write_bytes(b"bit rot")
        response = await client.get(PATH, headers=_cap())
    assert response.status_code == 500
    assert response.json()["code"] == "x.blob_digest_mismatch"
    assert "bit rot" not in response.text


def test_the_artifact_startup_sweep_also_ages_out_blobs(tmp_path: Path) -> None:
    """Retention reuses the artifact TTL sweep (owner decision Q4a): the App's startup sweep
    reclaims a blob older than `artifact_ttl_s` and keeps a young one."""
    app = _app(tmp_path, artifact_ttl_s=60)
    with TestClient(app) as client:
        client.put(PATH, content=PDF, headers={**_cap(), "Content-Type": "application/pdf"})
    old = time.time() - 10_000
    for path in (tmp_path / "artifacts" / "blobs").rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))

    with TestClient(app) as client:  # entering the context runs the startup sweep
        response = client.get(PATH, headers=_cap())

    assert response.status_code == 404
