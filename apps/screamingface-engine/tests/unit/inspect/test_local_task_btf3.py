# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, huggingface_hub and pyarrow, absent in the
# extra-less typecheck install.
"""BTF-3 (binary) as a LOCAL inspect Task: the Case, the reply reader, the mark, the headline.

What these tests pin, and why (spec docs/spec/2026-11-17-btf3-local-task.md, §12: the design of
ScreamingFace/screamingface#1868, OME-1938, "a replication runs the paper's questions, prompt and
grading rule"):

- the Case: the contributor's study prompt (its shortened copy of Bench to the Future's A.1,
  research left empty) with its answer line reworded to name a probability, filled with the
  row (§3, §12);
- the reply: the study's own reader, ``btf_parse``, vendored verbatim (§3);
- the mark: accuracy, a forecast of 0.5 or more reads Yes; the Brier score rides beside it (§4);
- a reply with no forecast is a miss and costs Brier 0.25: issue #1868's rule, the study's
  rule for a crowd with no decision, a named deviation for one model's reply (§12).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

import huggingface_hub  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.model import ModelName, ModelOutput  # noqa: E402
from inspect_ai.scorer import SampleScore, Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine_inspect.local_tasks.btf3 import btf3  # noqa: E402
from screamingface_engine_inspect.local_tasks.btf3.vendor import study_btf_parse  # noqa: E402

#: Two rows in the pinned schema: one resolved Yes, one No.
_ROWS: list[dict[str, Any]] = [
    {
        "question_id": "444b8215-8b25-5b43-9625-2de4476e49b7",
        "question": "Will the SEC approve the ETF by June 1, 2026?",
        "resolution_criteria": "Resolves YES if the SEC approves it by June 1, 2026.",
        "background": "The application was filed in March 2026.",
        "present_date": "2026-05-18 13:45:18.630323",
        "date_cutoff_start": "2026-04-18 00:00:00",
        "date_cutoff_end": "2026-05-18 23:59:59",
        "expected_resolution_date": "2026-06-01 00:00:00",
        "resolution": 1.0,
        "resolution_explanation": "It was approved on May 30.",
        "sota_forecast_probability": 62.0,
        "sota_summary_rationale": "Filed early.",
    },
    {
        "question_id": "05a32e8a-b922-574c-904e-2dcaf0db962c",
        "question": "Will the {bill} pass by June 30, 2026?",
        "resolution_criteria": "Resolves YES on a final vote by June 30, 2026.",
        "background": "It left committee in May.",
        "present_date": "2026-05-02 09:00:00",
        "date_cutoff_start": "2026-04-02 00:00:00",
        "date_cutoff_end": "2026-05-02 23:59:59",
        "expected_resolution_date": "2026-06-30 00:00:00",
        "resolution": 0.0,
        "resolution_explanation": "No vote was held.",
        "sota_forecast_probability": None,
        "sota_summary_rationale": None,
    },
]


def _parquet(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path: Path = tmp_path / "btf3_binary_questions_and_forecasts.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _state(reply: str, target: str = "1") -> TaskState:
    return TaskState(
        metadata={"outcome": int(target)},
        model=ModelName("mockllm/model"),
        sample_id="q",
        epoch=1,
        input="prompt",
        messages=[],
        output=ModelOutput.from_content(model="mockllm/model", content=reply),
        target=Target(target),
    )


async def _score(reply: str, target: str = "1") -> Score:
    scorer = btf3.btf3_accuracy()
    score: Score | None = await scorer(_state(reply, target), Target(target))
    assert score is not None
    return score


# ── the Case ─────────────────────────────────────────────────────────────────────────────────


def test_the_pins_are_the_specs_commit_file_and_sha256() -> None:
    assert btf3.DATASET == "futuresearch-ai/BTF-3"
    assert btf3.DATASET_REVISION == "ad5a2165eea26a8a43592ba36ff15765199ddc71"
    assert btf3.DATASET_FILE == "btf3_binary_questions_and_forecasts.parquet"
    assert btf3.DATASET_SHA256 == (
        "50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b"
    )


#: Our answer line, the study's line (``bench_formats.BTF_TIGHT``) it replaces, and the A.1
#: closing line the study's line replaced.
_OURS: str = (
    "The last thing you write is your final answer as a probability between 0 and 1, on its "
    "own line in this format: `Final answer: <probability between 0 and 1>`. Do not write "
    "anything after that line.\n"
)
_TIGHT: str = (
    "End your response with exactly one line in this format: "
    "`Final answer: <number between 0 and 1>`. Do not write anything after that line.\n"
)
_A1_TAIL: str = "The last thing you write is your final answer as a probability between 0 and 1.\n"


def test_the_prompt_is_the_studys_prompt_with_the_answer_line_reworded() -> None:
    """INVARIANT: the template is the study's prompt as sent with only its answer line
    reworded to name the answer a probability (3,386 bytes; spec §12, contributor's decision
    2026-11-18). Everything above the answer line is the study's, byte for byte."""

    digest: str = hashlib.sha256(btf3.PROMPT_TEMPLATE.encode()).hexdigest()

    assert digest == "62f19370b5cdb491244ffbe5cb7e645f998630787bdcc399c9625c4e0a8e1c53"
    assert len(btf3.PROMPT_TEMPLATE.encode()) == 3386
    assert btf3.PROMPT_TEMPLATE.endswith(_OURS)
    assert "<research>\n</research>" in btf3.PROMPT_TEMPLATE
    assert "Today is {today}." in btf3.PROMPT_TEMPLATE


def test_swapping_the_study_line_back_gives_the_studys_prompt_as_sent() -> None:
    """Putting the study's answer line back must give ``bench_formats.btf_render(
    forecast_prompts.BTF, "tight")`` exactly (sha256 1b539749…), from which all 100 of the
    study's stored BTF-3 prompts re-render: only the answer line differs from the paper's runs."""

    as_sent: str = btf3.PROMPT_TEMPLATE.replace(_OURS, _TIGHT)

    assert hashlib.sha256(as_sent.encode()).hexdigest() == (
        "1b5397496e04fb7aa35c00c6214d127da6c827ef042b081a8c40c14aa0ac9d9e"
    )


def test_swapping_the_a1_line_back_gives_the_studys_stored_template() -> None:
    """The study stored ``forecast_prompts.BTF`` (sha256 1494ebd2…), ending on A.1's own line."""

    stored: str = btf3.PROMPT_TEMPLATE.replace(_OURS, _A1_TAIL)

    assert hashlib.sha256(stored.encode()).hexdigest() == (
        "1494ebd22daeb854d0eb63b90a1fa832f6622f2a17f1ce77a034368692504042"
    )


def test_the_prompt_is_the_shortened_copy_not_the_full_a1() -> None:
    """The study's copy drops A.1's worked examples (spec §3); serving the full A.1 instead
    would not replicate the paper's runs."""

    assert "Elon Musk" not in btf3.PROMPT_TEMPLATE
    assert "happen in the originally stated timeframe" in btf3.PROMPT_TEMPLATE


def test_a_row_becomes_the_filled_prompt_with_its_date_and_outcome() -> None:
    sample: Sample = btf3.record_to_sample(_ROWS[0])

    assert sample.id == _ROWS[0]["question_id"]
    assert sample.input == btf3.PROMPT_TEMPLATE.format(
        question=_ROWS[0]["question"],
        background=_ROWS[0]["background"],
        resolution_criteria=_ROWS[0]["resolution_criteria"],
        today="2026-05-18",
    )
    assert sample.target == "1"
    assert sample.metadata == {
        "outcome": 1,
        "present_date": "2026-05-18 13:45:18.630323",
        "expected_resolution_date": "2026-06-01 00:00:00",
        "sota_forecast_probability": 62.0,
    }


def test_braces_inside_a_row_are_served_as_written() -> None:
    sample: Sample = btf3.record_to_sample(_ROWS[1])

    assert "Will the {bill} pass by June 30, 2026?" in str(sample.input)
    assert sample.target == "0"


def test_a_wrong_sha256_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tampered: Path = _parquet(tmp_path, _ROWS)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(tampered))

    with pytest.raises(ValueError, match=f"expected {btf3.DATASET_SHA256}"):
        btf3.load_btf3()


def test_a_pinned_file_loads_in_file_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path: Path = _parquet(tmp_path, _ROWS)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(path))
    digest: str = hashlib.sha256(path.read_bytes()).hexdigest()

    dataset = btf3.load_btf3(sha256=digest)

    assert [str(sample.id) for sample in dataset] == [row["question_id"] for row in _ROWS]
    assert dataset.name == "btf3"


def test_a_duplicate_question_id_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path: Path = _parquet(tmp_path, [_ROWS[0], _ROWS[0]])
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(path))
    digest: str = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="two rows share the Case id"):
        btf3.load_btf3(sha256=digest)


# ── the reply reader (the study's btf_parse, verbatim) ───────────────────────────────────────


def test_the_vendored_reader_is_the_studys_excerpt_byte_for_byte() -> None:
    source: str = Path(study_btf_parse.__file__).read_text()
    excerpt: str = source.split("# --- verbatim below ---\n", 1)[1]

    assert hashlib.sha256(excerpt.encode()).hexdigest() == (
        "0e263b1c9c365d273b3b3bd7a3703058e0650e4b2897439ff756c49687ff8165"
    )


@pytest.mark.parametrize(
    ("reply", "forecast", "compliant", "source"),
    [
        ("Reasoning...\n0.35", 0.35, True, "final_line"),
        ("Reasoning...\nFinal answer: .35", 0.35, True, "final_line"),
        ("Reasoning...\nmy estimate is *0.35*", 0.35, True, "final_line"),
        ("Reasoning...\n1.0.", 1.0, True, "final_line"),
        ("Reasoning...\n0", 0.0, True, "final_line"),
        # The study's quirk, kept: mid-reply, a number directly followed by "." is not read
        # (``_NUM`` refuses a trailing "." to avoid splitting "0.85"), so this reply has none.
        ("My answer is 0.8. But note this is uncertain.", None, False, None),
        ("My answer is 0.8 but note this is uncertain.", 0.8, False, "number_not_final"),
        ("a 0.7 chance of Y.\nI cannot give a final figure.", 0.7, False, "number_not_final"),
        ("I put it at 65%.", None, False, None),
        # The reader's other side: a percentage's digits are never read, but a stray 1 is.
        ("About 1 month remains.\nFinal answer: 65%", 1.0, False, "number_not_final"),
        ("I will not forecast this.", None, False, None),
        ("", None, False, None),
        # The reader knows only plain decimals from 0 to 1 (kept as the study wrote it): a sign
        # is ignored, and an exponent, a decimal comma or a fraction is read by a lone digit.
        ("Final answer: -0.8", 0.8, True, "final_line"),
        ("Final answer: 1e-2", 1.0, False, "number_not_final"),
        ("Final answer: 0,35", 0.0, False, "number_not_final"),
        ("Final answer: 1/3", 1.0, False, "number_not_final"),
        # A later line wins over the answer line: the reader takes the LAST line.
        ("Final answer: 0.9\n\nP(No) = 0.1", 0.1, True, "final_line"),
        # A reply cut off before its answer line: a lone 1 in the reasoning becomes the forecast.
        (
            "(a) 1 month left.\n(b) The status quo is No.\nSo the probability is abou",
            1.0,
            False,
            "number_not_final",
        ),
    ],
)
def test_the_reader_follows_the_studys_three_rules(
    reply: str, forecast: float | None, compliant: bool, source: str | None
) -> None:
    reading: btf3.Reading = btf3.read_forecast(reply)

    assert (reading.forecast, reading.compliant, reading.source) == (forecast, compliant, source)


# ── the mark and the headline ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_forecast_scores_accuracy_at_one_half_with_its_brier_beside() -> None:
    yes: Score = await _score("Reasoning.\nFinal answer: 0.8", "1")
    no: Score = await _score("Reasoning.\nFinal answer: 0.8", "0")

    assert yes.value == 1.0
    assert no.value == 0.0
    assert no.metadata == {
        "forecast": 0.8,
        "outcome": 0,
        "brier": pytest.approx(0.64),
        "compliant": True,
        "source": "final_line",
    }
    assert no.answer == "0.8"


@pytest.mark.asyncio
async def test_exactly_one_half_reads_yes() -> None:
    """The study's ``THRESHOLD``: a probability of exactly 0.5 counts as Yes."""

    assert (await _score("Final answer: 0.5", "1")).value == 1.0
    assert (await _score("Final answer: 0.5", "0")).value == 0.0
    assert (await _score("Final answer: 0.49", "0")).value == 1.0


@pytest.mark.asyncio
async def test_a_reply_with_no_forecast_is_a_miss_costing_brier_one_quarter() -> None:
    """The study's crowd abstain rule (``committee_kit/metrics.py``): no forecast reads as 0.5 for
    Brier (0.25 either way) and as a miss for accuracy, as issue #1868 asks (F1)."""

    score: Score = await _score("I put it at 65%.", "1")

    assert score.value == 0.0
    assert score.metadata == {
        "forecast": None,
        "outcome": 1,
        "brier": 0.25,
        "compliant": False,
        "source": None,
    }


@pytest.mark.asyncio
async def test_a_case_without_its_outcome_fails_loudly() -> None:
    state: TaskState = _state("Reasoning.\n0.8")
    state.metadata = {}

    with pytest.raises(KeyError, match="outcome"):
        await btf3.btf3_accuracy()(state, Target("1"))


@pytest.mark.parametrize("outcome", [0.5, 0.9, 2, "1"])
def test_an_outcome_that_is_not_0_or_1_is_refused_before_it_is_rounded(outcome: object) -> None:
    """INVARIANT: the 0/1 check runs before ``int()``. WHY: ``int(0.5)`` is 0, so a Case whose
    outcome is not a resolution would otherwise be graded as "resolved No" with no error."""

    state: TaskState = _state("Reasoning.\n0.8")
    state.metadata = {"outcome": outcome}

    with pytest.raises(ValueError, match="outcome must be 0 or 1"):
        btf3.case_outcome(state)


def _sample(value: float, forecast: float | None, brier: float, **extra: Any) -> SampleScore:
    return SampleScore(
        score=Score(value=value, metadata={"forecast": forecast, "brier": brier, **extra}),
        sample_id="q",
    )


def _headline(scores: list[SampleScore]) -> dict[str, Any]:
    """The row's whole-run metric over ``scores``. WHY ``Any``: inspect's ``Metric`` alias
    types its argument as ``list[Score]``, though the Engine hands it ``SampleScore``s."""

    compute: Any = btf3.btf3_headline()
    return compute(scores)


def test_the_headline_is_accuracy_over_every_case_with_brier_and_counts() -> None:
    scores: list[SampleScore] = [
        _sample(1.0, 0.8, 0.04, compliant=True),
        _sample(0.0, 0.8, 0.64, compliant=False),
        _sample(0.0, None, 0.25),
        _sample(1.0, 0.1, 0.01, compliant=True),
    ]

    assert _headline(scores) == {
        "accuracy": pytest.approx(2 / 4),
        "brier": pytest.approx((0.04 + 0.64 + 0.25 + 0.01) / 4),
        "forecasts": 3,
        "no_forecast": 1,
        "compliant": 2,
    }


def test_a_bare_abstain_score_is_a_miss_costing_brier_one_quarter() -> None:
    """The Engine's ``zero_sample_score`` files a bare 0.0 with only ``candidate_abstained``
    (no reader metadata) when grading filed no Score: a miss, Brier 0.25, no forecast."""

    abstain: SampleScore = SampleScore(
        score=Score(value=0.0, metadata={"candidate_abstained": True}), sample_id="q"
    )

    assert _headline([_sample(1.0, 0.8, 0.04, compliant=True), abstain]) == {
        "accuracy": pytest.approx(0.5),
        "brier": pytest.approx((0.04 + 0.25) / 2),
        "forecasts": 1,
        "no_forecast": 1,
        "compliant": 1,
    }


def test_an_empty_run_heads_zero() -> None:
    assert _headline([])["accuracy"] == 0.0


def test_the_row_names_accuracy_as_its_headline() -> None:
    from screamingface_engine_inspect.benchmarks import BENCHMARKS

    [row] = [spec for spec in BENCHMARKS if spec.key == "btf3"]

    assert row.whole_run_metric is not None
    assert row.whole_run_metric.endswith("btf3:btf3_headline")
    assert row.whole_run_headline == "accuracy"


def test_a_resolution_other_than_0_or_1_is_refused() -> None:
    with pytest.raises(ValueError, match="resolution 0.5 is not 0 or 1"):
        btf3.record_to_sample({**_ROWS[0], "resolution": 0.5})


@pytest.mark.asyncio
async def test_through_the_engine_the_report_shows_the_cases_left_out(
    tmp_path: Path, no_network: None
) -> None:
    """End to end over the production aggregate route: a forecast of 0.8 on a Yes question and
    a reply with no number → accuracy 0.5, Brier (0.04 + 0.25) / 2, one Case with no forecast."""

    import json

    from test_whole_run_metric import _row

    from screamingface_engine_inspect.benchmarks import imported_benchmark
    from screamingface_engine_inspect.prepare import (
        TASK_REPLAY_CASES,
        PreparedCase,
        _write_cases,  # pyright: ignore[reportPrivateUsage]
        prepared_case,
    )
    from screamingface_engine_inspect.single_shot import benchmark_aggregate_async

    prepared: list[PreparedCase] = []
    for case_id in (1, 2):
        sample: Sample = btf3.record_to_sample({**_ROWS[0], "question_id": f"q{case_id}"})
        case = prepared_case(sample, case_id, str(sample.input), TASK_REPLAY_CASES["btf3"])
        prepared.append(json.loads(json.dumps(case)))
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [_row(1, "Reasoning.\nFinal answer: 0.8"), _row(2, "I will not forecast this.")]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("btf3"), rows, tmp_path, case_ids=(1, 2)
    )

    assert result["score"] == 0.5
    assert result["metrics"]["brier"] == pytest.approx(0.145)
    assert result["metrics"]["forecasts"] == 1
    assert result["metrics"]["no_forecast"] == 1
    assert result["metrics"]["compliant"] == 1


def test_the_task_generates_once_under_one_scorer_and_the_headline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util.registry import registry_info

    one: Sample = btf3.record_to_sample(_ROWS[0])
    monkeypatch.setattr(btf3, "load_btf3", lambda **_kwargs: [one])

    task = btf3.btf3()

    [scorer] = task.scorer or []
    assert registry_info(scorer).name.endswith("btf3_accuracy")
    assert [registry_info(m).name for m in task.metrics or []] == [
        registry_info(btf3.btf3_headline()).name
    ]
