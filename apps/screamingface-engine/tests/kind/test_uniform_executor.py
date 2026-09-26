"""The uniform executor kind suite (test-plan §5). Every case needs the live cluster
`deploy/kind/up.sh` brings up; the whole module skips cleanly when kind context
`kind-sf-uniform` is unreachable (`_cluster.kind_reachable`), the same shape
`tests/integration/test_worker_spine.py` uses for its NATS-reachability skip.

K1, K2, K3, K6 and K12 are real assertions (test-plan §7 phase exit criteria). K4, K5 and
K7-K11 are named stubs — the scenario is in each docstring, and the orchestrator implements
them next (they need real object storage redemption, a runner-pod kill, a NATS restart, and a
pre-upgrade legacy stream respectively; none of that is wired here yet).
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import websockets
from _cluster import KIND_CONTEXT, NAMESPACE, kind_reachable, port_forward
from _helpers import (
    DATA_MOUNT,
    EXPRESSION,
    IDENTITY,
    MODEL_MOUNT,
    assert_gapfree,
    gauge_value,
    mint_token,
    run_async_over_ws,
    ws_uri,
)

_KIND_REACHABLE = kind_reachable()

pytestmark = [
    pytest.mark.kind,
    pytest.mark.skipif(
        not _KIND_REACHABLE,
        reason=f"kind context {KIND_CONTEXT!r} is not reachable — run deploy/kind/up.sh",
    ),
]

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART_DIR = _APP_ROOT / "deploy/helm"
_VALUES_FILE = _APP_ROOT / "deploy/kind/values-kind.yaml"
_RELEASE = "sf-uniform"


# --------------------------------------------------------------------------------------------
# K1 — async run with WebSocket attach: frames 1..n, no gap, a result.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k1_async_run_with_ws_attach_is_gapfree_and_carries_a_result(
    app_base_url: str,
) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=30.0) as client:
        token = await mint_token(client)
        async with websockets.connect(ws_uri(app_base_url, token)) as ws:
            response, frames = await run_async_over_ws(client, ws, token)

    assert response.status_code == 202, response.text
    assert_gapfree(frames)
    types = [frame["type"] for frame in frames]
    assert "ai.url4.result" in types, types
    assert types[-1] == "ai.url4.terminated", types


# --------------------------------------------------------------------------------------------
# K2 — sync GET /?q= with no WebSocket -> 200.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k2_sync_get_without_a_websocket_returns_200(app_base_url: str) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=30.0) as client:
        token = await mint_token(client)
        response = await client.get(
            "/", params={"q": EXPRESSION}, headers={"URL4-Capability": token, **IDENTITY}
        )

    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------------------------
# K3 — mount call -> 200; /openapi.json lists both mounts.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k3_mount_calls_succeed_and_openapi_lists_both_mounts(app_base_url: str) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=30.0) as client:
        model_response = await client.get(MODEL_MOUNT, params={"q": EXPRESSION}, headers=IDENTITY)
        data_response = await client.get(DATA_MOUNT, headers=IDENTITY)
        openapi = (await client.get("/openapi.json")).json()

    assert model_response.status_code == 200, model_response.text
    assert data_response.status_code == 200, data_response.text
    assert data_response.text == "rows of papers"
    assert data_response.headers["content-type"].startswith("text/plain")
    paths = openapi["paths"]
    assert MODEL_MOUNT in paths, sorted(paths)
    assert DATA_MOUNT in paths, sorted(paths)


# --------------------------------------------------------------------------------------------
# K6 — 50 concurrent mixed runs: every subject gap-free; no per-topic (`url4-cloud_*`) stream.
# --------------------------------------------------------------------------------------------
async def _one_ws_run(app_base_url: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        token = await mint_token(client)
        async with websockets.connect(ws_uri(app_base_url, token)) as ws:
            _, frames = await run_async_over_ws(client, ws, token)
    return frames


async def _one_sync_run(app_base_url: str) -> httpx.Response:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        token = await mint_token(client)
        return await client.get(
            "/", params={"q": EXPRESSION}, headers={"URL4-Capability": token, **IDENTITY}
        )


@pytest.mark.asyncio
async def test_k6_fifty_concurrent_mixed_runs_are_gapfree_with_no_legacy_stream(
    app_base_url: str, nats_local_port: int
) -> None:
    ws_runs = 25
    sync_runs = 25

    ws_results, sync_results = await asyncio.gather(
        asyncio.gather(*(_one_ws_run(app_base_url) for _ in range(ws_runs))),
        asyncio.gather(*(_one_sync_run(app_base_url) for _ in range(sync_runs))),
    )

    for frames in ws_results:
        assert_gapfree(frames)
        assert frames[-1]["type"] == "ai.url4.terminated", frames[-1]
    for response in sync_results:
        assert response.status_code == 200, response.text

    from nats.aio.client import Client as NatsClient

    nc = NatsClient()
    try:
        await nc.connect(f"nats://127.0.0.1:{nats_local_port}")
        js = nc.jetstream()
        streams = await js.streams_info()
    finally:
        await nc.close()
    names = [stream.config.name for stream in streams if stream.config.name is not None]
    legacy = [name for name in names if name.startswith("url4-cloud_")]
    assert legacy == [], f"legacy per-topic stream(s) still exist: {legacy} (all streams: {names})"
    assert "url4-events" in names, names


# --------------------------------------------------------------------------------------------
# K12 — events store near full (a small events.maxBytes) -> the utilization gauge > 0.8.
# --------------------------------------------------------------------------------------------
def _helm_upgrade(*extra: str) -> None:
    subprocess.run(
        [
            "helm",
            "upgrade",
            "--install",
            _RELEASE,
            str(_CHART_DIR),
            "--kube-context",
            KIND_CONTEXT,
            "--namespace",
            NAMESPACE,
            "-f",
            str(_VALUES_FILE),
            *extra,
            "--wait",
            "--timeout",
            "3m",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_k12_events_store_near_full_raises_the_utilization_gauge() -> None:
    """`events.maxBytes` set small enough that ~20 runs' frames approach it; the App's
    `screamingface_engine_events_store_utilization_ratio` gauge (`metrics.py`,
    `_EventsStoreMonitor`, polled every 15s) must cross 0.8 — the chart's own alert threshold
    (deploy/helm/README.md). Restores the base values afterwards regardless of the outcome.
    """
    small_max_bytes = 131072  # 128 KiB — the base 8 GiB default divided down to fill fast.
    _helm_upgrade("--set", f"events.maxBytes={small_max_bytes}")
    try:
        with port_forward("sf-uniform-url4-cloud", 9108) as local_port:
            base_url = f"http://127.0.0.1:{local_port}"
            async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
                for _ in range(30):
                    token = await mint_token(client)
                    await client.get(
                        "/",
                        params={"q": EXPRESSION},
                        headers={"URL4-Capability": token, **IDENTITY},
                    )

                ratio: float | None = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    metrics_text = (await client.get("/metrics")).text
                    ratio = gauge_value(
                        metrics_text, "screamingface_engine_events_store_utilization_ratio"
                    )
                    if ratio is not None and ratio > 0.8:
                        break
                    await asyncio.sleep(2)
    finally:
        _helm_upgrade()

    assert ratio is not None and ratio > 0.8, f"utilization ratio never exceeded 0.8: {ratio}"


# --------------------------------------------------------------------------------------------
# K4, K5, K7-K11 — TODO stubs for the orchestrator.
# --------------------------------------------------------------------------------------------
def test_k4_mount_call_with_a_1_5_mib_reply_spills_to_the_artifact_store() -> None:
    """K4: a mount call whose stub reply carries `X-Stub-Bytes: 1572864` (1.5 MiB) exceeds the
    mount route's 1 MiB inline limit and must answer `303` with a `Location` the App itself can
    redeem `200` from (`rest/artifacts.py`, `ArtifactReader.content()`), on the real Garage-backed
    S3 store this environment already runs."""
    pytest.skip("TODO: mount call with a 1.5 MiB stub reply -> 303 -> artifact fetch 200")


def test_k5_mount_call_that_hangs_upstream_times_out_and_terminates_the_run() -> None:
    """K5: a mount call whose stub reply carries `X-Stub-Fail: hang` (aigw-stub sleeps 3600s)
    must answer `504` at the mount's own wait bound, and the run's subject must carry a
    `Terminated(stopped)` frame — the handler stops the run itself before answering (D5/M6,
    implementation-notes.md)."""
    pytest.skip("TODO: mount call with X-Stub-Fail: hang -> 504 and Terminated(stopped)")


def test_k7_killing_a_runner_pod_mid_run_redelivers_to_exactly_one_terminal_frame() -> None:
    """K7: `kubectl delete pod` on the runner pod holding an in-flight run's slot must cause
    JetStream redelivery to a surviving replica, and the run's shared-stream subject must end
    with EXACTLY ONE terminal frame (D3/D3a's redelivery rebase, implementation-notes.md) —
    never two, never zero."""
    pytest.skip("TODO: kill one runner pod during a run -> redelivery -> one terminal frame")


def test_k8_a_run_past_its_memory_budget_is_oom_killed_without_taking_its_siblings() -> None:
    """K8: a run whose child process allocates past its budget must end `oom_killed` (the
    warm-pool RLIMIT_AS cap, WRM-8) while every OTHER run sharing the same worker pod finishes
    normally — the isolation the warm child pool (PRD 03) claims across runs sharing one pod."""
    pytest.skip("TODO: a run that allocates past its budget -> oom_killed; siblings finish")


def test_k9_a_runner_rollout_restart_drains_and_kills_idle_warm_children_first() -> None:
    """K9: `kubectl rollout restart` of the runner pool mid-run must drain in-flight runs
    (`worker_drain_grace_s`) before terminating, and among a pod's warm children the IDLE ones
    must die before a warm child that is mid-hand-off or mid-run (`WarmChildPool` drain
    ordering, PRD 03)."""
    pytest.skip("TODO: rollout restart during runs -> drain; idle warm children die first")


def test_k10_restarting_the_nats_pod_mid_run_stays_gapfree_or_fails_named() -> None:
    """K10: restarting the NATS pod during a live run must either keep every later frame
    gap-free once the broker comes back (EV-16), or the run must end with a named
    `failed/stream_failed` — never a silent gap and never a second, contradictory terminal
    frame."""
    pytest.skip("TODO: restart the NATS pod during a run -> gap-free, or failed/stream_failed")


def test_k11_purge_legacy_streams_after_a_drained_upgrade_from_the_old_chart() -> None:
    """K11: on a cluster carrying a legacy `url4-cloud_<topic>` stream from the pre-PRD-01
    chart, the new image's App/worker must refuse to start (implementation-notes.md D7, err
    10065) until `admin purge-legacy-streams` runs — this test needs to seed a legacy-shaped
    stream first, which needs the OLD chart's stream-declaration code path, not just a values
    tweak on the new chart."""
    pytest.skip("TODO: purge-legacy-streams after a drained upgrade from the previous chart")
