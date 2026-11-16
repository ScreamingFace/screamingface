# pyright: reportMissingImports=false
"""The hosted run delivers the parked Candidate Result's exact bytes, inline or spilled.

FEATURE: memory fix 3 (OME-1835), unit 2 (parked Cases), proved on the real hosted run path.
The hosted aggregate routes use the parked faces, so the run hands the spool a
``ParkedResultBody`` and never a whole ``CandidateResult``.

INVARIANT: the delivered result bytes equal the held result's ``compact_json(as_payload())``.
Inline, the bytes ride the result frame as ``body``. Spilled through the run spool, the complete
bytes are written to the artifact store under their sha256, and the ticket's bytes equal the
same text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.dataset import Sample  # noqa: E402
from test_single_turn_judged_imports import _ScriptedNode  # noqa: E402
from test_streamed_result_hosted import _run  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks import result_body  # noqa: E402
from screamingface_engine.benchmarks.grading_endpoints import compact_json  # noqa: E402
from screamingface_engine.benchmarks.result_builder import ParkedResultBody  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    _judged_aggregate_body,
    _judged_aggregate_result,
)


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Records the type name and the expected text of each result body the aggregate delivers.

    WHY at write_result_body: deliver_result calls result_body.write_result_body at call time
    for every ResultBody, so the capture sees the parked body the hosted route returns.
    """

    seen: list[tuple[str, str]] = []
    original = result_body.write_result_body

    def _recording(body: result_body.ResultBody, write: Any) -> None:
        # WHY the original: encode_result_body calls the module's write_result_body,
        # which is this wrapper while the patch is on.
        pieces: list[str] = []
        original(body, pieces.append)
        seen.append((type(body).__name__, "".join(pieces)))
        original(body, write)

    monkeypatch.setattr(result_body, "write_result_body", _recording)
    return seen


@pytest.mark.asyncio
async def test_the_hosted_route_delivers_a_parked_body(
    tmp_path: Path, capture: list[tuple[str, str]]
) -> None:
    result, terminated = await _run(tmp_path, 5, {})

    assert terminated.data.status == "succeeded"
    assert [name for name, _ in capture] == ["ParkedResultBody"]
    assert result.data.artifact is None
    assert result.data.body == capture[0][1]


@pytest.mark.asyncio
async def test_a_spilled_parked_body_redeems_to_the_same_bytes(
    tmp_path: Path, capture: list[tuple[str, str]]
) -> None:
    result, terminated = await _run(tmp_path, 5, {"URL4_CLOUD_RESULT_INLINE_CAP_BYTES": "1024"})

    assert terminated.data.status == "succeeded"
    assert [name for name, _ in capture] == ["ParkedResultBody"]
    artifact = result.data.artifact
    assert artifact is not None
    data = (tmp_path / "art" / artifact.id).read_bytes()
    expected = capture[0][1].encode("utf-8")
    assert data == expected
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_the_judged_body_face_writes_the_held_bytes(tmp_path: Path) -> None:
    samples: list[Sample] = [
        Sample(id=index, input=question, target=gold)
        for index, (question, gold) in enumerate(
            [("Capital of Uganda?", "Kampala"), ("Year Inspect launched?", "2024"), ("?", "x")],
            start=1,
        )
    ]
    cases = [
        prepared_case(sample, index, str(sample.input), TASK_REPLAY_CASES["simpleqa"])
        for index, sample in enumerate(samples, start=1)
    ]
    _write_cases(cases, tmp_path)
    rows: str = json.dumps(
        [_row(index, reply) for index, reply in enumerate(["Kampala", "2019", "I don't know."], 1)]
    )
    with request_scope(RequestScope(origin="run")):
        held = await _judged_aggregate_result(
            imported_benchmark("simpleqa"),  # type: ignore[arg-type]
            tmp_path,
            _ScriptedNode(["A", "B", "C"]),  # type: ignore[arg-type]
        )(rows, (1, 2, 3))
        body = await _judged_aggregate_body(
            imported_benchmark("simpleqa"),  # type: ignore[arg-type]
            tmp_path,
            _ScriptedNode(["A", "B", "C"]),  # type: ignore[arg-type]
        )(rows, (1, 2, 3))
    assert isinstance(body, ParkedResultBody)
    assert result_body.encode_result_body(body) == compact_json(held.as_payload())
