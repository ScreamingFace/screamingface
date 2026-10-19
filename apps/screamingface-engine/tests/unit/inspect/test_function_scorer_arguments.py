# pyright: reportMissingImports=false
# WHY file-level: drop's scorer imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""A scorer argument that is a function, carried by reference (OME-1602, PR 6).

drop hands inspect's ``f1`` its own ``extract_answer``, which reads the reply's "Answer:"
line. inspect logs that argument as the string ``'extract_answer'``, so before this PR the
importer refused drop (F1). The row now names the function as ``module:attribute`` in its own
field, and grading imports it. What these tests pin, and why:

- grading reads the "Answer:" line through the eval's own function, so a reasoned reply
  scores on its answer, not on every word it wrote;
- assembly refuses a reference spelled wrong, one outside the eval's own package, and a name
  given both as a literal and as a function, without importing anything;
- the reference is Benchmark identity: pointing it elsewhere moves the revision, and rows
  without one keep theirs.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    imported_benchmark,
)
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    prepared_case,
)

_DROP: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "drop")


async def _grade_drop(reply: str, answers: list[str]) -> CaseGradeOutcome:
    """Grade one reply on drop's real per-Case hook."""

    sample = Sample(id="q1", input="How many touchdowns were scored?", target=answers)
    case: PreparedCase = prepared_case(sample, 1, str(sample.input), TASK_REPLAY_CASES["drop"])
    material: Any = json.loads(json.dumps(case["grading_material"]))
    hook = imported_benchmark("drop").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=1,
            input=TextPayload(text=str(sample.input)),
            answer=TextPayload(text=reply),
            row={"case": {"status": "answered"}},
            material=material,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "score"),
    [
        ("Two in the first half, one in the second, so three in all.\nAnswer: 3", 1.0),
        ("Counting them, I get four.\nAnswer: 4", 0.0),
    ],
)
async def test_drop_grades_the_answer_line_through_the_evals_own_reader(
    reply: str, score: float
) -> None:
    """INVARIANT: the reasoning before "Answer:" is not graded. Without the eval's reader,
    inspect's f1 would compare the whole reply with "3" and score the right answer near 0."""

    outcome: CaseGradeOutcome = await _grade_drop(reply, ["3", "three"])

    assert (outcome.score, outcome.failure_code) == (score, None)


def test_the_drop_row_names_the_evals_reader_and_no_literal_stands_in_for_it() -> None:
    assert dict(_DROP.scorer_function_kwargs) == {
        "answer_fn": "inspect_evals.drop.drop:extract_answer"
    }
    assert "answer_fn" not in _DROP.scorer_kwargs


@pytest.mark.parametrize(
    ("functions", "literals", "reason"),
    [
        ({"answer_fn": "inspect_evals.drop.drop.extract_answer"}, {}, "not a module:attribute"),
        ({"answer_fn": "os:system"}, {}, "outside the eval's own package"),
        # Another eval's function shares the top-level inspect_evals package, but not drop's.
        (
            {"answer_fn": "inspect_evals.gsm8k.gsm8k:record_to_sample"},
            {},
            "outside the eval's own package",
        ),
        (
            {"answer_fn": "inspect_evals.drop.drop:extract_answer"},
            {"answer_fn": "extract_answer"},
            "both a literal and a function",
        ),
    ],
)
def test_assembly_refuses_a_function_argument_it_could_not_name_safely(
    functions: dict[str, str], literals: dict[str, Any], reason: str
) -> None:
    """Checked by spelling at assembly, before any Case is served: the Engine imports a row's
    references only when it grades, so a row may name only the eval's own functions."""

    spec: BenchmarkSpec = replace(_DROP, scorer_function_kwargs=functions, scorer_kwargs=literals)

    with pytest.raises(ValueError, match=reason):
        benchmarks._check_scorer_function_kwargs(spec)


def test_the_reference_is_benchmark_identity_and_absent_rows_keep_their_revision() -> None:
    elsewhere: BenchmarkSpec = replace(
        _DROP, scorer_function_kwargs={"answer_fn": "inspect_evals.drop.drop:format_input"}
    )

    assert benchmarks._scorer_function_pins(_DROP) != benchmarks._scorer_function_pins(elsewhere)
    assert all(
        benchmarks._scorer_function_pins(spec) == ()
        for spec in BENCHMARKS
        if not spec.scorer_function_kwargs
    )
