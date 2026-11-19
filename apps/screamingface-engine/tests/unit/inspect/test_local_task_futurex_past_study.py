# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""``futurex_past_study``: FutureX-Past scored the crowd-wisdom study's way, for replication.

What these tests pin, and why (spec docs/spec/2026-11-16-futurex-past-local-task.md §10):

- the scorer is the study's ``committee_kit/metrics.py``, byte for byte below our header;
- the data is commit 3c2e3969, the latest that holds all 100 of the study's questions, and the
  100 Case positions the README publishes are exactly the study's ``item_id``s;
- the study's stored answers, scored here, give the study's own number for all 27 models;
- the fused-medoids committee's stored answers give 0.306 here, not the study's 0.302 (its
  Table III): the committee abstained on 2 of the 100 questions, the study counts a committee
  abstain as 0, and here an empty answer leaves the score like any other (``excluded`` 2).

The fixture ``tests/fixtures/futurex_past_study/replication.json`` was generated from the study
package by ``make_replication_fixture.py`` beside it; its expected scores are the study kit's.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.scorer import SampleScore, Score  # noqa: E402

import screamingface_engine_inspect.local_tasks.futurex_past.vendor as vendor  # noqa: E402
from screamingface_engine_inspect.local_tasks.futurex_past import (  # noqa: E402
    futurex_past_study as study,
)
from screamingface_engine_inspect.local_tasks.futurex_past.futurex_past import (  # noqa: E402
    parse_ground_truth,
)

_FIXTURE: Path = (
    Path(__file__).resolve().parents[2] / "fixtures" / "futurex_past_study" / "replication.json"
)
_VENDORED: Path = Path(vendor.__file__).parent / "study_metrics.py"

#: sha256 of the study's ``metrics.py`` code AFTER its module docstring (whole file 2c94cb74…).
_STUDY_CODE_SHA256: str = "b9a81867c34e6b76f581456809afc2b99024e18358e08a64bb18f23303676176"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ── the vendored scorer ──────────────────────────────────────────────────────────────────────


def test_the_vendored_file_is_the_studys_code_below_our_header() -> None:
    """INVARIANT: a tidy-up of the copy would move every score off the study's with every
    other gate green; this hash is what notices."""

    source: bytes = _VENDORED.read_bytes()
    first: ast.stmt = ast.parse(source).body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    assert first.end_lineno is not None
    code: bytes = b"".join(source.splitlines(keepends=True)[first.end_lineno :])

    assert hashlib.sha256(code).hexdigest() == _STUDY_CODE_SHA256
    assert _STUDY_CODE_SHA256 in (vendor.__doc__ or "")


# ── the data ─────────────────────────────────────────────────────────────────────────────────


def test_the_pins_are_the_study_commit_file_and_sha256() -> None:
    assert study.STUDY_REVISION == "3c2e39690de35eb1fcc621251f56343c72bae8c4"
    assert study.STUDY_SHA256 == "55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50"


def test_the_published_100_positions_are_exactly_the_studys_questions() -> None:
    """The README's ``cases=[...]`` list: position k (1-based, file order at 3c2e3969) is the
    study's item, for all 100."""

    dataset: dict[str, Any] = _fixture()["dataset_3c2e3969"]

    assert sorted(entry["position"] for entry in dataset.values()) == list(study.STUDY_CASES)
    assert len(study.STUDY_CASES) == len(set(study.STUDY_CASES)) == 100


def test_the_datasets_key_at_3c2e3969_is_the_studys_key_after_normalisation() -> None:
    """The study froze its gold from this commit; parsed here and normalised the study's way,
    every one of the 100 keys equals the study's."""

    fixture: dict[str, Any] = _fixture()
    for item, entry in fixture["dataset_3c2e3969"].items():
        ours: list[str] = [study.normalise(t) for t in parse_ground_truth(entry["ground_truth"])]
        theirs: list[str] = [study.normalise(t) for t in fixture["gold"][item]["ground_truth"]]
        assert ours == theirs, item
        assert int(entry["level"]) == fixture["gold"][item]["level"], item


# ── the score ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "gold", "tokens", "score"),
    [
        (1, ["Blues"], ["blues"], 1.0),  # the study case-folds both sides
        (1, ["Blues"], ["Blues", "Lightning"], 0.0),
        (2, ["C", "P"], ["c"], pytest.approx(2 / 3)),
        (3, ["A  B", "C"], ["a b", "c"], 1.0),  # whitespace collapsed
        (3, ["x", "y", "z"], ["y", "x"], pytest.approx(0.8 * 2 / 3)),
        (4, [6923.23], ["6923.23"], 1.0),  # numbers compare as text, no sigma
        (4, [6923.23], ["6923.2"], 0.0),
        (4, ["x"], [], 0.0),  # no box: an abstention
    ],
)
def test_each_case_is_scored_by_the_studys_item_score_after_normalisation(
    level: int, gold: list[Any], tokens: list[str], score: float
) -> None:
    assert study.study_item_score(level, gold, tokens) == score


def _headline(scores: list[SampleScore]) -> Any:
    """Run the Task's @metric as inspect does (its ``Metric`` alias still types the argument as
    ``list[Score]``, so the call goes through ``Any``)."""

    compute: Any = study.study_tier_weighted()
    return compute(scores)


def _sample_scores(answers: dict[str, Any], gold: dict[str, Any]) -> list[SampleScore]:
    """One SampleScore per study item, as the Engine would hand them to the metric."""

    return [
        SampleScore(
            score=Score(
                value=study.study_item_score(
                    gold[item]["level"], gold[item]["ground_truth"], tokens or []
                )
            ),
            sample_id=item,
            sample_metadata={"level": gold[item]["level"]},
        )
        for item, tokens in answers.items()
    ]


@pytest.mark.parametrize("entry", ["claude-haiku-4.5", "claude-opus-4.6", "claude-sonnet-4.6"])
def test_the_studys_stored_answers_reproduce_the_studys_scores_exactly(entry: str) -> None:
    """The replication contract: same answers in, the study's number out, to 0.0 tolerance."""

    fixture: dict[str, Any] = _fixture()

    value: Any = _headline(_sample_scores(fixture["answers"][entry], fixture["gold"]))

    assert value == fixture["expected"][entry]


def test_the_studys_own_committee_rule_gives_its_0_302() -> None:
    """The study's number, by the STUDY'S rule, which is not this Benchmark's scorer.

    WHY kept: it shows where the 0.302 of the study's Table III comes from. ``_sample_scores``
    marks every cell usable, so the 2 questions the committee abstained on stay in as 0 (the
    study's ``rank.decide``). The production reading drops them; the next test pins that.
    """

    fixture: dict[str, Any] = _fixture()

    value: Any = _headline(_sample_scores(fixture["answers"]["fused-medoids"], fixture["gold"]))

    assert value == fixture["expected"]["fused-medoids"]
    assert round(float(value), 3) == 0.302


# ── the Task ─────────────────────────────────────────────────────────────────────────────────


def test_the_task_has_one_judge_free_scorer_under_the_studys_tier_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util.registry import registry_info
    from inspect_ai.dataset import Sample

    one: Sample = Sample(id="x|2026-08-01", input="Q?", target=["A"], metadata={"level": 1})
    monkeypatch.setattr(study, "load_futurex_past", lambda **_kwargs: [one])

    task = study.futurex_past_study()

    [scorer] = task.scorer or []
    assert registry_info(scorer).name.endswith("futurex_study_score")
    assert [registry_info(metric).name.split("/")[-1] for metric in task.metrics or []] == [
        "study_tier_weighted"
    ]


# ── the study's reader and its usability gate (fidelity audit D1/D2) ────────────────────────

_ALL: Path = _FIXTURE.with_name("replication_all_models.json")

#: sha256 of the study's ``bench_formats.py`` code AFTER its module docstring (file 746eb79e…).
_FORMATS_CODE_SHA256: str = "a74cbe880ffb0af9690361d87272427233950b8db98663777e486298e74eec1f"


def _all_models() -> dict[str, Any]:
    return json.loads(_ALL.read_text(encoding="utf-8"))


def test_the_vendored_reader_is_the_studys_bench_formats_below_our_header() -> None:
    source: bytes = (_VENDORED.parent / "study_formats.py").read_bytes()
    first: ast.stmt = ast.parse(source).body[0]
    assert isinstance(first, ast.Expr) and first.end_lineno is not None
    code: bytes = b"".join(source.splitlines(keepends=True)[first.end_lineno :])

    assert hashlib.sha256(code).hexdigest() == _FORMATS_CODE_SHA256
    assert _FORMATS_CODE_SHA256 in (vendor.__doc__ or "")


@pytest.mark.parametrize(
    ("reply", "tokens"),
    [
        # Each expected list is what the study's own futurex_parse + build_data split returned
        # for the reply (run on the study package, bench_formats.py sha256 746eb79e…).
        ("Reasoning...\n\\boxed{Blues}", ["Blues"]),
        ("First \\boxed{A}, then \\boxed{B, C}", ["B", "C"]),
        ("\\boxed{\\text{央视新闻, 新华社, 占豪}}", ["\\text{央视新闻", "新华社", "占豪}"]),
        ("\\boxed { 42 }", ["42"]),
        ("\\boxed{ A ,, B }", ["A", "B"]),
        ("no box", []),
        ("\\boxed{}", []),
        ("\\boxed{1{,}234}", ["1{", "}234"]),
        (
            "\\boxed{\\text{Taylor Fritz}, Novak Djokovic}",
            ["\\text{Taylor Fritz}", "Novak Djokovic"],
        ),
    ],
)
def test_a_reply_is_read_into_the_studys_tokens(reply: str, tokens: list[str]) -> None:
    assert study.study_reading(reply, "Who?").tokens == tokens


@pytest.mark.parametrize(
    ("reply", "prompt", "usable"),
    [
        ("\\boxed{B}", "Pick.\nA. one\nB. two\nC. three", True),
        ("no box at all", "Who?", False),  # no answer: the study's no_answer cell
        ("\\boxed{}", "Who?", False),
        ("\\boxed{maybe}", "Who?", False),  # a hedge, not a prediction
        ("\\boxed{A, B, C}", "Pick.\nA. one\nB. two\nC. three", False),  # every option
        ("\\boxed{Z}", "Pick.\nA. one\nB. two\nC. three", False),  # an option not offered
    ],
)
def test_a_reply_without_a_usable_answer_is_marked_unusable(
    reply: str, prompt: str, usable: bool
) -> None:
    """The study's ``interpret_answer`` gate: such a cell was excluded, never scored."""

    assert study.study_reading(reply, prompt).usable is usable


def test_the_gate_reproduces_every_exclusion_in_the_studys_stored_replies() -> None:
    """All 2,697 stored cells, each rebuilt as the study's replay rebuilds it: unusable exactly
    when the study excluded the cell (23 no answer, 15 uninterpretable)."""

    fixture: dict[str, Any] = _all_models()
    checked: int = 0
    for model, cells in fixture["answers"].items():
        if model == "fused-medoids":
            continue
        for item, cell in cells.items():
            reply: str = "(stored answer)\n\\boxed{" + ", ".join(cell["tokens"]) + "}"
            usable: bool = study.study_reading(reply, fixture["prompts"][item]).usable
            assert usable is not cell["excluded"], (model, item)
            checked += 1
    assert checked == 2697


def _study_scores(cells: dict[str, Any], fixture: dict[str, Any]) -> list[SampleScore]:
    """One SampleScore per cell the study received; a failed call (no cell) is absent, as
    ``coverage_declare`` leaves it out."""

    scores: list[SampleScore] = []
    for item, cell in cells.items():
        gold: dict[str, Any] = fixture["gold"][item]
        reply: str = "(stored answer)\n\\boxed{" + ", ".join(cell["tokens"]) + "}"
        reading = study.study_reading(reply, fixture["prompts"][item])
        value: float = study.study_item_score(gold["level"], gold["ground_truth"], reading.tokens)
        metadata: dict[str, Any] = {"level": gold["level"], "study_usable": reading.usable}
        scores.append(
            SampleScore(
                score=Score(value=value, metadata=metadata),
                sample_id=item,
                sample_metadata={"level": gold["level"]},
            )
        )
    return scores


def test_every_entry_in_the_study_reproduces_its_reported_score_exactly() -> None:
    """All 27 models: our headline, through the production reading of each stored reply,
    equals the study's ``rank.score_entry`` (which drops unusable cells from both sides).

    WHY 1e-12, not equality: the fixture's expected values were computed under Python 3.11 and
    the Engine runs 3.12, whose ``statistics.fmean`` can round the last bit differently; the
    study's own kit run under 3.12 gives our values exactly (checked on llama-4-maverick,
    0.25790034335247103 against 3.11's 0.257900343352471). Every per-Case mark is identical.
    """

    fixture: dict[str, Any] = _all_models()
    models: list[str] = [entry for entry in fixture["answers"] if entry != "fused-medoids"]
    assert len(models) == 27
    for entry in models:
        value: Any = _headline(_study_scores(fixture["answers"][entry], fixture))
        assert value == pytest.approx(fixture["expected"][entry], abs=1e-12), entry


def test_the_fused_committees_answers_score_0_306_here_with_two_cases_excluded() -> None:
    """The same stored answers the study scored 0.302, through the production reading.

    NAMED DEVIATION (second review on PR 1897): the committee abstained on 2 of the 100
    questions (no majority, an empty answer). The study's ``rank.decide`` scores a committee
    abstain 0 and keeps it; this scorer sees one reply per Case and cannot tell a committee
    from a model, so an empty answer leaves the score, as it does for a model in the study.
    The run metric ``excluded`` shows the 2.
    """

    fixture: dict[str, Any] = _all_models()
    cells: dict[str, Any] = fixture["answers"]["fused-medoids"]
    assert sum(1 for cell in cells.values() if cell.get("abstained")) == 2
    compute: Any = study.study_headline()

    result: dict[str, Any] = compute(_study_scores(cells, fixture))

    assert result["answered"] == 98 and result["excluded"] == 2
    assert result["study_score"] == pytest.approx(0.3060836169346808, abs=1e-12)
    assert round(result["study_score"], 3) == 0.306
    assert round(fixture["expected"]["fused-medoids"], 3) == 0.302


def test_an_unusable_case_leaves_both_sides_of_the_headline() -> None:
    def mark(value: float, usable: bool, case: int) -> SampleScore:
        return SampleScore(
            score=Score(value=value, metadata={"level": 1, "study_usable": usable}),
            sample_id=case,
            sample_metadata={"level": 1},
        )

    assert _headline([mark(1.0, True, 1), mark(0.0, False, 2)]) == 1.0
    assert _headline([mark(0.0, False, 1)]) == 0.0


@pytest.mark.asyncio
async def test_through_the_engine_an_unusable_reply_leaves_the_study_headline(
    tmp_path: Path, no_network: None
) -> None:
    """End to end over the production aggregate route: one right answer and one reply with no
    box. The study drops the boxless cell, so the headline is 1.0, not the 0.5 a mean gives."""

    from test_whole_run_metric import _row

    from screamingface_engine_inspect.benchmarks import imported_benchmark
    from screamingface_engine_inspect.local_tasks.futurex_past.futurex_past import (
        record_to_sample,
    )
    from screamingface_engine_inspect.prepare import (
        TASK_REPLAY_CASES,
        PreparedCase,
        _write_cases,  # pyright: ignore[reportPrivateUsage]
        prepared_case,
    )
    from screamingface_engine_inspect.single_shot import benchmark_aggregate_async

    row: dict[str, Any] = {
        "id": "6877aaaa",
        "prompt": 'Predict: "Lightning vs. Blues".\n\\boxed{Lightning} or \\boxed{Blues}',
        "end_time": "2026-07-17",
        "level": 1,
        "title": "Lightning vs. Blues",
        "ground_truth": '["Blues"]',
    }
    prepared: list[PreparedCase] = []
    for case_id in (1, 2):
        sample = record_to_sample({**row, "end_time": f"2026-07-1{case_id}"})
        case = prepared_case(
            sample, case_id, str(sample.input), TASK_REPLAY_CASES["futurex_past_study"]
        )
        prepared.append(json.loads(json.dumps(case)))
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, "\\boxed{Blues}"), _row(2, "I cannot tell.")])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("futurex_past_study"), rows, tmp_path, case_ids=(1, 2)
    )

    assert [case["status"] for case in result["cases"]] == ["scored", "scored"]
    assert result["score"] == 1.0


# ── the published excluded count (maintainer review, OME-1952) ───────────────────────────────


def test_the_rows_metric_publishes_the_study_score_beside_the_excluded_count() -> None:
    """1 right answer and 99 hedges: the study's score is 1.0, as in the study, but the run
    metric ``excluded`` says 99 Cases left it."""

    right: SampleScore = SampleScore(
        score=Score(value=1.0, metadata={"level": 1, "study_usable": True}),
        sample_id="right",
        sample_metadata={"level": 1},
    )
    hedges: list[SampleScore] = [
        SampleScore(
            score=Score(value=0.0, metadata={"level": 1, "study_usable": False}),
            sample_id=f"hedge-{n}",
            sample_metadata={"level": 1},
        )
        for n in range(99)
    ]
    compute: Any = study.study_headline()

    assert compute([right, *hedges]) == {"study_score": 1.0, "answered": 1, "excluded": 99}


def test_the_row_names_the_study_score_as_its_headline() -> None:
    from screamingface_engine_inspect.benchmarks import BENCHMARKS

    [row] = [spec for spec in BENCHMARKS if spec.key == "futurex_past_study"]

    assert row.whole_run_metric is not None
    assert row.whole_run_metric.endswith(":study_headline")
    assert row.whole_run_headline == "study_score"


@pytest.mark.asyncio
async def test_through_the_engine_the_report_shows_how_many_cases_left_the_score(
    tmp_path: Path, no_network: None
) -> None:
    """End to end: one right answer, one boxless reply → headline 1.0 and excluded 1."""

    from test_whole_run_metric import _row

    from screamingface_engine_inspect.benchmarks import imported_benchmark
    from screamingface_engine_inspect.local_tasks.futurex_past.futurex_past import (
        record_to_sample,
    )
    from screamingface_engine_inspect.prepare import (
        TASK_REPLAY_CASES,
        PreparedCase,
        _write_cases,  # pyright: ignore[reportPrivateUsage]
        prepared_case,
    )
    from screamingface_engine_inspect.single_shot import benchmark_aggregate_async

    row: dict[str, Any] = {
        "id": "6877aaaa",
        "prompt": 'Predict: "Lightning vs. Blues".\n\\boxed{Lightning} or \\boxed{Blues}',
        "end_time": "2026-07-17",
        "level": 1,
        "title": "Lightning vs. Blues",
        "ground_truth": '["Blues"]',
    }
    prepared: list[PreparedCase] = []
    for case_id in (1, 2):
        sample = record_to_sample({**row, "end_time": f"2026-07-1{case_id}"})
        case = prepared_case(
            sample, case_id, str(sample.input), TASK_REPLAY_CASES["futurex_past_study"]
        )
        prepared.append(json.loads(json.dumps(case)))
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, "\\boxed{Blues}"), _row(2, "I cannot tell.")])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("futurex_past_study"), rows, tmp_path, case_ids=(1, 2)
    )

    assert result["score"] == 1.0
    assert result["metrics"]["answered"] == 1
    assert result["metrics"]["excluded"] == 1
