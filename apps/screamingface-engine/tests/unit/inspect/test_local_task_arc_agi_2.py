# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""ARC-AGI-2 as a LOCAL inspect Task (OME-1476) — the ARC Prize harness's exam, on our spine.

FEATURE: ARC-AGI-2 public eval as a Benchmark. Think of two examiners grading the same answer
sheets with the same key: the ARC Prize harness and us. These tests pin that we ask the same
question, read the answer the same way, and add up the marks the same way, so our number on a
clean run IS the harness's number on the same replies.

What these tests pin, and why:

- the prompt: the template's bytes equal the harness's ``system_prompt.txt`` and a fixture
  prompt equals what the harness's own builder printed (sha256 below) — the prompt is Benchmark
  identity;
- the reply reader: the vendored parser decides; a reply with no grid scores 0, never raises
  (spec D5);
- conservation: the Headline Score equals the harness's ``score_task`` / ``score_submission``
  arithmetic on the same replies, including a grid whose Attempts both failed (spec D7) — the
  oracle is that arithmetic restated in ``_harness_headline``;
- the limits we declared: a task with EVERY grid failed drops out (the harness counts it 0),
  and missing Sample metadata scores as the plain mean;
- the row: two Attempts with ``max``, the per-task metric honoured, origin ``screamingface``;
- the two reproducibility pins the ticket asked for: ARC's url4 bytes, and one known
  ``derive_attempt_seed`` value.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.graded_answer import CASE_ATTEMPTS_SCHEMA  # noqa: E402
from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    imported_benchmark,
)
from screamingface_engine_inspect.local_tasks.arc_agi_2 import arc_agi_2  # noqa: E402
from screamingface_engine_inspect.local_tasks.arc_agi_2.arc_agi_2 import (  # noqa: E402
    PROMPT_TEMPLATE,
    arc_exact_match,
    build_prompt,
    read_grid,
    samples_from_zip,
    task_to_samples,
)
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, _write_cases  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    benchmark_aggregate_async,
    single_shot_benchmark,
)

#: sha256 of ``src/arc_agi_benchmarking/prompts/system_prompt.txt`` at
#: arcprize/arc-agi-benchmarking@9e2828fb5bd3ab43f6b9fc545595b82b67473b93.
_UPSTREAM_TEMPLATE_SHA256 = "065e42f724bcfe3a735ded38d92b34a6a942604e653a0584cc08b1de9bdf70cc"

#: The harness's own ``convert_task_pairs_to_prompt`` over ``_FIXTURE_TASK`` (train pairs, test
#: input 0), run at that same commit with its pydantic ``ARCPair``: sha256 of the returned str.
_UPSTREAM_FIXTURE_PROMPT_SHA256 = "fc42a381c450d3f952117862ddf96990fb5ba06ade4479cb16051cc0478f19a1"

#: A two-grid task, small enough to read. Grid 0's answer is [[3, 3], [0, 3]].
_FIXTURE_TASK: dict[str, Any] = {
    "train": [
        {"input": [[0, 1], [1, 0]], "output": [[1, 0], [0, 1]]},
        {"input": [[2]], "output": [[3]]},
    ],
    "test": [
        {"input": [[4, 5, 6]], "output": [[3, 3], [0, 3]]},
        {"input": [[7]], "output": [[8]]},
    ],
}


# ── the prompt: the harness's question, byte for byte ─────────────────────────────────────


def test_the_template_is_the_harness_prompt_file_byte_for_byte() -> None:
    """INVARIANT: the restated template IS upstream's file (it ends with no newline)."""

    digest: str = hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()

    assert digest == _UPSTREAM_TEMPLATE_SHA256


def test_a_fixture_prompt_equals_the_harness_builders_output() -> None:
    """The restated builder (example numbering, the spaces after ``--`` and ``INPUT:``, the
    ``json.dumps`` default separators) prints exactly what the harness printed."""

    prompt: str = build_prompt(_FIXTURE_TASK["train"], _FIXTURE_TASK["test"][0]["input"])

    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == _UPSTREAM_FIXTURE_PROMPT_SHA256
    assert prompt.endswith("--Test Input--\n[[4, 5, 6]]\n--End of Test Input--\n\nYour response:")


def test_one_sample_per_test_grid_in_order_with_its_task() -> None:
    """Spec D1: a task with two test grids is two Cases; each knows its task and how many
    grids that task has (D7's denominator)."""

    samples = task_to_samples("t2", _FIXTURE_TASK)

    assert [sample.id for sample in samples] == ["t2_0", "t2_1"]
    assert [sample.target for sample in samples] == ["[[3, 3], [0, 3]]", "[[8]]"]
    assert [sample.metadata for sample in samples] == [
        {"task_id": "t2", "test_index": 0, "grids_in_task": 2},
        {"task_id": "t2", "test_index": 1, "grids_in_task": 2},
    ]
    assert samples[1].input == build_prompt(_FIXTURE_TASK["train"], [[7]])


# ── the reply reader: the harness's parser decides ───────────────────────────────────────


@pytest.mark.parametrize(
    ("reply", "grid"),
    [
        # \boxed{} wins even when a different grid comes later.
        ("thinking... \\boxed{[[1, 2], [3, 4]]} then [[9]]", [[1, 2], [3, 4]]),
        # No \boxed{}: the LAST bracketed JSON in the reply.
        ("first [[0]] then the answer:\n```\n[[5, 6]]\n```", [[5, 6]]),
        # Rows of unequal length still parse: shape is checked by comparing to the target.
        ("[[1, 2], [3]]", [[1, 2], [3]]),
        # Nothing bracketed at all.
        ("The output is a 2 by 2 grid of threes.", None),
        # A flat list is not a grid.
        ("[1, 2, 3]", None),
        # Upstream quirk kept: a reply ending in "}" is tried as a dict and gives up.
        ("[[1]] and then {}", None),
    ],
)
def test_the_reply_reader_is_the_harness_parser(reply: str, grid: list[list[int]] | None) -> None:
    assert read_grid(reply) == grid


async def _mark(reply: str, target: str) -> Score:
    """inspect's own (state, target) → Score call, as the scorer adapter makes it."""

    state = TaskState(
        model="screamingface/candidate",  # type: ignore[arg-type]
        sample_id="t2_0",
        epoch=1,
        input="q",
        messages=[ChatMessageUser(content="q")],
        output=ModelOutput.from_content(model="screamingface/candidate", content=reply),
    )
    score: Score | None = await arc_exact_match()(state, Target(target))
    assert score is not None, "arc_exact_match always returns a Score"
    return score


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "value", "explanation"),
    [
        ("\\boxed{[[3, 3], [0, 3]]}", 1.0, None),
        # One cell off is wrong: the harness compares whole grids.
        ("[[3, 3], [3, 3]]", 0.0, None),
        # Spec D5: no extraction call, no re-ask — an unreadable reply is a wrong answer.
        ("I am not sure.", 0.0, "no grid found"),
    ],
)
async def test_an_attempt_scores_one_only_on_the_exact_grid(
    reply: str, value: float, explanation: str | None
) -> None:
    score: Score = await _mark(reply, "[[3, 3], [0, 3]]")

    assert score.value == value
    assert score.explanation == explanation


# ── conservation: our headline is the harness's arithmetic ──────────────────────────────


def _harness_headline(grids: list[tuple[str, int, list[str | None]]]) -> float:
    """The oracle: the ARC Prize scorer's arithmetic, restated from arc-agi-benchmarking@9e2828fb.

    ``score_task`` (scoring.py:122-127): a test grid passes if ANY attempt equals its output; a
    failed attempt is a null slot that never passes (main.py:334); task score = passed / grids.
    ``score_submission`` (scoring.py:160-234): headline = sum of task scores / tasks.
    Each entry is (task id, grids in that task, the attempts' replies; None = failed).
    """

    passed: dict[str, int] = {}
    totals: dict[str, int] = {}
    for task_id, grids_in_task, replies in grids:
        totals[task_id] = grids_in_task
        solved: bool = any(reply == "RIGHT" for reply in replies if reply is not None)
        passed[task_id] = passed.get(task_id, 0) + int(solved)
    return sum(passed[task] / totals[task] for task in totals) / len(totals)


#: (task id, grids in task, [Attempt 1, Attempt 2]); "RIGHT" is the target grid, "WRONG" a
#: wrong grid, None a failed Attempt. Task p: 2 grids, one solved by Attempt 2 only. Task q:
#: 2 grids, one solved, the other's Attempts BOTH failed (spec D7: counts 0, as the harness
#: does). Task r: 1 grid, wrong.
_RUN: list[tuple[str, int, list[str | None]]] = [
    ("p", 2, ["WRONG", "RIGHT"]),
    ("p", 2, ["WRONG", "WRONG"]),
    ("q", 2, ["RIGHT", "WRONG"]),
    ("q", 2, [None, None]),
    ("r", 1, ["WRONG", "WRONG"]),
]

_TARGET: list[list[int]] = [[1, 2], [3, 4]]


def _reply_text(reply: str | None) -> str:
    """The Candidate's reply text for one fixture Attempt."""

    return json.dumps(_TARGET) if reply == "RIGHT" else "[[0, 0], [0, 0]]"


def _arc_row() -> BenchmarkSpec:
    """The published ``arc_agi_2`` row — its scorer, metric and reducer are what we test."""

    return next(row for row in BENCHMARKS if row.key == "arc_agi_2")


def _assembled_from_row(key: str, case_count: int) -> ImportedBenchmark:
    """The plugin Benchmark the real row assembles into, over stand-in Cases (no network)."""

    row: BenchmarkSpec = _arc_row()
    return single_shot_benchmark(
        benchmark_key=key,
        title="ARC-AGI-2 stand-in",
        description="The arc_agi_2 row over stand-in Cases.",
        focus="Reasoning",
        dataset_url="https://example.test/arc",
        case_count=case_count,
        revision_pins=("stand-in",),
        scorer_factory=benchmarks._scorer_factory(row),
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="hard",
        failure_policy="coverage_declare",
        whole_run_metric_factory=benchmarks._whole_run_metric_factory(row),
        epoch_reducer_factory=benchmarks._epoch_reducer_factory(row),
        attempts=row.attempts,
    )


async def _run(
    tmp_path: Path,
    key: str,
    grids: list[tuple[str, int, list[str | None]]],
    *,
    metadata: bool = True,
) -> dict[str, Any]:
    """Grade every Case's two Attempts through the plugin's own aggregate. A Case whose
    Attempts failed arrives as a collected error row in its slot: a failed Candidate
    Invocation fails the whole Case (OME-1458's Candidate-failure limitation), so a failed
    Case is the only failure shape a run hands over."""

    # WHY a key per test: an assembled id is bound to one revision (its case count included).
    benchmark: ImportedBenchmark = _assembled_from_row(key, len(grids))
    _write_cases(
        [
            {
                "case": {"id": index, "case_id": str(index), "input": f"grid {index}"},
                "grading_material": {
                    "target": json.dumps(_TARGET),
                    "metadata": {"task_id": task_id, "grids_in_task": grids_in_task}
                    if metadata
                    else {},
                },
            }
            for index, (task_id, grids_in_task, _) in enumerate(grids, start=1)
        ],
        tmp_path,
    )
    rows: str = json.dumps(
        [
            {
                "schema": CASE_ATTEMPTS_SCHEMA,
                "case_id": index,
                "attempts": [_row(index, _reply_text(reply)) for reply in replies],
            }
            if all(reply is not None for reply in replies)
            # Stand-in for a Case whose Candidate Invocation failed (e.g. the token cap): the
            # error row the run collects in that Case's slot. It does not simulate WHICH
            # Attempt failed; the Engine fails the Case either way.
            else {
                "case_id": index,
                "error": {"kind": "ResolutionError", "message": "cap", "code": "upstream_error"},
            }
            for index, (_, _, replies) in enumerate(grids, start=1)
        ]
    )
    return await benchmark_aggregate_async(
        benchmark, rows, tmp_path, case_ids=tuple(range(1, len(grids) + 1))
    )


@pytest.mark.asyncio
async def test_the_headline_is_the_harness_score_on_the_same_replies(tmp_path: Path) -> None:
    """Worked example: p = 1/2, q = 1/2 (its failed grid counts 0), r = 0/1, so the harness
    says (0.5 + 0.5 + 0) / 3 = 0.3333. A per-grid mean would say 2/4 = 0.5, and leaving q's
    failed grid out of its task would say (0.5 + 1 + 0) / 3 = 0.5 — both wrong."""

    result: dict[str, Any] = await _run(tmp_path, "arc-conservation", _RUN)

    assert result["score"] == round(_harness_headline(_RUN), 4) == 0.3333


@pytest.mark.asyncio
async def test_a_task_with_every_grid_failed_drops_out(tmp_path: Path) -> None:
    """Spec §4 limitation, pinned so a fix is a visible change: task s's only grid failed both
    Attempts, so no Score of task s reaches the metric. We say p alone = 1/1 = 1.0; the harness
    counts s as 0 and says (1 + 0) / 2 = 0.5."""

    run: list[tuple[str, int, list[str | None]]] = [
        ("p", 1, ["RIGHT", "WRONG"]),
        ("s", 1, [None, None]),
    ]

    result: dict[str, Any] = await _run(tmp_path, "arc-task-dropped", run)

    assert result["score"] == 1.0
    assert _harness_headline(run) == 0.5


@pytest.mark.asyncio
async def test_missing_metadata_scores_as_the_plain_mean(tmp_path: Path) -> None:
    """The no-network grading lane's stand-in Cases carry no metadata: each Case then counts as
    its own one-grid task, never a KeyError. p's two grids: one solved → 1/2."""

    run: list[tuple[str, int, list[str | None]]] = [
        ("p", 2, ["RIGHT", "WRONG"]),
        ("p", 2, ["WRONG", "WRONG"]),
    ]

    result: dict[str, Any] = await _run(tmp_path, "arc-no-metadata", run, metadata=False)

    assert result["score"] == 0.5


# ── the loader: one pinned zip, counted ──────────────────────────────────────────────────


def _fake_zip(path: Path, tasks: dict[str, dict[str, Any]]) -> Path:
    """A zip laid out like GitHub's archive of the data repo at the pinned commit."""

    with zipfile.ZipFile(path, "w") as archive:
        for task_id, task in tasks.items():
            archive.writestr(f"{arc_agi_2.EVAL_DIR}/{task_id}.json", json.dumps(task))
        archive.writestr(f"{arc_agi_2.EVAL_DIR.rsplit('/', 1)[0]}/training/x.json", "{}")
    return path


def test_the_zip_becomes_samples_task_by_task_in_id_order(tmp_path: Path) -> None:
    one_grid: dict[str, Any] = {**_FIXTURE_TASK, "test": _FIXTURE_TASK["test"][:1]}
    path: Path = _fake_zip(tmp_path / "a.zip", {"bb": _FIXTURE_TASK, "aa": one_grid})

    samples = samples_from_zip(path, expected_tasks=2, expected_grids=3)

    # Training files are ignored; tasks sorted by id; grids in task order.
    assert [sample.id for sample in samples] == ["aa_0", "bb_0", "bb_1"]


def test_a_zip_with_the_wrong_counts_is_refused_by_name(tmp_path: Path) -> None:
    """Spec F2: the build stops rather than serve a different exam."""

    path: Path = _fake_zip(tmp_path / "a.zip", {"aa": _FIXTURE_TASK})

    with pytest.raises(ValueError, match=r"1 tasks and 2 test grids, expected 120 and 167"):
        samples_from_zip(path, expected_tasks=120, expected_grids=167)


def test_the_loader_downloads_the_pinned_zip_with_its_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec D6: one ``inspect_ai.util.download`` call (the Case Source recorder wraps it) with
    the commit-pinned URL and its sha256; the counts come from the module constants."""

    import inspect_ai.util

    calls: list[tuple[str, str]] = []
    source: Path = _fake_zip(tmp_path / "src.zip", {"aa": _FIXTURE_TASK})

    def fake_download(url: str, sha256: str, dest: Path, **_: Any) -> Path:
        calls.append((url, sha256))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        return dest

    monkeypatch.setattr(inspect_ai.util, "download", fake_download)
    monkeypatch.setattr(arc_agi_2, "EXPECTED_TASKS", 1)
    monkeypatch.setattr(arc_agi_2, "EXPECTED_GRIDS", 2)

    dataset = arc_agi_2.load_arc_agi_2_eval(cache_dir=tmp_path / "cache")

    assert calls == [(arc_agi_2.ZIP_URL, arc_agi_2.ZIP_SHA256)]
    assert "f3283f727488ad98fe575ea6a5ac981e4a188e49" in arc_agi_2.ZIP_URL
    assert [sample.id for sample in dataset] == ["aa_0", "aa_1"]


# ── the row ──────────────────────────────────────────────────────────────────────────────


def test_the_row_asks_twice_takes_any_match_and_honours_the_per_task_metric() -> None:
    """Spec D2/D3: two Attempts reduced with ``max`` (``pass_at_2`` would make a Case with a
    failed Attempt nan and refuse the run), and the Headline Score is our per-task metric."""

    row: BenchmarkSpec = _arc_row()
    benchmark = imported_benchmark("arc_agi_2")

    assert (row.attempts, row.epoch_reducer) == (2, "max")
    assert row.whole_run_metric == (
        "screamingface_engine_inspect.local_tasks.arc_agi_2.arc_agi_2:arc_per_task_accuracy"
    )
    assert benchmark.benchmark.id == "arc_agi_2"
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert TASK_REPLAY_CASES["arc_agi_2"].keep_sample_metadata is True
    assert TASK_REPLAY_CASES["arc_agi_2"].case_count == 167


def test_the_arc_url4_is_pinned_byte_for_byte() -> None:
    """Ticket comment pin (a): ARC-AGI-2 is the first published Benchmark with Attempts, so any
    change to how Attempts are written into its url4 fails here instead of quietly moving the
    Benchmark Revision. Sits here, not in test_benchmark_protocol.py, because that module runs
    without the inspect extra and an imported Benchmark needs it."""

    from url4 import render

    imported: ImportedBenchmark = imported_benchmark("arc_agi_2")
    url4: str = render(imported.benchmark.build(167))

    assert (
        hashlib.sha256(url4.encode()).hexdigest()
        == "294a48447d1890ef2ff7bbfab5705274f37476aaf3feec6f22a72608cce4a942"
    )
