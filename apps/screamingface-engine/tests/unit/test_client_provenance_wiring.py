"""Admission and both real Engine substrates carry provenance without shared state."""

import asyncio

import pytest
from _fakes import FixedGate
from test_client_provenance import _FailingExecutor, _frames
from test_inprocess_runner import _runner as local_runner
from test_queue_runner_status import _FakeClock, _FakePublisher
from test_queue_runner_status import _FakeQueue as SubmissionQueue
from test_queue_runner_status import _runner as queue_runner
from test_rest import SECRET, T0, WINDOW_S, _cap, _client, _make_app
from test_worker_claim import _FakeMsg, _FakeQueue, _worker
from test_worker_claim import _FakePublisher as WorkerPublisher

from screamingface_engine.app import create_app
from screamingface_engine.client_provenance import CLIENT_VERSION_ENV, VERSION_ATTRIBUTE
from screamingface_engine.config import Settings
from screamingface_engine.runner.main import _run_and_log, params_from_env
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import LogEvent


def _versions(frames: list) -> list:
    return [
        e.data.attributes[VERSION_ATTRIBUTE]
        for e in frames
        if isinstance(e, LogEvent) and VERSION_ATTRIBUTE in e.data.attributes
    ]


@pytest.mark.asyncio
async def test_local_requests_capture_versions_per_run_and_ignore_ambient_values() -> None:
    stream = InMemoryEventStream()
    runner, _ = local_runner(stream, base_env={CLIENT_VERSION_ENV: "ambient"})
    app = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=stream,
        job_runner=runner,
        interest=FixedGate(True),
        clock=lambda: T0,
    )
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.get(
                "/",
                params={"q": "'hi'"},
                headers={
                    **_cap("first"),
                    "Prefer": "respond-async",
                    "User-Agent": "screamingface/1.2.3",
                },
            ),
            client.get(
                "/",
                params={"q": "'hi'"},
                headers={**_cap("second"), "Prefer": "respond-async", "User-Agent": "old-client/1"},
            ),
        )
    assert first.status_code == second.status_code == 202
    assert _versions(await _frames(stream, "first")) == ["1.2.3"]
    assert _versions(await _frames(stream, "second")) == []
    await runner.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("present, expected", [(False, 428), (True, 409)])
async def test_rejected_admission_does_not_publish_version(present: bool, expected: int) -> None:
    from _fakes import RecordingJobRunner

    stream = InMemoryEventStream()
    runner = RecordingJobRunner(exists=True)
    app = _make_app(stream=stream, job_runner=runner, gate_present=present)
    async with _client(app) as client:
        response = await client.get(
            "/", params={"q": "'hi'"}, headers={**_cap("rejected"), "User-Agent": "screamingface/1"}
        )
    assert response.status_code == expected
    assert runner.scheduled == []


@pytest.mark.asyncio
async def test_queue_submission_carries_version_into_worker_execution() -> None:
    runner = queue_runner(_FakeClock(), _FakePublisher())
    await runner.schedule("queued", "'hi'", 60, client_version="0.0.0+source")
    assert isinstance(runner._queue, SubmissionQueue)
    message = runner._queue.published[0]
    env = decode_message(message)
    assert env[CLIENT_VERSION_ENV] == "0.0.0+source"
    params = params_from_env(env)
    stream = InMemoryEventStream()
    await _run_and_log(OperationCapturingExecutor(_FailingExecutor()), stream, params, None)
    assert _versions(await _frames(stream, "queued")) == ["0.0.0+source"]


@pytest.mark.parametrize("version", [None, "1.2.3"])
def test_worker_cannot_inherit_an_unrelated_client_version(
    monkeypatch: pytest.MonkeyPatch, version: str | None
) -> None:
    monkeypatch.setenv(CLIENT_VERSION_ENV, "ambient")
    message = _FakeMsg(encode_message("queued", "'hi'", 60, client_version=version))
    worker = _worker(_FakeQueue(), WorkerPublisher())
    env = worker._supervisor._child_env(message)
    assert env.get(CLIENT_VERSION_ENV) == version
