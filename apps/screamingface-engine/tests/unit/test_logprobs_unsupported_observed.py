"""The author sees `logprobs_unsupported` in the quorum record and the activity view (E4b part 3).

Pins LC#11 (a): in a quorum panel the refused member is `fail/missing` in the evidence and the
connector reports `logprobs_unsupported` through `observation.failed(code)`; and (b): the activity
stream of the single call shows the code. A separate module (append-only gate).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from logprobs_support import ANSWERS, REFUSAL, evaluate_panel, panel_candidate, recorded
from test_model_activity_stream import activities, publish

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.world import connector


@pytest.fixture
def failed_codes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every `observation.failed(code)` of the connector, as (model id, code)."""
    codes: list[tuple[str, str]] = []

    class _SpyCall:
        def __init__(self, model_id: str, emit: object) -> None:
            self._model_id = model_id

        async def __aenter__(self) -> _SpyCall:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def completed(self, finish_reason: str | None) -> None:
            return None

        def failed(self, code: str) -> None:
            codes.append((self._model_id, code))

        def retry(self, *, attempt: int, delay_seconds: float) -> None:
            return None

    monkeypatch.setattr(connector, "ModelCall", _SpyCall)
    return codes


@pytest.mark.asyncio
async def test_quorum_panel_member_refused_for_logprobs_is_missing_and_observed(
    failed_codes: list[tuple[str, str]],
) -> None:
    """LC#11 (a): the optional refused member is missing; the author sees the code."""
    encoded = await evaluate_panel(
        panel_candidate(quorum=2, optional=[3]), refusing=["provider/gamma"]
    )
    decoded = decode_candidate_invocation_record(encoded)
    assert decoded.output == ANSWERS["provider/alpha"]
    assert decoded.operations is not None
    combine = {op.operation_id: op for op in decoded.operations}["op_synthesis_1"].combine
    assert combine is not None
    assert [(m.member_id, m.status, m.reason) for m in combine.members] == [
        ("member_1", "answered", None),
        ("member_2", "answered", None),
        ("member_3", "fail", "missing"),
    ]
    assert failed_codes == [("provider/gamma", "logprobs_unsupported")]


@pytest.mark.asyncio
async def test_the_activity_view_shows_logprobs_unsupported() -> None:
    """LC#11 (b): the activity stream of the refused call ends with the code."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return recorded(REFUSAL)

    frames = await publish(handler, expression="/model('PRIVATE PROMPT')!go;logprobs=true")
    logs = activities(frames)
    assert len(calls) == 1
    assert calls[0]["logprobs"] is True
    assert [r.data.attributes["sf.activity.state"] for r in logs] == ["started", "failed"]
    assert logs[-1].data.attributes["sf.activity.failure_code"] == "logprobs_unsupported"
    assert frames[-1].data.status == "failed"
    assert frames[-1].data.error is not None
    assert frames[-1].data.error.code == "logprobs_unsupported"
