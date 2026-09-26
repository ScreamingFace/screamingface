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
# Shared plumbing for K4-K11: read a run's frames straight off the shared events stream.
# --------------------------------------------------------------------------------------------
_RUNNER_DEPLOYMENT = "sf-uniform-url4-cloud-runner"
_APP_DEPLOYMENT = "sf-uniform-url4-cloud"
_NATS_POD = "sf-uniform-nats-0"


async def _subject_frames(nats_port: int, topic: str) -> list[dict]:
    """Every retained frame on `url4-cloud.<topic>` of `url4-events`, in stream order."""
    import json

    from nats.aio.client import Client as NatsClient

    nc = NatsClient()
    await nc.connect(f"nats://127.0.0.1:{nats_port}")
    try:
        js = nc.jetstream()
        subject = f"url4-cloud.{topic}"
        info = await js.stream_info("url4-events", subjects_filter=subject)
        count = (info.state.subjects or {}).get(subject, 0)
        frames: list[dict] = []
        if count:
            sub = await js.subscribe(subject, stream="url4-events", ordered_consumer=True)
            while len(frames) < count:
                msg = await sub.next_msg(timeout=10)
                frames.append(json.loads(msg.data))
            await sub.unsubscribe()
        return frames
    finally:
        await nc.close()


def _terminals(frames: list[dict]) -> list[dict]:
    return [frame for frame in frames if frame.get("type") == "ai.url4.terminated"]


def _kubectl(*args: str, timeout: float = 120.0) -> str:
    result = subprocess.run(
        ["kubectl", "--context", KIND_CONTEXT, "-n", NAMESPACE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _rollout(deployment: str) -> None:
    _kubectl("rollout", "status", f"deployment/{deployment}", "--timeout=300s", timeout=320)


async def _start_async(client: httpx.AsyncClient, expression: str) -> tuple[str, object]:
    """Mint a token, attach a WebSocket, start an async run; returns (topic, websocket)."""
    import base64
    import json

    token = await mint_token(client)
    payload = token.split(".")[1]
    topic = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]
    ws = await websockets.connect(ws_uri(str(client.base_url).rstrip("/"), token))
    from _helpers import attach

    await attach(ws)
    response = await client.get(
        "/",
        params={"q": expression},
        headers={"URL4-Capability": token, "Prefer": "respond-async", **IDENTITY},
    )
    assert response.status_code == 202, response.text
    return topic, ws


async def _until_terminal(nats_port: int, topic: str, timeout: float) -> list[dict]:
    deadline = time.monotonic() + timeout
    frames: list[dict] = []
    while time.monotonic() < deadline:
        frames = await _subject_frames(nats_port, topic)
        if _terminals(frames):
            return frames
        await asyncio.sleep(2)
    return frames


# --------------------------------------------------------------------------------------------
# K4 — a mount call with a 1.5 MiB reply -> 303 -> the signed artifact URL answers 200.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k4_mount_call_with_a_1_5_mib_reply_spills_to_the_artifact_store(
    app_base_url: str,
) -> None:
    size = 1536 * 1024
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        response = await client.get(
            MODEL_MOUNT, params={"q": f"('STUB_BYTES={size}')!'go'"}, headers=IDENTITY
        )
        assert response.status_code == 303, response.text
        location = response.headers["location"]
        assert location.startswith("/artifacts/") and "sig=" in location
        body = await client.get(location)
    assert body.status_code == 200
    assert len(body.content) >= size  # the stub's answer, at least its padding


# --------------------------------------------------------------------------------------------
# K5 — a mount call whose upstream hangs -> 504, and the run ends Terminated(stopped).
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k5_mount_call_that_hangs_upstream_times_out_and_terminates_the_run(
    app_base_url: str, nats_local_port: int
) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        response = await client.get(
            MODEL_MOUNT,
            params={"q": "('STUB_FAIL=hang')!'go'"},
            headers={**IDENTITY, "Prefer": "wait=3"},
        )
    assert response.status_code == 504, response.text
    topic = response.headers["x-url4-run"]
    frames = await _until_terminal(nats_local_port, topic, timeout=60)
    (terminal,) = _terminals(frames)
    assert terminal["data"]["status"] == "stopped", terminal


# --------------------------------------------------------------------------------------------
# K7 — kill the runner pod holding a run -> redelivery -> exactly one terminal frame.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k7_killing_a_runner_pod_mid_run_redelivers_to_exactly_one_terminal_frame(
    app_base_url: str, nats_local_port: int
) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        topic, ws = await _start_async(client, "('STUB_SLEEP_MS=20000')!'go'")
        try:
            # Wait for the run to start, then find and delete the pod that runs it.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not await _subject_frames(nats_local_port, topic):
                await asyncio.sleep(1)
            busy = [
                pod
                for pod in _kubectl("get", "pods", "-o", "name").split()
                if "runner" in pod and _slots_busy(pod) > 0
            ]
            assert busy, "no runner pod is running the run"
            _kubectl("delete", busy[0], "--wait=false")
        finally:
            await ws.close()  # type: ignore[attr-defined]
    frames = await _until_terminal(nats_local_port, topic, timeout=240)
    terminals = _terminals(frames)
    assert len(terminals) == 1, terminals
    assert_gapfree(frames)
    _rollout(_RUNNER_DEPLOYMENT)


def _slots_busy(pod: str) -> float:
    script = (
        "import urllib.request;"
        "t=urllib.request.urlopen('http://127.0.0.1:9109/metrics').read().decode();"
        "print([l.split()[-1] for l in t.splitlines()"
        " if l.startswith('screamingface_engine_worker_slots_busy ')][0])"
    )
    return float(_kubectl("exec", pod.removeprefix("pod/"), "--", "python", "-c", script).strip())


# --------------------------------------------------------------------------------------------
# K8 — a run past its memory budget dies alone; its siblings finish.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k8_a_run_past_its_memory_budget_is_oom_killed_without_taking_its_siblings(
    app_base_url: str, nats_local_port: int
) -> None:
    budget = 1536 * 1024 * 1024
    _kubectl(
        "set",
        "env",
        f"deployment/{_RUNNER_DEPLOYMENT}",
        f"URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES={budget}",
    )
    _rollout(_RUNNER_DEPLOYMENT)
    try:
        async with httpx.AsyncClient(base_url=app_base_url, timeout=120.0) as client:
            hog = asyncio.ensure_future(
                client.get(
                    MODEL_MOUNT,
                    params={"q": f"('STUB_BYTES={600 * 1024 * 1024}')!'go'"},
                    headers={**IDENTITY, "Prefer": "wait=30"},
                )
            )
            siblings = await asyncio.gather(
                *(
                    client.get(MODEL_MOUNT, params={"q": "('hi')!'go'"}, headers=IDENTITY)
                    for _ in range(3)
                )
            )
            hogged = await hog
        assert all(s.status_code == 200 for s in siblings), [s.text for s in siblings]
        assert hogged.status_code >= 500, hogged.status_code  # the hog failed, alone
        frames = await _until_terminal(nats_local_port, hogged.headers["x-url4-run"], 60)
        (terminal,) = _terminals(frames)
        assert terminal["data"]["status"] in ("failed", "stopped"), terminal
    finally:
        _kubectl(
            "set",
            "env",
            f"deployment/{_RUNNER_DEPLOYMENT}",
            "URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES-",
        )
        _rollout(_RUNNER_DEPLOYMENT)


# --------------------------------------------------------------------------------------------
# K9 — rollout restart of the runner pool during runs -> every run ends with one terminal.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k9_a_runner_rollout_restart_drains_and_kills_idle_warm_children_first(
    app_base_url: str, nats_local_port: int
) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        started = [await _start_async(client, "('STUB_SLEEP_MS=3000')!'go'") for _ in range(4)]
        _kubectl("rollout", "restart", f"deployment/{_RUNNER_DEPLOYMENT}")
        for _, ws in started:
            await ws.close()  # type: ignore[attr-defined]
    _rollout(_RUNNER_DEPLOYMENT)
    for topic, _ in started:
        frames = await _until_terminal(nats_local_port, topic, timeout=240)
        terminals = _terminals(frames)
        assert len(terminals) == 1, (topic, terminals)
        assert terminals[0]["data"]["status"] in ("succeeded", "stopped"), terminals
        assert_gapfree(frames)


# --------------------------------------------------------------------------------------------
# K10 — restart the NATS pod during a run -> gap-free frames, or failed/stream_failed.
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k10_restarting_the_nats_pod_mid_run_stays_gapfree_or_fails_named(
    app_base_url: str,
) -> None:
    async with httpx.AsyncClient(base_url=app_base_url, timeout=60.0) as client:
        topic, ws = await _start_async(client, "('STUB_SLEEP_MS=8000')!'go'")
        await asyncio.sleep(2)
        _kubectl("delete", "pod", _NATS_POD, "--wait=false")
        await ws.close()  # type: ignore[attr-defined]
    _kubectl("wait", "--for=condition=Ready", f"pod/{_NATS_POD}", "--timeout=180s", timeout=200)
    _rollout(_APP_DEPLOYMENT)
    # A FRESH port-forward: the fixture's one pointed at the pod that was deleted.
    with port_forward("sf-uniform-nats", 4222) as nats_port:
        frames = await _until_terminal(nats_port, topic, timeout=240)
    terminals = _terminals(frames)
    if terminals:
        assert len(terminals) == 1, terminals
        status = terminals[0]["data"]["status"]
        if status != "succeeded":
            assert status in ("failed", "stopped"), terminals
    # Whatever survived the restart must not hide a gap.
    sequences = [int(f["sequence"]) for f in frames if "sequence" in f]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    if sequences:
        assert sequences == list(range(sequences[0], sequences[0] + len(sequences))), sequences


# --------------------------------------------------------------------------------------------
# K11 — a legacy per-run stream blocks startup until `admin purge-legacy-streams` ran.
# --------------------------------------------------------------------------------------------
async def _seed_legacy_stream(nats_port: int, legacy: str) -> None:
    """What the pre-PRD-01 chart leaves behind: a per-run stream, and no `url4-events`."""
    from nats.aio.client import Client as NatsClient

    nc = NatsClient()
    await nc.connect(f"nats://127.0.0.1:{nats_port}")
    try:
        js = nc.jetstream()
        await js.delete_stream("url4-events")
        await js.add_stream(name=legacy, subjects=[f"url4-cloud.{legacy.split('_', 1)[1]}"])
    finally:
        await nc.close()


async def _app_log_names(needle: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    logs = ""
    while time.monotonic() < deadline and needle not in logs:
        await asyncio.sleep(5)
        logs = subprocess.run(
            [
                "kubectl",
                "--context",
                KIND_CONTEXT,
                "-n",
                NAMESPACE,
                "logs",
                f"deployment/{_APP_DEPLOYMENT}",
                "--tail=200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    return logs


def _run_purge_command() -> None:
    """The rollout step, with the NEW image (the command ships only there)."""
    image = _kubectl(
        "get",
        f"deployment/{_APP_DEPLOYMENT}",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    )
    _kubectl(
        "run",
        "k11-purge",
        "--rm",
        "-i",
        "--restart=Never",
        f"--image={image}",
        "--image-pull-policy=Never",
        "--env=URL4_CLOUD_NATS_URL=nats://sf-uniform-nats:4222",
        "--command",
        "--",
        "screamingface-engine",
        "admin",
        "purge-legacy-streams",
        timeout=180,
    )


@pytest.mark.asyncio
async def test_k11_purge_legacy_streams_after_a_drained_upgrade_from_the_old_chart(
    nats_local_port: int,
) -> None:
    """The drained-rollout order (implementation-notes D7): with a legacy `url4-cloud_<topic>`
    stream on the broker (seeded here as the old chart left one), the new App refuses to start
    naming the command; the command deletes it; the App starts."""
    _kubectl("scale", f"deployment/{_RUNNER_DEPLOYMENT}", "--replicas=0")
    _kubectl("scale", f"deployment/{_APP_DEPLOYMENT}", "--replicas=0")
    _kubectl(
        "wait",
        "--for=delete",
        "pod",
        "-l",
        "app.kubernetes.io/component=runner",
        "--timeout=120s",
        timeout=140,
    )
    await _seed_legacy_stream(nats_local_port, "url4-cloud_k11-legacy")
    try:
        _kubectl("scale", f"deployment/{_APP_DEPLOYMENT}", "--replicas=1")
        logs = await _app_log_names("purge-legacy-streams", timeout=120)
        assert "purge-legacy-streams" in logs, logs[-2000:]
        _run_purge_command()
    finally:
        _kubectl("scale", f"deployment/{_APP_DEPLOYMENT}", "--replicas=1")
        _kubectl("scale", f"deployment/{_RUNNER_DEPLOYMENT}", "--replicas=2")
    _kubectl("rollout", "restart", f"deployment/{_APP_DEPLOYMENT}")
    _rollout(_APP_DEPLOYMENT)
    _rollout(_RUNNER_DEPLOYMENT)
