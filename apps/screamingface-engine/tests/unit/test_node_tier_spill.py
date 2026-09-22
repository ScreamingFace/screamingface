"""u3-spill — the node tier's 512 KiB spill and short-lived signed redirect (D9, OQ-3.2).

FEATURE (unit 3, prd/03 §2.4): a sync response body over the inline cap is parked in the
artifact store and the caller gets ``303 See Other`` with a signed ``Location``; a body over
the hard cap fails ``413`` and writes nothing; a spill write that fails is ``502`` and the body
is NEVER returned inline.

WHY the spill is on the node's response path: the node signs the URL (contracts.md C6), and the
App verifies it. The store is the SAME writer the run path uses (prd/03 T5 refactor note), so
this file pins the boundary against that one store rather than a private copy.

Stubbed aigateway throughout: no real external API is called, so the suite runs offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport
from test_aigateway_connector import _MockAigateway

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.artifacts import ArtifactStore, signing
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.node_tier import (
    NodeTier,
    NodeTierError,
    NodeTierSettings,
    build_node_tier,
)

_MODEL = "anthropic/claude-haiku-4-5"
_KEY = "u3-spill-artifact-signing-key-0123456789abcdef"
_NOW = 1_000_000.0
_TTL = 600
# The shipped inline cap is the D9 512 KiB threshold; tests that need an exact boundary inject
# small caps rather than allocate half a megabyte per case.
_INLINE = job_env.DEFAULT_RESULT_INLINE_CAP_BYTES


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL),),
        )
    )


def _settings(**overrides: object) -> NodeTierSettings:
    base = {"request_timeout_s": 5.0, "aigateway_timeout_s": 4.0, "artifact_url_ttl_s": _TTL}
    return NodeTierSettings(**{**base, **overrides})  # type: ignore[arg-type]


async def _serve(
    tmp_path: Path,
    *,
    body: str,
    settings: NodeTierSettings | None = None,
    signing_key: str | None = _KEY,
    store: object | None = None,
) -> tuple[NodeTier, ArtifactStore, httpx.AsyncClient, _MockAigateway]:
    """A started node tier over a stubbed aigateway and a filesystem spill store."""
    gw = _MockAigateway((_MODEL,), responses={_MODEL: body})
    resolved_store = store if store is not None else ArtifactStore(tmp_path / "artifacts")
    client = gw.client()
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=settings or _settings(),
        artifact_store=resolved_store,  # type: ignore[arg-type]
        artifact_signing_key=signing_key,
        clock=lambda: _NOW,
    )
    return tier, resolved_store, client, gw  # type: ignore[return-value]


def _node_client(tier: NodeTier) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=tier), base_url="http://node.test")


async def _get_mount(node: httpx.AsyncClient) -> httpx.Response:
    return await node.get(
        f"/{_MODEL}", params={"q": "('')!'go'"}, headers={"X-User-Email": "a@x.test"}
    )


def _artifact_id(location: str) -> str:
    return location.split("?", 1)[0].rsplit("/", 1)[-1]


def _app(tmp_path: Path, *, signing_key: str) -> FastAPI:
    settings = Settings(
        jwt_secret="u3-spill-secret-u3-spill-secret",
        artifacts_dir=str(tmp_path / "artifacts"),
        artifact_signing_key=signing_key,
    )
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        # The node signs with a fixed clock in these tests; the App must verify against the SAME
        # instant or the round trip is testing wall-clock drift, not the credential.
        clock=lambda: datetime.fromtimestamp(_NOW, tz=UTC),
    )


# --- T5: a large body spills and the redirect is fetchable -----------------------------------


@pytest.mark.asyncio
async def test_an_over_512kib_response_redirects_to_a_signed_artifact_location(
    tmp_path: Path,
) -> None:
    """AC15: over the 512 KiB inline cap → 303 with a signed Location under /artifacts/."""
    body = "X" * (_INLINE + 1)
    tier, store, client, _gw = await _serve(tmp_path, body=body)
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 303, response.text
        location = response.headers["location"]
        assert location.startswith("/artifacts/")
        assert f"{signing.EXPIRY_PARAM}={int(_NOW) + _TTL}" in location
        assert f"{signing.SIGNATURE_PARAM}=" in location
        # The complete body was parked; the redirect is not a truncation.
        stored = store.path_for(_artifact_id(location))
        assert stored is not None
        assert stored.read_bytes() == body.encode("utf-8")
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_the_signed_location_fetches_without_a_token_and_bare_is_refused(
    tmp_path: Path,
) -> None:
    """AC15: the redirect is fetchable with NO capability token; the same id bare is refused."""
    body = "Y" * (_INLINE + 1)
    tier, _store, client, _gw = await _serve(tmp_path, body=body)
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 303
        location = response.headers["location"]
    finally:
        await tier.aclose()
        await client.aclose()

    app = _app(tmp_path, signing_key=_KEY)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as app_client:
        signed = await app_client.get(location)
        bare = await app_client.get(f"/artifacts/{_artifact_id(location)}")

    assert signed.status_code == 200, signed.text
    assert signed.text == body
    # Bare — no token, no signature — behaves exactly as today.
    assert bare.status_code == 401


# --- T6: the hard cap rejects BEFORE the spill, and writes nothing ---------------------------


@pytest.mark.asyncio
async def test_an_over_hard_cap_response_is_413_and_writes_nothing(tmp_path: Path) -> None:
    """AC16: above `result_hard_cap_bytes` → 413 and the store is untouched."""
    settings = _settings(result_inline_cap_bytes=100, result_hard_cap_bytes=200)
    tier, store, client, _gw = await _serve(tmp_path, body="Z" * 201, settings=settings)
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "result_too_large"
        assert "201" in response.json()["error"]["message"]
        assert "200" in response.json()["error"]["message"]
        # INVARIANT: an over-cap body is never deposited — not even to be swept later.
        root = tmp_path / "artifacts"
        assert not root.exists() or not any(root.iterdir())
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_the_hard_cap_wins_even_when_the_caps_are_inverted(tmp_path: Path) -> None:
    """T6: inverted caps can no longer reach the send boundary — FX-13 refuses them at boot.

    WHY updated (04-review-fixes FX-13): the tier used to serve inverted caps and rely on the
    hard-cap-first order; `NodeTierSettings.validate()` now refuses them before the world is
    built, so a huge inline cap still cannot bypass the ceiling, and nothing is written.
    """
    settings = _settings(result_inline_cap_bytes=100, result_hard_cap_bytes=30)
    with pytest.raises(NodeTierError, match="result_inline_cap_bytes"):
        await _serve(tmp_path, body="Z" * 50, settings=settings)
    assert not (tmp_path / "artifacts").exists() or not any((tmp_path / "artifacts").iterdir())


@pytest.mark.asyncio
async def test_a_spill_write_failure_is_502_and_never_returns_the_body_inline(
    tmp_path: Path,
) -> None:
    """C5: a failed deposit is 502 — falling back to inline would defeat the memory cap."""

    class _FailingStore:
        def write_bytes(self, encoded: bytes) -> object:
            raise OSError("disk full")

        def write_text(self, body: str) -> object:  # pragma: no cover - port completeness
            raise OSError("disk full")

    body = "Q" * (_INLINE + 1)
    tier, _store, client, _gw = await _serve(tmp_path, body=body, store=_FailingStore())
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "artifact_spill_failed"
        # The 200-byte-ish error envelope must not contain the response body.
        assert body not in response.text
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_spill_with_no_signing_key_is_502_and_not_inline(tmp_path: Path) -> None:
    """A missing signing key means an unfetchable redirect; the tier now refuses to START.

    WHY updated (04-review-fixes FX-9): an empty key used to be tolerated at build and failed
    each spill with a 502. `build_node_tier` now raises `NodeTierError`, so a pod with no key
    never serves at all — and the body is still never returned inline, because nothing serves.
    """
    body = "Q" * (_INLINE + 1)
    with pytest.raises(NodeTierError, match="signing key"):
        await _serve(tmp_path, body=body, signing_key="")
    assert not (tmp_path / "artifacts").exists() or not any((tmp_path / "artifacts").iterdir())


@pytest.mark.asyncio
async def test_the_signing_key_is_read_from_the_deployment_env(tmp_path: Path) -> None:
    """The chart injects the Secret as `URL4_CLOUD_ARTIFACT_SIGNING_KEY`; the tier reads it."""
    body = "E" * (_INLINE + 1)
    gw = _MockAigateway((_MODEL,), responses={_MODEL: body})
    client = gw.client()
    tier = await build_node_tier(
        env={job_env.ARTIFACT_SIGNING_KEY: _KEY},
        config=_config(),
        client=client,
        settings=_settings(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        clock=lambda: _NOW,
    )
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 303
        assert f"{signing.SIGNATURE_PARAM}=" in response.headers["location"]
    finally:
        await tier.aclose()
        await client.aclose()


# --- boundary values (test-plan §4): the inline cap and the hard cap -------------------------


@pytest.mark.parametrize(
    ("size", "expected_status", "spills"),
    [
        (99, 200, False),  # cap-1: inline
        (100, 200, False),  # exactly at cap: the largest inline body
        (101, 303, True),  # cap+1: one byte over spills
    ],
    ids=["cap-1-inline", "at-cap-inline", "cap+1-spills"],
)
@pytest.mark.asyncio
async def test_the_inline_cap_boundary_is_inclusive(
    tmp_path: Path, size: int, expected_status: int, spills: bool
) -> None:
    settings = _settings(result_inline_cap_bytes=100, result_hard_cap_bytes=1000)
    tier, store, client, _gw = await _serve(tmp_path, body="B" * size, settings=settings)
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == expected_status
        root = tmp_path / "artifacts"
        if spills:
            assert response.headers["location"].startswith("/artifacts/")
            assert root.exists() and any(root.iterdir())
        else:
            assert response.text == "B" * size
            assert not root.exists() or not any(root.iterdir())
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.parametrize(
    ("size", "expected_status"),
    [
        (99, 303),  # hard_cap-1: spills
        (100, 303),  # exactly at hard cap: still deliverable (spilled)
        (101, 413),  # hard_cap+1: refused, nothing written
    ],
    ids=["hard-cap-1-spills", "at-hard-cap-spills", "hard-cap+1-refused"],
)
@pytest.mark.asyncio
async def test_the_hard_cap_boundary_refuses_only_above(
    tmp_path: Path, size: int, expected_status: int
) -> None:
    settings = _settings(result_inline_cap_bytes=10, result_hard_cap_bytes=100)
    tier, store, client, _gw = await _serve(tmp_path, body="H" * size, settings=settings)
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == expected_status
        root = tmp_path / "artifacts"
        if expected_status == 413:
            assert not root.exists() or not any(root.iterdir())
    finally:
        await tier.aclose()
        await client.aclose()


# --- regression: a small body is byte-identical to before the spill path ---------------------


@pytest.mark.asyncio
async def test_a_small_body_still_returns_inline_unchanged(tmp_path: Path) -> None:
    tier, store, client, _gw = await _serve(tmp_path, body="PARIS")
    try:
        async with _node_client(tier) as node:
            response = await _get_mount(node)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.text == "PARIS"
        assert not (tmp_path / "artifacts").exists() or not any((tmp_path / "artifacts").iterdir())
    finally:
        await tier.aclose()
        await client.aclose()
