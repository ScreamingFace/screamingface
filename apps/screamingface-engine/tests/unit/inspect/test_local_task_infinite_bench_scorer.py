# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""InfiniteBench Math.Find graded by the official first-number rule: inspect_evals PR #2346.

What these tests pin, and why:

- the reply's FIRST number, compared by value, decides: a right number wrapped in words is right,
  a hedge that names a wrong number first is wrong, a reply with no number is a format failure;
- the TRIPWIRE: inspect_evals' own Task still grades with a scorer (inspect's `exact()` at
  v0.20.0) that marks a wrapped right number wrong; when a pin bump makes that assert fail,
  inspect_evals has the fix (https://github.com/UKGovernmentBEIS/inspect_evals/pull/2346)
  and the Named Deviation can go;
- the official pattern is copied as is: decimals before integers, no sign;
- the local Task and its row both grade with this scorer.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai._util.registry import registry_info  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.infinite_bench import (  # noqa: E402
    infinite_bench as inspect_evals_infinite_bench,
)

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.local_tasks.infinite_bench import (  # noqa: E402
    infinite_bench as local,
)
from screamingface_engine_inspect.local_tasks.infinite_bench.infinite_bench import (  # noqa: E402
    first_number,
    infinite_bench_math_find,
    math_find_scorer,
)

#: A one-Sample stand-in dataset, so either Task builds without the Hub.
_STAND_IN = MemoryDataset([Sample(input="Find the largest number.", target="91")])


async def _scored(scorer: Scorer, reply: str, key: str) -> Score:
    """The Score one scorer gives one reply against one answer."""

    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply),
    )
    score: Score | None = await scorer(state, Target(key))
    assert score is not None
    return score


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["The largest number in the list is: 91", "The median is 91.0."])
async def test_tripwire_a_right_number_in_words_inspect_evals_fails_is_right_under_ours(
    reply: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRIPWIRE (inspect_evals PR #2346): the first assert is the verdict of the scorer
    inspect_evals' Task declares at the pinned version."""

    monkeypatch.setattr(inspect_evals_infinite_bench, "hf_dataset", lambda **_kwargs: _STAND_IN)
    inspect_evals_scorers: list[Scorer] = list(
        inspect_evals_infinite_bench.infinite_bench_math_find().scorer or []
    )

    assert (await _scored(inspect_evals_scorers[0], reply, "91")).value == INCORRECT
    assert (await _scored(math_find_scorer(), reply, "91")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["Either 90 or 91.", "92", "9.1"])
async def test_only_the_first_number_counts_and_it_must_equal_the_answer(reply: str) -> None:
    assert (await _scored(math_find_scorer(), reply, "91")).value == INCORRECT


@pytest.mark.asyncio
async def test_a_reply_with_no_number_is_a_format_failure() -> None:
    score: Score = await _scored(math_find_scorer(), "I could not find it.", "91")

    assert (score.value, score.reason) == (INCORRECT, "invalid_response_format")


@pytest.mark.parametrize(
    ("reply", "number"),
    [("3.5 then 4", "3.5"), ("about -5", "5"), ("x7y", "7"), ("none", None)],
)
def test_the_official_pattern_reads_decimals_first_and_no_sign(
    reply: str, number: str | None
) -> None:
    assert first_number(reply) == number


def test_the_task_and_its_row_grade_with_the_first_number_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The local Task declares the scorer its row grades with."""

    monkeypatch.setattr(local, "hf_dataset", lambda **_kwargs: _STAND_IN)
    row = next(spec for spec in BENCHMARKS if spec.key == "infinite_bench_math_find")

    assert [registry_info(scorer).name for scorer in infinite_bench_math_find().scorer or []] == [
        "math_find_scorer"
    ]
    assert row.scorer.endswith("local_tasks.infinite_bench.infinite_bench:math_find_scorer")
