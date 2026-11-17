"""The hosted run delivers the Candidate Result's exact bytes, inline or spilled.

FEATURE: memory fix 3 (OME-1835), unit 1 (streamed delivery), proved on the real hosted run
path. The run goes ``build_executor`` -> url4 ``lifecycle.run`` with the SDK-shaped link
expression, against a stub gateway.

INVARIANT: the delivered result bytes equal ``compact_json(CandidateResult.as_payload())``.
Inline, the bytes ride the result frame as ``body``. Spilled through the run spool, the
complete bytes are written to the artifact store under their sha256, the frame carries only
the ``artifact`` ticket, and the ticket's bytes equal the same text. The run body is never a
spool reference: the reference is redeemed into the ticket, never published as text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_case_result_memory import _CANDIDATE, _MODEL, _reply, _write_bundle  # noqa: E402

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore  # noqa: E402
from screamingface_engine.benchmarks import link_candidate, result_body  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine.benchmarks.grading_endpoints import compact_json  # noqa: E402
from screamingface_engine.runner.main import build_executor  # noqa: E402
from screamingface_engine.subjects import RUN_ROOT_NODE  # noqa: E402
from screamingface_engine.world.config import (  # noqa: E402
    AigatewaySection,
    ModelSpec,
    WorldConfig,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4.streaming.interfaces.stream import EventPublisher  # noqa: E402
from url4.streaming.lifecycle import run  # noqa: E402
from url4.streaming.protocol import OutboundFrame, ResultEvent, TerminatedEvent  # noqa: E402


class _Frames(EventPublisher):
    """Keeps every frame, so the test reads the result and the terminal event."""

    def __init__(self) -> None:
        self.events: list[OutboundFrame] = []

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None


class _Gateway:
    """Answers every chat call with a short reply; counts the calls."""

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls += 1
        message = {"role": "assistant", "content": _reply(json.dumps(body["messages"])[-200:])}
        return httpx.Response(
            200,
            json={
                "id": f"x{self.calls}",
                "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 600, "completion_tokens": 350},
            },
        )


class _BrokenSink:
    """A sink whose disk is full: the first write fails."""

    def write(self, chunk: bytes) -> None:
        raise OSError("disk full")

    def commit(self) -> Any:
        raise AssertionError("commit must not run after a failed write")

    def abort(self) -> None:
        return None


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records the expected text of each result body the aggregate hands to the spool.

    WHY at write_result_body: deliver_result calls result_body.write_result_body at call time
    for every ResultBody, held or parked, so the capture does not depend on how the aggregate
    holds its Cases. For a held body the expected text is also checked against
    compact_json(as_payload()), the bytes before memory fix 3.
    """

    seen: list[str] = []
    original = result_body.write_result_body

    def _recording(body: result_body.ResultBody, write: Any) -> None:
        # WHY the original: encode_result_body calls the module's write_result_body,
        # which is this wrapper while the patch is on.
        pieces: list[str] = []
        original(body, pieces.append)
        expected = "".join(pieces)
        if isinstance(body, result_body.HeldResultBody):
            assert expected == compact_json(body.result.as_payload())
        seen.append(expected)
        original(body, write)

    monkeypatch.setattr(result_body, "write_result_body", _recording)
    return seen


async def _run_frames(tmp_path: Path, cases: int, env_extra: dict[str, str]) -> list[OutboundFrame]:
    """Run N Cases through the hosted path; return every frame the run published."""

    _write_bundle(tmp_path, cases)
    gateway = _Gateway()
    url4 = link_candidate(_CANDIDATE, imported_benchmark("mmlu_pro").benchmark.build(cases))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.respond), base_url="http://aigateway.test"
    )
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test", default_model=_MODEL, models=(ModelSpec(id=_MODEL),)
        )
    )
    env = {
        "URL4_CLOUD_TOPIC": "streamed-hosted",
        "URL4_CLOUD_ARTIFACTS_DIR": str(tmp_path / "art"),
        **env_extra,
    }
    executor = build_executor(
        env,
        config,
        client=client,
        benchmarks=BUILTIN_BENCHMARKS,
        benchmark_assets_root=tmp_path,
    )
    frames = _Frames()
    try:
        await run(frames, executor, "streamed-hosted", url4, node=RUN_ROOT_NODE)
    finally:
        await client.aclose()
    return frames.events


async def _run(
    tmp_path: Path, cases: int, env_extra: dict[str, str]
) -> tuple[ResultEvent, TerminatedEvent]:
    """Run N Cases through the hosted path; return the single result and terminal events."""

    events = await _run_frames(tmp_path, cases, env_extra)
    results = [event for event in events if isinstance(event, ResultEvent)]
    terminals = [event for event in events if isinstance(event, TerminatedEvent)]
    assert len(results) == 1, "the run must publish exactly one result"
    assert len(terminals) == 1, "the run must publish exactly one terminal event"
    return results[0], terminals[0]


@pytest.mark.asyncio
async def test_a_small_result_rides_inline_byte_identical(
    tmp_path: Path, capture: list[str]
) -> None:
    result, terminated = await _run(tmp_path, 5, {})

    assert terminated.data.status == "succeeded"
    assert len(capture) == 1
    assert result.data.artifact is None
    assert result.data.body == capture[0]


@pytest.mark.asyncio
async def test_a_spilled_result_redeems_to_byte_identical_bytes(
    tmp_path: Path, capture: list[str]
) -> None:
    result, terminated = await _run(tmp_path, 5, {"URL4_CLOUD_RESULT_INLINE_CAP_BYTES": "1024"})

    assert terminated.data.status == "succeeded"
    assert len(capture) == 1
    artifact = result.data.artifact
    assert artifact is not None
    data = (tmp_path / "art" / artifact.id).read_bytes()
    expected = capture[0].encode("utf-8")
    assert data == expected
    assert artifact.size_bytes == len(data)
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()
    names = [path.name for path in (tmp_path / "art").iterdir()]
    assert not any(name.endswith(".tmp") for name in names)


@pytest.mark.asyncio
async def test_the_run_body_is_never_a_spool_reference(tmp_path: Path, capture: list[str]) -> None:
    result, terminated = await _run(tmp_path, 5, {"URL4_CLOUD_RESULT_INLINE_CAP_BYTES": "1024"})

    assert terminated.data.status == "succeeded"
    assert result.data.body is None


@pytest.mark.asyncio
async def test_a_sink_failure_ends_the_run_with_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FilesystemArtifactStore, "open_sink", lambda self: _BrokenSink())
    frames = await _run_frames(tmp_path, 5, {"URL4_CLOUD_RESULT_INLINE_CAP_BYTES": "1024"})
    terminals = [event for event in frames if isinstance(event, TerminatedEvent)]
    assert len(terminals) == 1
    assert not [event for event in frames if isinstance(event, ResultEvent)]
    assert terminals[0].data.status == "failed"
    error = terminals[0].data.error
    assert error is not None
    assert error.code != "benchmark_unavailable"
    # Pinned (plan Unit 1 step 7): a store or disk failure ends the run as internal_error,
    # never benchmark_unavailable.
    assert error.code == "internal_error"
