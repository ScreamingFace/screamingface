"""A lone surrogate in one answer fails that Case, and the run still delivers the exact body.

FEATURE: memory fix 3 (OME-1835), unit 1, plan edge case "a lone surrogate in an answer".
The plan expected the surrogate to reach the result and fail the run in ``build_result``
(``.encode("utf-8")``). It does not, on this branch or on main: the surrogate stops one step
earlier. ``CaseResultStore.append`` (memory fix 2, unchanged by unit 1) encodes each Case row
to UTF-8 and raises ``UnicodeEncodeError``. The graded-answer route turns that into a
Case-level failure (``missing_case_row``, source ``UnicodeEncodeError``), so the run succeeds
and the surrogate never reaches the aggregate. Measured with the spool unbound (the old
path), the run also succeeds with the same Case failure.

What this pins, because the run succeeds: the streamed body (inline, and spilled to an
artifact) still equals ``compact_json(as_payload())`` of the CandidateResult the aggregate
handed to the spool, and that Case is a failed Case with that source error. If a later change
lets the surrogate reach the result, the spool's writer fails on it (as ``build_result`` did),
the outcome is no longer ``succeeded``, and this test fails and must be looked at again.

How the reply is built: ``json.dumps`` escapes the surrogate as ``\\ud800`` in ASCII JSON
(httpx's ``json=`` would fail to encode it), and the client decodes it back to a lone
surrogate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_case_result_memory import _CANDIDATE, _MODEL, _reply, _write_bundle  # noqa: E402

from screamingface_engine.benchmarks import link_candidate  # noqa: E402
from screamingface_engine.benchmarks import result_body as result_body_module  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine.benchmarks.contract import CandidateResult  # noqa: E402
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
from url4.streaming.protocol import OutboundFrame  # noqa: E402

_CASES = 3
_SURROGATE_CALL = 2
_SURROGATE_ANSWER = "ANSWER: A \ud800"


class _Recorder(EventPublisher):
    """Keeps every frame, so the test reads the terminal result and status."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)

    async def flush(self) -> None:
        return None

    def data_of(self, kind: str) -> Any:
        """The ``data`` of the last frame of type ``ai.url4.<kind>``."""

        matches = [f for f in self.frames if getattr(f, "type", "") == f"ai.url4.{kind}"]
        assert matches, f"no {kind} frame was published"
        return getattr(matches[-1], "data")


class _SurrogateGateway:
    """Answers every call; call ``_SURROGATE_CALL`` answers with a lone surrogate."""

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls += 1
        content = _reply(json.dumps(body["messages"])[-200:])
        if self.calls == _SURROGATE_CALL:
            content = _SURROGATE_ANSWER
        payload = {
            "id": f"x{self.calls}",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 600, "completion_tokens": 350},
        }
        # WHY bytes and not json=: json.dumps escapes the surrogate to ASCII; httpx's json=
        # would encode it to UTF-8 and fail before the engine ever saw the reply.
        return httpx.Response(
            200,
            content=json.dumps(payload).encode("ascii"),
            headers={"content-type": "application/json"},
        )


async def _run_hosted(tmp_path: Path, inline_cap: int | None) -> tuple[_Recorder, int]:
    """Run ``_CASES`` Cases on the hosted path; return the frames and the call count."""

    _write_bundle(tmp_path, _CASES)
    gateway = _SurrogateGateway()
    url4 = link_candidate(_CANDIDATE, imported_benchmark("mmlu_pro").benchmark.build(_CASES))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.respond), base_url="http://aigateway.test"
    )
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test", default_model=_MODEL, models=(ModelSpec(id=_MODEL),)
        )
    )
    env = {"URL4_CLOUD_TOPIC": "surrogate", "URL4_CLOUD_ARTIFACTS_DIR": str(tmp_path / "art")}
    if inline_cap is not None:
        env["URL4_CLOUD_RESULT_INLINE_CAP_BYTES"] = str(inline_cap)
    executor = build_executor(
        env, config, client=client, benchmarks=BUILTIN_BENCHMARKS, benchmark_assets_root=tmp_path
    )
    recorder = _Recorder()
    try:
        await run(recorder, executor, "surrogate", url4, node=RUN_ROOT_NODE)
    finally:
        await client.aclose()
    return recorder, gateway.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("inline_cap", [None, 1024], ids=["inline", "spilled"])
async def test_a_lone_surrogate_fails_its_case_and_the_body_stays_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline_cap: int | None
) -> None:
    captured: list[CandidateResult] = []
    held = result_body_module.HeldResultBody

    def capturing_body(result: CandidateResult) -> Any:
        captured.append(result)
        return held(result)

    # WHY the module attribute: deliver_result imports HeldResultBody at call time.
    monkeypatch.setattr(result_body_module, "HeldResultBody", capturing_body)

    recorder, calls = await _run_hosted(tmp_path, inline_cap)

    assert calls == _CASES
    assert recorder.data_of("terminated").status == "succeeded"
    assert len(captured) == 1, "the aggregate must hand exactly one result to the spool"
    expected = compact_json(captured[0].as_payload())
    result = recorder.data_of("result")
    if inline_cap is None:
        assert result.artifact is None
        delivered = result.body
    else:
        assert result.artifact is not None, "a 1 KiB inline cap must spill the result"
        delivered = (tmp_path / "art" / result.artifact.id).read_bytes().decode("utf-8")
    assert delivered == expected
    assert "\ud800" not in delivered

    case = json.loads(delivered)["cases"][_SURROGATE_CALL - 1]
    assert case["status"] == "failed"
    assert case["output"] is None
    source = case["failures"][0]["metadata"]["source_error"]
    assert source["kind"] == "UnicodeEncodeError"
