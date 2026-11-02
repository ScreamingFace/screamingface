# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""An inspect scorer sees whether the Candidate's reply was cut off (OME-1701 PR 7).

Think of the Case record as the exam script with a note from the invigilator stapled on: "time
ran out mid-sentence". The scorer adapter copies the script onto inspect's forms; before this
change it dropped the note and wrote "finished normally" on every script, so no inspect scorer
could tell a cut-off reply from a finished one.

What these tests pin, and why:

- the note travels the real path: the Candidate's provider finish reason, recorded by the
  Benchmark's own check route, reaches the scorer through the shared grading aggregate as
  inspect's stop reason (``length`` → ``max_tokens``, ``stop`` → ``stop``, none → ``unknown``,
  never a made-up ``stop``);
- end to end on AIME, the one row family whose grade reads it: the SAME text scores right when
  the reply finished and wrong when it was cut off (inspect_evals issue #2701, adopted);
- the mid-run check surface marks a cut-off draft as the final grade would, so its feedback
  never passes a draft the grade fails.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from replayed_cases_helpers import prepare_with_stand_in_hub  # noqa: E402

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.envelopes import build_case_grade  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

AIME24: Any = imported_benchmark("aime24")

#: Two stand-in Hub rows in AIME_2024's own columns; Case 1's key is 1, Case 2's is 16.
_ROWS: list[dict[str, Any]] = [
    {"ID": "2024-I-1", "Problem": "Find the remainder.", "Answer": 1, "Solution": "..."},
    {"ID": "2024-I-2", "Problem": "Find n squared plus 7.", "Answer": 16, "Solution": "..."},
]

#: inspect_evals issue #2701's reproduction: still working when the limit hit, last value 1.
_CUT_OFF_TEXT: str = "Try n = 3: then 3^2 + 7 = 16, so the remainder is 1"


def _node(tmp_path: Path) -> Url4Node:
    """A node serving aime24 over the two stand-in Cases, prepared by Task replay."""

    root: Path = tmp_path / AIME24.benchmark.id
    prepare_with_stand_in_hub("aime24", _ROWS, root)
    node = Url4Node("test")
    AIME24.benchmark.install(node, tmp_path)
    return node


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    """One url4 call to a Benchmark route, the way the run's protocol makes it."""

    result: Any = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


async def _graded_row(node: Url4Node, case_id: int, answer: str, finish: str | None) -> object:
    """One collected row, its Case record written by aime24's OWN check route."""

    invocation: str = encode_candidate_invocation(answer, finish, None)
    record: dict[str, Any] = json.loads(
        await _call(node, AIME24.check_route, invocation, str(case_id))
    )
    return graded_answer_payload(case_id, invocation, [build_case_grade(case_id, [record])])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "stop_reason"),
    [("length", "max_tokens"), ("stop", "stop"), (None, "unknown")],
)
async def test_the_candidate_finish_reason_reaches_the_scorer_as_inspect_stop_reason(
    tmp_path: Path, finish_reason: str | None, stop_reason: str
) -> None:
    """The provider's word for why the reply ended is the stop reason the scorer reads; an
    unknown one stays unknown rather than claiming the reply finished."""

    node: Url4Node = _node(tmp_path)
    seen: list[str] = []

    async def probe(state: TaskState, target: Target) -> Score:
        """A stand-in scorer that only records the stop reason it was handed."""

        seen.append(state.output.stop_reason)
        return Score(value=1.0)

    row: object = await _graded_row(node, 1, _CUT_OFF_TEXT, finish_reason)
    await replace(AIME24.aggregation(), grade_case=inspect_grade_case(probe)).aggregate_async(
        json.dumps([row]),
        benchmark_id=AIME24.benchmark.id,
        benchmark_revision=AIME24.benchmark.revision,
        selected_cases=[SelectedCase(case_id=1, input="Find the remainder.", metadata={})],
        grading_material=lambda case_id: {"target": "1"},
        scorer=lambda cases: CandidateScore(score=1.0, metrics={}),
    )

    assert seen == [stop_reason]


@pytest.mark.asyncio
async def test_aime_scores_the_same_text_right_when_finished_and_wrong_when_cut_off(
    tmp_path: Path,
) -> None:
    """End to end through aime24's aggregate route: only the finish reason differs."""

    node: Url4Node = _node(tmp_path)
    rows: list[object] = [
        await _graded_row(node, 1, _CUT_OFF_TEXT, "length"),
        await _graded_row(node, 2, "3^2 + 7 = 16\nANSWER: 16", "length"),
    ]
    cut_off: dict[str, Any] = json.loads(
        await _call(node, AIME24.aggregate_route, json.dumps(rows), "aggregate:2")
    )
    finished_row: object = await _graded_row(node, 1, _CUT_OFF_TEXT, "stop")
    finished: dict[str, Any] = json.loads(
        await _call(
            node, AIME24.aggregate_route, json.dumps([finished_row, rows[1]]), "aggregate:2"
        )
    )

    # WHY Case 2 stays right: it was cut off only after writing its ANSWER: line.
    assert [case["grade"]["score"] for case in cut_off["cases"]] == [0.0, 1.0]
    assert [case["grade"]["score"] for case in finished["cases"]] == [1.0, 1.0]


def _surface_probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    """aime24's own row re-assembled WITH the Draft Feedback offer, on fresh caches.

    WHY a stand-in: the offer is a per-Benchmark owner decision (OME-1513) and aime24 has it
    off, so this proves the surface CODE on aime24's scorer and Cases with the one flag flipped.
    """

    spec: Any = replace(
        next(row for row in BENCHMARKS if row.key == "aime24"), with_check_surface=True
    )
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return imported_benchmark("aime24")


@pytest.mark.asyncio
@pytest.mark.parametrize(("finish_reason", "passed"), [("length", False), ("stop", True)])
async def test_the_check_surface_marks_a_cut_off_draft_as_the_grade_would(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finish_reason: str, passed: bool
) -> None:
    probe: Any = _surface_probe(monkeypatch)
    prepare_with_stand_in_hub("aime24", _ROWS, tmp_path / probe.benchmark.id)
    node = Url4Node("test")
    probe.benchmark.install(node, tmp_path)
    booklet: Path = tmp_path / probe.benchmark.id / "cases.json"
    prompt: str = json.loads(booklet.read_text(encoding="utf-8"))[0]["input"]
    payload: str = json.dumps(
        {
            "input": prompt,
            "invocation": encode_candidate_invocation(_CUT_OFF_TEXT, finish_reason, None),
        }
    )

    record: dict[str, Any] = json.loads(
        await _call(node, probe.check_surface_route, payload, "check")
    )

    assert record["passed"] is passed
