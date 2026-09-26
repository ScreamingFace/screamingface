"""Mount calls as direct runs, App side (uniform executor PRD 04, contracts.md C2).

The App under test is the real `create_app` with the mounts registered from a fixed table. The
runner is scripted: it "executes" each queued direct run by publishing the frames a worker's
child would, so every answer is driven from a real terminal frame on the stream.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import MOUNT_TAG, register_mounts
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.serving import MountDescriptor, MountTable
from url4.streaming.protocol import (
    ErrorInfo,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for
from url4.streaming.protocol.signals import ResultArtifact

pytestmark = pytest.mark.asyncio

EMAIL = {"X-User-Email": "caller@example.com"}
TABLE = MountTable(
    mounts=(
        MountDescriptor("/v1/chat/completions", "endpoint", None),
        MountDescriptor("/v1/benchmarks/data/foo", "data", "application/json"),
    ),
    config_digest="abc",
)
Script = Callable[[str, str], list[Any]]


def _result(topic: str, body: str | None = None, **kwargs: Any) -> ResultEvent:
    return ResultEvent(
        id=f"res-{topic}",
        source=source_for(topic),
        subject=topic,
        data=ResultData(body=body, **kwargs),
    )


def _terminated(topic: str, status: str = "succeeded", **error: Any) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(
            status=status,  # type: ignore[arg-type]
            error=ErrorInfo(**error) if error else None,
        ),
    )


def _ok(body: str, media_type: str | None = None) -> Script:
    return lambda topic, target: [_result(topic, body, media_type=media_type), _terminated(topic)]


class _Runner:
    """Records what the App queued and plays `script` onto the stream for each direct run."""

    def __init__(self, stream: InMemoryEventStream, script: Script | None, **flags: Any) -> None:
        self._stream, self._script, self._flags = stream, script, flags
        self.scheduled: list[dict[str, Any]] = []
        self.stopped: list[str] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        if self._flags.get("full"):
            from url4.streaming.interfaces import JobRunnerAtCapacity

            raise JobRunnerAtCapacity(4, 4, retry_after_s=42)
        self.scheduled.append({"topic": topic, "target": url4, "deadline_s": deadline_s, **kwargs})
        if self._script is not None:
            for frame in self._script(topic, url4):
                await self._stream.publish(topic, frame)
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


def _app(
    script: Script | None = None,
    *,
    signing_key: str = "",
    sync_max_wait_s: float = 5.0,
    **flags: Any,
) -> tuple[Any, _Runner]:
    stream = InMemoryEventStream()
    runner = _Runner(stream, script, **flags)
    settings = Settings(
        jwt_secret="mount-secret",
        sync_max_wait_s=sync_max_wait_s,
        artifact_signing_key=signing_key,
    )
    app = create_app(settings, stream=stream, job_runner=runner)  # type: ignore[arg-type]
    register_mounts(app, TABLE)
    return app, runner


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _error(resp: httpx.Response) -> dict[str, Any]:
    return resp.json()["error"]


async def test_mount_call_publishes_direct_run_and_returns_200() -> None:
    """MNT-10 / MC-H2: one direct run on the queue; the handler's body and media type back."""
    app, runner = _app(_ok('{"answer": 42}', "application/json"))
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=('hi')!'answer'", headers=EMAIL)
    assert resp.status_code == 200
    assert resp.json() == {"answer": 42}
    (run,) = runner.scheduled
    assert run["shape"] == "direct"
    assert run["target"] == "/v1/chat/completions?q=('hi')!'answer'"
    assert run["deadline_s"] == 10  # sync_max_wait_s + 5: never outlives its caller


async def test_a_data_route_without_q_is_served() -> None:
    """MC-D14."""
    app, runner = _app(_ok('{"rows": 1}', "application/json"))
    async with _client(app) as client:
        resp = await client.get("/v1/benchmarks/data/foo", headers=EMAIL)
    assert resp.status_code == 200 and resp.json() == {"rows": 1}
    assert runner.scheduled[0]["target"] == "/v1/benchmarks/data/foo"


async def test_missing_identity_403_nothing_queued() -> None:
    """MNT-12 / MC-D2."""
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b")
    assert resp.status_code == 403
    assert _error(resp)["code"] == "identity_access_denied"
    assert runner.scheduled == []


async def test_only_verified_identity_reaches_message() -> None:
    """MNT-13 / MC-D3: the identity comes from the verified header reader alone; no other
    inbound header (Cookie, Authorization, URL4-Capability) reaches the run."""
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        await client.get(
            "/v1/chat/completions?q=(a)!b",
            headers={
                **EMAIL,
                "Cookie": "s=1",
                "Authorization": "Bearer t",
                "URL4-Capability": "tok",
            },
        )
    (run,) = runner.scheduled
    assert run["identity"] == job_env.identity_from_headers(httpx.Headers(EMAIL))
    flat = json.dumps(run, default=str)
    assert "Bearer" not in flat and "s=1" not in flat and "tok" not in flat


async def test_endpoint_without_q_is_400_missing_intent() -> None:
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions", headers=EMAIL)
    assert resp.status_code == 400 and _error(resp)["code"] == "missing_intent"
    assert runner.scheduled == []


async def test_invalid_answer_seed_400() -> None:
    """MNT-21 / MC-D10."""
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get(
            "/v1/chat/completions?q=(a)!b", headers={**EMAIL, "X-Answer-Seed": "not-a-seed"}
        )
    assert resp.status_code == 400 and _error(resp)["code"] == "malformed_header"
    assert runner.scheduled == []


async def test_target_over_8kib_414() -> None:
    """MNT-22 / MC-D11."""
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get(f"/v1/chat/completions?q=({'x' * 9000})!b", headers=EMAIL)
    assert resp.status_code == 414
    assert runner.scheduled == []


async def test_admission_503_for_mount_calls() -> None:
    """MNT-23 / MC-D5."""
    app, _ = _app(_ok("x"), full=True)
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "42"
    assert _error(resp)["code"] == "overloaded"


async def test_bound_elapsed_returns_504_and_stops_run() -> None:
    """MNT-11 / MC-E1 (ans:Q9): the run is stopped BEFORE the answer."""
    app, runner = _app(None, sync_max_wait_s=0.1)
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 504 and _error(resp)["code"] == "timeout"
    assert runner.stopped == [runner.scheduled[0]["topic"]]


@pytest.mark.parametrize(
    ("code", "permanent", "status"),
    [
        ("malformed_source", True, 400),
        ("missing_intent", True, 400),
        ("endpoint_not_found", True, 404),
        ("direct_eval_refused", True, 404),
        ("identity_access_denied", True, 403),
        ("result_too_large", True, 413),
        ("aigateway_transport_error", False, 502),
        ("artifact_spill_failed", True, 502),
        ("timeout", False, 504),
        # Node-tier parity (`send._remap`): a permanent ENGINE/provider code is a 502.
        ("aigateway_http_401", True, 502),
        ("provider_refused", True, 502),
    ],
)
async def test_mount_status_mapping_matches_node_tier_table(
    code: str, permanent: bool, status: int
) -> None:
    """MNT-9 / MC-D6: the MNT-C2 table (node-tier statuses) — same status, same `code`."""

    def script(topic: str, target: str) -> list[Any]:
        return [_terminated(topic, "failed", code=code, message="m", permanent=permanent)]

    app, _ = _app(script)
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == status
    assert _error(resp)["code"] == code


async def test_a_run_that_timed_out_is_504() -> None:
    app, _ = _app(lambda topic, _t: [_terminated(topic, "timed_out", code="deadline", message="m")])
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 504


def _artifact(size: int) -> ResultArtifact:
    return ResultArtifact(id="a" * 64, size_bytes=size, sha256="a" * 64)


async def test_result_over_1mib_returns_signed_303() -> None:
    """MNT-15 / MC-H4 (the redeem half is in the integration suite)."""
    big = _artifact(1536 * 1024)

    def script(topic: str, target: str) -> list[Any]:
        return [_result(topic, artifact=big, media_type=None), _terminated(topic)]

    app, _ = _app(script, signing_key="k" * 32)
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith(f"/artifacts/{big.id}?exp=") and "&sig=" in location


async def test_no_signing_key_streams_artifact_200() -> None:
    """MNT-17 / MC-D9: without a key a 303 would be unredeemable; the body is served, and the
    unsigned-spill counter rises."""
    big = _artifact(1536 * 1024)
    app, _ = _app(lambda topic, _t: [_result(topic, artifact=big), _terminated(topic)])
    body = b"y" * big.size_bytes
    app.state.artifact_store.content = lambda artifact_id: _stream(body)  # type: ignore[method-assign]
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
        metrics = (await client.get("/metrics")).text
    assert resp.status_code == 200 and len(resp.content) == len(body)
    assert "screamingface_engine_mount_unsigned_spill_total 1.0" in metrics


async def test_openapi_lists_every_mount_with_params_and_responses() -> None:
    """MNT-18 / MC-H1."""
    app, _ = _app(_ok("x"))
    async with _client(app) as client:
        schema = (await client.get("/openapi.json")).json()
    for mount in TABLE.mounts:
        operation = schema["paths"][mount.path]["get"]
        assert operation["tags"] == [MOUNT_TAG]
        assert "q" in [p["name"] for p in operation["parameters"] if p["in"] == "query"]
        assert set(operation["responses"]) >= {
            "200",
            "303",
            "400",
            "403",
            "404",
            "502",
            "503",
            "504",
        }


async def test_openapi_never_cached_without_mounts() -> None:
    """MNT-19 / MC-D8: a schema generated before the mounts must not survive their
    registration."""
    stream = InMemoryEventStream()
    runner: Any = _Runner(stream, None)
    app = create_app(Settings(jwt_secret="mount-secret"), stream=stream, job_runner=runner)
    async with _client(app) as client:
        before = (await client.get("/openapi.json")).json()
        assert "/v1/chat/completions" not in before["paths"]
        register_mounts(app, TABLE)
        after = (await client.get("/openapi.json")).json()
    assert "/v1/chat/completions" in after["paths"]


async def test_eval_path_is_404_in_production() -> None:
    """MNT-20 / MC-E2: no route for the eval path; nothing is queued."""
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get("/v1?q=(gpt)!'hi'", headers=EMAIL)
    assert resp.status_code == 404
    assert runner.scheduled == []


async def test_mount_calls_are_counted_by_path_and_status() -> None:
    app, _ = _app(_ok("x"))
    async with _client(app) as client:
        await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
        await client.get("/v1/chat/completions?q=(a)!b")
        metrics = (await client.get("/metrics")).text
    assert (
        'screamingface_engine_mount_calls_total{path="/v1/chat/completions",status="200"} 1.0'
        in metrics
    )
    assert (
        'screamingface_engine_mount_calls_total{path="/v1/chat/completions",status="403"} 1.0'
        in metrics
    )


async def test_disconnect_stops_mount_run_within_1s() -> None:
    """MNT-14 / MC-D4: nobody can attach to a mount run, so a caller that leaves stops it."""
    app, runner = _app(None, sync_max_wait_s=30.0)
    disconnect = asyncio.Event()
    first = [True]

    async def receive() -> dict[str, Any]:
        if first[0]:
            first[0] = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        pass

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"q=(a)!b",
        "root_path": "",
        "headers": [(b"host", b"test"), (b"x-user-email", b"caller@example.com")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    call = asyncio.ensure_future(app(scope, receive, send))  # type: ignore[arg-type]
    for _ in range(100):
        if runner.scheduled:
            break
        await asyncio.sleep(0.01)
    disconnect.set()
    await asyncio.wait_for(call, timeout=1.0)
    assert runner.stopped == [runner.scheduled[0]["topic"]]


async def test_result_700kib_returns_inline_200(tmp_path: Any) -> None:
    """MNT-16 / MC-H5: a result over the 512 KiB FRAME cap is spilled by the child, but it is
    under the 1 MiB mount limit, so the App serves it inline — 200, not 303 (ans:Q10)."""
    body = "x" * (700 * 1024)
    path = tmp_path / "result"
    path.write_text(body)
    medium = _artifact(len(body))
    app, _ = _app(
        lambda topic, _t: [_result(topic, artifact=medium), _terminated(topic)],
        signing_key="k" * 32,
    )
    from screamingface_engine.artifacts.ports import LocalFile

    app.state.artifact_store.content = lambda artifact_id: LocalFile(path=path)  # type: ignore[method-assign]
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 200
    assert len(resp.content) == len(body)


def _stream(body: bytes) -> Any:
    from screamingface_engine.artifacts.ports import RemoteStream

    async def _chunks():  # type: ignore[no-untyped-def]
        yield body

    return RemoteStream(stream=_chunks(), size_bytes=len(body))


async def test_a_success_without_its_result_frame_is_502_not_an_empty_200() -> None:
    """Review C3: a reclaimed Result frame must not read as an empty success."""
    app, _ = _app(lambda topic, _t: [_terminated(topic)])
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert resp.status_code == 502 and _error(resp)["code"] == "result_unavailable"


async def test_a_mount_path_that_cannot_be_a_route_fails_registration() -> None:
    """Review C9: an exact-target data key or a `{` path is refused at startup."""
    stream = InMemoryEventStream()
    runner: Any = _Runner(stream, None)
    app = create_app(Settings(jwt_secret="mount-secret"), stream=stream, job_runner=runner)
    for bad in ("/rows?limit=5", "/a/{b}"):
        with pytest.raises(ValueError, match="cannot be served"):
            register_mounts(app, MountTable((MountDescriptor(bad, "data", None),), None))


async def test_a_mount_call_arms_no_orphan_reaper() -> None:
    """Review C11: nobody attaches to a mount run, and the handler stops it itself — so a call
    leaves nothing for the reaper to watch."""
    app, _ = _app(_ok("x"))
    async with _client(app) as client:
        await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)
    assert app.state.reaper is None or not app.state.reaper._deadlines  # noqa: SLF001
