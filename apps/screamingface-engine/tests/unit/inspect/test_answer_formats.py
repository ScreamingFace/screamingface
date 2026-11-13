# pyright: reportMissingImports=false
# WHY file-level: grading runs through inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""Every Benchmark page states the answer format its grader reads, and the statement is true.

FEATURE: answer format on the Benchmark page (OME-1906). A submitter whose model wrote
`ANSWER: $C` paid for a full MMLU-Pro run in which inspect's parser read 68 of 200 replies as
no answer (OME-1886). The grader stays as inspect wrote it; the page now says what it reads, so
a 20-Case smoke run can be checked before the whole Benchmark is paid for.

STORY: as a submitter, I read on the Benchmark page that the reply must end `ANSWER: B`, see
that my 20-Case smoke run wrote `ANSWER: $B`, and fix my pipeline before the full run.

What these tests pin, and why:

- a row with an answer format publishes its hand-written prose followed by its sentence;
- every reply a sentence quotes is graded the way the sentence says, through each row's real
  grader with no network, so the page cannot promise a format the grader refuses;
- a judge-graded answer format quotes no graded replies (grading them is a paid judge call)
  and says a judge reads the reply; a row has a judge exactly when its answer format is
  judge-graded;
- a row with no answer format publishes its prose unchanged;
- the description is not part of the revision: the fingerprint tests stay green untouched.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inspect_task_replay_benchmarks import _node, _scores  # noqa: E402

from screamingface_engine_inspect.answer_formats import (  # noqa: E402
    ANSWER_FORMATS,
    AnswerFormat,
    answer_format_for,
    with_answer_format,
)
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    ImportedBenchmark,
    imported_benchmark,
)
from screamingface_engine_inspect.prepare import PreparedCase  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_CHOICE: str = "inspect_ai.scorer:choice"
_FORMATTED_ROWS: list[BenchmarkSpec] = [
    spec for spec in BENCHMARKS if answer_format_for(spec.key, spec.scorer) is not None
]


def _answer_format(spec: BenchmarkSpec) -> AnswerFormat:
    """The answer format a row with one publishes."""

    answer_format: AnswerFormat | None = answer_format_for(spec.key, spec.scorer)
    assert answer_format is not None, spec.key
    return answer_format


def _stand_in_cases(answer_format: AnswerFormat, count: int) -> list[PreparedCase]:
    """`count` copies of the answer format's stand-in Case, one per example reply.

    WHY a stand-in: the real Cases need the network to fetch; the answer format is the grader's,
    not the question's, so any Case with its Grading Material proves it."""

    assert answer_format.material is not None
    return [
        {
            "case": {"id": index, "case_id": str(index), "input": answer_format.case_input},
            "grading_material": dict(answer_format.material),
        }
        for index in range(1, count + 1)
    ]


def test_the_choice_answer_format_serves_the_thirty_five_choice_rows() -> None:
    assert sum(1 for spec in BENCHMARKS if spec.scorer == _CHOICE) == 35
    assert all(
        _answer_format(spec) is ANSWER_FORMATS[_CHOICE]
        for spec in BENCHMARKS
        if spec.scorer == _CHOICE
    )


@pytest.mark.parametrize("spec", _FORMATTED_ROWS, ids=lambda spec: spec.key)
def test_a_row_with_an_answer_format_publishes_its_prose_then_the_sentence(
    spec: BenchmarkSpec,
) -> None:
    published: str = imported_benchmark(spec.key).benchmark.description

    assert published == f"{spec.description} {_answer_format(spec).sentence}"


def test_a_row_with_no_answer_format_publishes_its_prose_unchanged() -> None:
    assert with_answer_format("Prose.", "no_such_row", "no.such:scorer") == "Prose."


def test_every_example_reply_is_quoted_in_its_sentence() -> None:
    """INVARIANT: the replies under test are exactly what the submitter reads."""

    for answer_format in ANSWER_FORMATS.values():
        for example in (*answer_format.accepted, *answer_format.rejected):
            assert f"'{example}'" in answer_format.sentence


def test_an_answer_format_either_names_a_judge_or_proves_itself_with_replies() -> None:
    for name, answer_format in ANSWER_FORMATS.items():
        if answer_format.judged:
            assert not answer_format.accepted and not answer_format.rejected, name
            assert "judge" in answer_format.sentence, name
        else:
            assert answer_format.accepted and answer_format.rejected, name


@pytest.mark.parametrize("spec", _FORMATTED_ROWS, ids=lambda spec: spec.key)
def test_a_row_has_a_judge_exactly_when_its_answer_format_is_judge_graded(
    spec: BenchmarkSpec,
) -> None:
    assert (spec.judge is not None) == _answer_format(spec).judged


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec",
    [spec for spec in _FORMATTED_ROWS if not _answer_format(spec).judged],
    ids=lambda spec: spec.key,
)
async def test_each_quoted_reply_grades_as_the_sentence_says(
    spec: BenchmarkSpec, tmp_path: Path, no_network: None
) -> None:
    """Accepted replies score 1 on the stand-in Case; rejected ones score 0."""

    answer_format: AnswerFormat = _answer_format(spec)
    replies: list[str] = [*answer_format.accepted, *answer_format.rejected]
    benchmark: ImportedBenchmark = imported_benchmark(spec.key)
    node: Url4Node = _node(benchmark, _stand_in_cases(answer_format, len(replies)), tmp_path)

    assert await _scores(node, benchmark, replies) == [
        *([1.0] * len(answer_format.accepted)),
        *([0.0] * len(answer_format.rejected)),
    ]
