# pyright: reportMissingImports=false
# WHY file-level: grading runs through inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""Every Benchmark page states the answer format its grader reads, and the statement is true.

FEATURE: answer format on the Benchmark page. A submitter whose model wrote `ANSWER: $C` paid
for a full MMLU-Pro run in which inspect's parser read 68 of 200 replies as no answer
(OME-1886). The grader stays as inspect wrote it; the page now says what it reads, so a
20-Case smoke run can be checked before the whole Benchmark is paid for.

STORY: as a submitter, I read on the Benchmark page that the reply must end `ANSWER: B`, see
that my 20-Case smoke run wrote `ANSWER: $B`, and fix my pipeline before the full run.

What these tests pin, and why:

- a row's published description is its hand-written prose followed by its scorer's sentence;
- every reply the sentence quotes is graded the way the sentence says, through each row's
  real grader with no network, so the page cannot promise a format the grader refuses;
- a row whose scorer has no sentence yet publishes its prose unchanged (PR 1 of 2 covers
  inspect's `choice`; PR 2 the rest);
- the description is not part of the revision: the fingerprint tests stay green untouched.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inspect_task_replay_benchmarks import _node, _scores  # noqa: E402

from screamingface_engine_inspect.answer_formats import ANSWER_FORMATS, AnswerFormat  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    ImportedBenchmark,
    imported_benchmark,
)
from screamingface_engine_inspect.prepare import PreparedCase  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_CHOICE: str = "inspect_ai.scorer:choice"
_CHOICE_ROWS: list[BenchmarkSpec] = [spec for spec in BENCHMARKS if spec.scorer == _CHOICE]


def _stand_in_cases(answer_format: AnswerFormat, count: int) -> list[PreparedCase]:
    """`count` copies of one two-option Case whose key is the one the examples are written for.

    WHY a stand-in: the real Cases need the network to fetch; the format rule is the scorer's,
    not the question's, so any Case with that key proves it."""

    return [
        {
            "case": {
                "id": index,
                "case_id": str(index),
                "input": "Which seat is free?\n\nA) 1\nB) 2",
            },
            "grading_material": {"target": answer_format.key, "choices": ["1", "2"]},
        }
        for index in range(1, count + 1)
    ]


def test_the_choice_rows_are_the_thirty_five_this_pr_covers() -> None:
    assert len(_CHOICE_ROWS) == 35


@pytest.mark.parametrize("spec", _CHOICE_ROWS, ids=lambda spec: spec.key)
def test_a_choice_row_publishes_its_prose_then_the_answer_format(spec: BenchmarkSpec) -> None:
    published: str = imported_benchmark(spec.key).benchmark.description

    assert published == f"{spec.description} {ANSWER_FORMATS[_CHOICE].sentence}"


def test_every_example_reply_is_quoted_in_the_sentence_the_page_shows() -> None:
    """INVARIANT: the examples under test are exactly what the submitter reads."""

    for answer_format in ANSWER_FORMATS.values():
        for example in (*answer_format.accepted, *answer_format.rejected):
            assert f"'{example}'" in answer_format.sentence


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", _CHOICE_ROWS, ids=lambda spec: spec.key)
async def test_each_quoted_reply_grades_as_the_sentence_says(
    spec: BenchmarkSpec, tmp_path: Path, no_network: None
) -> None:
    """Accepted replies score 1 on their key; rejected ones are read as no answer and score 0."""

    answer_format: AnswerFormat = ANSWER_FORMATS[spec.scorer]
    replies: list[str] = [*answer_format.accepted, *answer_format.rejected]
    benchmark: ImportedBenchmark = imported_benchmark(spec.key)
    node: Url4Node = _node(benchmark, _stand_in_cases(answer_format, len(replies)), tmp_path)

    assert await _scores(node, benchmark, replies) == [
        *([1.0] * len(answer_format.accepted)),
        *([0.0] * len(answer_format.rejected)),
    ]


def test_a_row_whose_scorer_has_no_sentence_yet_publishes_its_prose_unchanged() -> None:
    """paws grades with our bare Yes/No scorer, which PR 2 of 2 describes."""

    paws: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "paws")

    assert paws.scorer not in ANSWER_FORMATS
    assert imported_benchmark("paws").benchmark.description == paws.description
