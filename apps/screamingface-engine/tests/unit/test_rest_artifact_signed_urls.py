"""u3-spill — `GET /artifacts/{id}` accepts a capability token OR a signed URL (OQ-3.2, C6).

FEATURE (unit 3, D9): the sync caller who is redirected to a spilled artifact holds no
capability token, so the redirect carries a short-lived signature. This file pins the App's
verification side: a valid unexpired signature fetches; an invalid or expired one is refused
exactly as a bad token is today; and a BARE request is unchanged — still 401.

INVARIANT (the whole point of choosing signed URLs): the existing route is NOT loosened. A
request with no credential of either kind behaves byte-for-byte as it did before this unit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.artifacts import ArtifactStore, signing
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

KEY = "u3-spill-artifact-signing-key-0123456789abcdef"
SECRET = "rest-artifact-signed-urls-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 8, 18, 9, 0, 0, tzinfo=UTC)
T0_TS = T0.timestamp()
EXP = int(T0_TS) + 600
_ID = "c" * 64
_BODY = "spilled result bytes"


def _cap(topic: str) -> dict[str, str]:
    return {
        "URL4-Capability": JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, T0)
    }


def _app(tmp_path: Path, *, signing_key: str = KEY) -> FastAPI:
    settings = Settings(
        jwt_secret=SECRET,
        iat_window_s=WINDOW_S,
        artifacts_dir=str(tmp_path / "artifacts"),
        artifact_signing_key=signing_key,
    )
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _signed_path(*, expires_at: int = EXP, key: str = KEY, artifact_id: str = _ID) -> str:
    sig = signing.sign_artifact_id(artifact_id, expires_at=expires_at, key=key)
    exp = f"{signing.EXPIRY_PARAM}={expires_at}"
    return f"/artifacts/{artifact_id}?{exp}&{signing.SIGNATURE_PARAM}={sig}"


@pytest.mark.asyncio
async def test_a_valid_signature_fetches_without_a_capability_token(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    signed = _signed_path(artifact_id=ref.id)
    app = _app(tmp_path)

    async with _client(app) as client:
        response = await client.get(signed)

    assert response.status_code == 200, response.text
    assert response.text == _BODY


@pytest.mark.asyncio
async def test_a_bare_request_is_still_401(tmp_path: Path) -> None:
    """INVARIANT: with no credential of either kind the route behaves exactly as before."""
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    app = _app(tmp_path)

    async with _client(app) as client:
        response = await client.get(f"/artifacts/{ref.id}")

    assert response.status_code == 401
    assert store.path_for(ref.id) is not None


@pytest.mark.asyncio
async def test_a_valid_capability_token_still_works(tmp_path: Path) -> None:
    """The existing path is unchanged: a token is accepted with signing configured."""
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    app = _app(tmp_path)

    async with _client(app) as client:
        response = await client.get(f"/artifacts/{ref.id}", headers=_cap("t" * 64))

    assert response.status_code == 200
    assert response.text == _BODY


@pytest.mark.asyncio
async def test_a_tampered_signature_is_401(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    app = _app(tmp_path)
    tampered = _signed_path(artifact_id=ref.id)
    tampered = tampered[:-1] + ("0" if tampered[-1] != "0" else "1")

    async with _client(app) as client:
        response = await client.get(tampered)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_signature_under_another_key_is_401(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    app = _app(tmp_path, signing_key=KEY)
    signed = _signed_path(artifact_id=ref.id, key="a-different-signing-key-0123456789abcdef")

    async with _client(app) as client:
        response = await client.get(signed)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_unconfigured_signing_key_never_accepts_a_signature(tmp_path: Path) -> None:
    """An empty key must not become a universal credential."""
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    app = _app(tmp_path, signing_key="")
    signed = _signed_path(artifact_id=ref.id, key=KEY)

    async with _client(app) as client:
        response = await client.get(signed)

    assert response.status_code == 401


# --- the expiry boundary (test-plan §4): n-1 / n / n+1 --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("clock_ts", "expected_status"),
    [
        (EXP - 1, 200),  # one second inside the window
        (EXP, 200),  # inclusive at expiry
        (EXP + 1, 401),  # one second past expiry
    ],
    ids=["inside", "at-expiry", "past-expiry"],
)
async def test_the_signature_expiry_boundary(
    tmp_path: Path, clock_ts: int, expected_status: int
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write_text(_BODY)
    settings = Settings(
        jwt_secret=SECRET,
        artifacts_dir=str(tmp_path / "artifacts"),
        artifact_signing_key=KEY,
    )
    app = create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        clock=lambda: datetime.fromtimestamp(clock_ts, tz=UTC),
    )
    signed = _signed_path(artifact_id=ref.id)

    async with _client(app) as client:
        response = await client.get(signed)

    assert response.status_code == expected_status
