"""The imported `inspect-gsm8k` proof board — spec §3 end to end, minus the paid run.

FEATURE: the first stranger-authored benchmark on the shared spine with zero spine
edits (OME-1115). This suite drives the board's definition, asset snapshot, runtime
routes, the shared spine aggregate through the scorer shim, and the §4 check surface
(the SAME wrapped scorer serving mid-run feedback).

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest …`);
the plain gate run skips it, which is exactly the extra-less contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.ensemble.policy import CHECK_SURFACE_SCHEMA  # noqa: E402
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine_inspect.gsm8k import GSM8K_BOARD  # noqa: E402
from screamingface_engine_inspect.prepare import SNAPSHOTS, emit_snapshot  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_ROWS: list[dict[str, Any]] = [
    {"question": "What is 6 times 7?", "answer": "6 * 7 = 42\n#### 42"},
    {"question": "A train travels 30 km twice. Total?", "answer": "30 + 30 = 60\n#### 60"},
]


def _bake(root: Path) -> Path:
    """Bake a two-case snapshot in the board's asset layout (assets/<benchmark id>/)."""

    emit_snapshot(SNAPSHOTS["gsm8k"], _ROWS, root / GSM8K_BOARD.benchmark.id)
    return root


# ── definition ───────────────────────────────────────────────────────────────


def test_board_identity_and_declaration() -> None:
    board = GSM8K_BOARD.benchmark
    assert board.id == "inspect-gsm8k"
    assert len(board.revision) == 16 and int(board.revision, 16) >= 0
    assert board.declaration.as_block() == {
        "failure_policy": "coverage_declare",
        "interaction": "single_shot",
    }
    assert board.case_count == 1319
    assert board.dataset_url is not None and "gsm8k" in board.dataset_url


def test_check_surface_is_declared_and_free() -> None:
    """§4 — the wrapped scorer is ALSO the advertised mid-run check, at zero cost."""

    surface = GSM8K_BOARD.benchmark.check_surface
    assert surface is not None
    assert surface.expected_check_cost == "free"
    assert GSM8K_BOARD.benchmark.revision in surface.check_route


def test_registration_carries_the_board_and_its_bundle() -> None:
    assert GSM8K_BOARD.registration.benchmark is GSM8K_BOARD.benchmark
    assert GSM8K_BOARD.registration.asset_bundle.id == GSM8K_BOARD.benchmark.id


def test_resource_renders_a_protocol_for_a_selection() -> None:
    resource = GSM8K_BOARD.benchmark.resource(limit=5)
    assert resource["selected_case_count"] == 5
    assert GSM8K_BOARD.benchmark.revision in str(resource["url4"])


# ── runtime + spine aggregate ────────────────────────────────────────────────


def _node(tmp_path: Path) -> Url4Node:
    node = Url4Node("test")
    GSM8K_BOARD.benchmark.install(node, _bake(tmp_path))
    return node


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


@pytest.mark.asyncio
async def test_check_route_records_the_candidate_answer_verbatim(tmp_path: Path) -> None:
    node = _node(tmp_path)
    invocation = encode_candidate_invocation("ANSWER: 42", "stop", None)
    reply = json.loads(await _call(node, GSM8K_BOARD.check_route, invocation, "1"))
    assert reply["schema"] == CHECK_SCHEMA
    assert reply["case_id"] == 1
    assert reply["answer"] == "ANSWER: 42"
    assert reply["status"] == "completed"


@pytest.mark.asyncio
async def test_check_route_refuses_a_case_with_an_unusable_target(tmp_path: Path) -> None:
    """Refuse-early pin: an attempt against a missing answer key fails the CALL —
    it must never record an ungradeable attempt for the aggregate to trip on later."""

    node = _node(tmp_path)
    (tmp_path / GSM8K_BOARD.benchmark.id / "targets" / "1.json").unlink()
    invocation = encode_candidate_invocation("ANSWER: 42", "stop", None)
    with pytest.raises(Exception, match="target record"):
        await _call(node, GSM8K_BOARD.check_route, invocation, "1")


def _row(case_id: int, answer: str) -> dict[str, object]:
    record = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
    }
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [bind_case_evaluation(case_id, [record])],
    )


@pytest.mark.asyncio
async def test_aggregate_scores_through_the_shared_spine(tmp_path: Path) -> None:
    """Two Cases, one right one wrong → accuracy 0.5, real evidence per Case."""

    node = _node(tmp_path)
    rows = json.dumps([_row(1, "The sum is small.\nANSWER: 42"), _row(2, "ANSWER: 59")])
    result = json.loads(await _call(node, GSM8K_BOARD.aggregate_route, rows, "aggregate:2"))
    assert result["benchmark_id"] == "inspect-gsm8k"
    assert result["score"] == 0.5
    assert result["metrics"]["scored_cases"] == 2
    grades = [case["grade"] for case in result["cases"]]
    assert [grade["score"] for grade in grades] == [1.0, 0.0]
    # The scorer's verdict rides the checks evidence — audit material per Case.
    assert grades[0]["checks"][0]["type"] == "inspect_scorer"
    assert grades[0]["checks"][0]["outcome"] == "MET"


@pytest.mark.asyncio
async def test_a_missing_row_is_a_named_failure_not_a_zero(tmp_path: Path) -> None:
    node = _node(tmp_path)
    rows = json.dumps([_row(1, "ANSWER: 42")])
    result = json.loads(await _call(node, GSM8K_BOARD.aggregate_route, rows, "aggregate:2"))
    failed = result["cases"][1]
    assert failed["grade"]["score"] is None
    assert failed["failures"][0]["code"] == "missing_case_row"
    assert result["metrics"]["scored_cases"] == 1


@pytest.mark.asyncio
async def test_a_missing_target_asset_fails_by_its_own_name(tmp_path: Path) -> None:
    node = _node(tmp_path)
    (tmp_path / GSM8K_BOARD.benchmark.id / "targets" / "2.json").unlink()
    rows = json.dumps([_row(1, "ANSWER: 42"), _row(2, "ANSWER: 60")])
    result = json.loads(await _call(node, GSM8K_BOARD.aggregate_route, rows, "aggregate:2"))
    assert result["cases"][1]["failures"][0]["code"] == "missing_target_asset"


# ── §4 check surface ─────────────────────────────────────────────────────────


def _prompt(tmp_path: Path) -> str:
    booklet = tmp_path / GSM8K_BOARD.benchmark.id / "cases.json"
    return json.loads(booklet.read_text(encoding="utf-8"))[0]["input"]


async def _surface_check(node: Url4Node, tmp_path: Path, answer: str) -> dict[str, object]:
    payload = json.dumps(
        {
            "input": _prompt(tmp_path),
            "invocation": encode_candidate_invocation(answer, "stop", None),
        }
    )
    reply = await _call(node, GSM8K_BOARD.check_surface_route, payload, "check")
    return json.loads(reply)


@pytest.mark.asyncio
async def test_check_surface_passes_a_correct_answer(tmp_path: Path) -> None:
    node = _node(tmp_path)
    record = await _surface_check(node, tmp_path, "ANSWER: 42")
    assert record["schema"] == CHECK_SURFACE_SCHEMA
    assert record["passed"] is True
    assert record["satisfaction"] == 1.0
    assert record["feedback"] == ""


@pytest.mark.asyncio
async def test_check_surface_fails_without_leaking_the_target(tmp_path: Path) -> None:
    """Sealed envelope: mid-run feedback may say wrong, never WHAT the answer is."""

    node = _node(tmp_path)
    record = await _surface_check(node, tmp_path, "ANSWER: 59")
    assert record["passed"] is False
    assert record["satisfaction"] == 0.0
    feedback = str(record["feedback"])
    assert feedback  # the loop needs something to react to
    assert "42" not in feedback


@pytest.mark.asyncio
async def test_check_surface_feedback_intent_extracts_the_feedback(
    tmp_path: Path,
) -> None:
    node = _node(tmp_path)
    record = await _surface_check(node, tmp_path, "ANSWER: 59")
    reply = await _call(node, GSM8K_BOARD.check_surface_route, json.dumps(record), "feedback")
    assert reply == record["feedback"]


@pytest.mark.asyncio
async def test_check_surface_refuses_an_unusable_target_in_the_plugins_voice(
    tmp_path: Path,
) -> None:
    """INVARIANT: failure wording is this plugin's published voice — a missing key
    refuses with the named missing_target_asset message, never the shim's internal
    TypeError vocabulary reaching the candidate mid-run."""

    node = _node(tmp_path)
    (tmp_path / GSM8K_BOARD.benchmark.id / "targets" / "1.json").unlink()
    with pytest.raises(Exception, match="baked target record"):
        await _surface_check(node, tmp_path, "ANSWER: 42")
