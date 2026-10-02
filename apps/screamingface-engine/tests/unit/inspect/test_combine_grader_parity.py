"""The combine reads a numeric answer the way Inspect's own grader does (OME-1289, E4a, unit 2).

FEATURE: two members whose answers Inspect would grade equal land in one tally row.
STORY: as an author of a GSM8K or AIME Candidate, the combine and the grader agree on what counts
as the same number. GP#1 to GP#6 of the E4a gap-closure; the oracle is the real
``inspect_ai.scorer.match(numeric=True)`` (and ``aime_scorer``), run on a ``TaskState`` the way
``screamingface_engine_inspect/scorer_adapter.py`` builds one.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest ...`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, Score, Target, match  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS  # noqa: E402
from screamingface_engine.combine.ports import OpArgs, Stage, StageResult  # noqa: E402


def _stage(op_id: str, stage_name: Stage, text: str, args: OpArgs | None = None) -> StageResult:
    """Run one built-in extract or normalize operator (the Inspect lane has no shared test
    support: ``tests/unit`` is not on its import path)."""
    run = BUILTIN_OPERATORS.resolve(op_id, stage_name).run
    return run(text, {} if args is None else args)  # type: ignore[call-arg, return-value]


@pytest.fixture(scope="module")
def runner() -> Iterator[asyncio.Runner]:
    """One event loop for every row (a loop per row would dominate the corpus runs)."""
    with asyncio.Runner() as loop_runner:
        yield loop_runner


def _state(text: str) -> TaskState:
    return TaskState(
        model="m",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[ChatMessageUser(content="q")],
        output=ModelOutput.from_content(model="m", content=text),
    )


def _inspect_score(
    runner: asyncio.Runner, scorer: Callable[..., Any], text: str, target: str
) -> Score:
    score = runner.run(scorer(_state(text), Target(target)))
    assert isinstance(score, Score)
    return score


def _builtin_equal(text: str, target: str) -> bool:
    """What the v1 built-ins say: numeric@1 of last_number@1 against numeric@1 of the target."""
    reply = _stage("last_number@1", "extract", text)
    wanted = _stage("numeric@1", "normalize", target)
    if reply.value is None or wanted.value is None:
        return False
    return _stage("numeric@1", "normalize", reply.value).value == wanted.value


@pytest.mark.parametrize(
    ("text", "target"), [("x=42", "42"), ("123457", "123456"), ("1,23", "123")]
)
def test_builtin_last_number_and_numeric_disagree_with_inspect(
    runner: asyncio.Runner, text: str, target: str
) -> None:
    # GP#1 CHAR: the v1 built-ins and Inspect differ on these rows by design; the Inspect-rule
    # operators close the gap (rows below), and the v1 operators never change.
    score = _inspect_score(runner, match(numeric=True), text, target)
    assert (score.value == CORRECT) != _builtin_equal(text, target)
