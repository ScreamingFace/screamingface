# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Capture rendering: a Task-replay Case is what inspect's own solver chain sends the model
at its first ``generate`` (spec R2, R9).

INVARIANT: the rendered input is byte for byte what the eval's real solvers produce; our code
never imitates a solver. INVARIANT: capture never calls a model: the stand-in ``generate``
records the messages and answers nothing, and a chain that needs more than one answer, tools
or a sandbox is refused by name instead of approximated.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from random import Random

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser  # noqa: E402
from inspect_ai.solver import (  # noqa: E402
    Generate,
    Solver,
    TaskState,
    generate,
    multiple_choice,
    prompt_template,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.tool import tool  # noqa: E402

from screamingface_engine_inspect.capture import CaptureError, captured_case_records  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay import replayed_cases  # noqa: E402

#: A stand-in for an eval's own instruction template (sevenllm's TEMPLATE shape).
TEMPLATE: str = "You are a security analyst. {prompt}"

#: The one Sample every stand-in task below serves.
PORT_SAMPLE: Sample = Sample(
    input="Which port serves HTTPS?", choices=["21", "443", "80", "22"], target="B", id=1
)

#: What inspect's ``prompt_template(TEMPLATE)`` then ``multiple_choice()`` sends the model for
#: PORT_SAMPLE — written by hand from inspect 0.3.263's SINGLE_ANSWER template, never
#: computed by our code, so the test can only pass if capture reproduces inspect exactly.
EXPECTED_CHAINED_INPUT: str = (
    "Answer the following multiple choice question. The entire content of your response "
    "should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is "
    "one of A,B,C,D.\n\n"
    "You are a security analyst. Which port serves HTTPS?\n\n"
    "A) 21\nB) 443\nC) 80\nD) 22"
)

_UNSEALED: str = "0" * 64


def _spec(**overrides: object) -> TaskReplayCasesSpec:
    """A declaration whose seal nothing compares; capture reads only its writer options."""

    fields: dict[str, object] = {"task": "stand_in:task", "case_count": 1, "case_digest": _UNSEALED}
    fields.update(overrides)
    return TaskReplayCasesSpec(**fields)  # type: ignore[arg-type]


def _one_sample_task(solver_chain: list[Solver] | None = None, **task_kwargs: object) -> Task:
    """A Task over PORT_SAMPLE with the given chain (None → inspect's default generate())."""

    dataset = MemoryDataset([PORT_SAMPLE])
    if solver_chain is None:
        return Task(dataset=dataset, **task_kwargs)  # type: ignore[arg-type]
    return Task(dataset=dataset, solver=solver_chain, **task_kwargs)  # type: ignore[arg-type]


# ── what capture produces ────────────────────────────────────────────────────


def test_a_chained_template_and_multiple_choice_renders_as_inspect_does() -> None:
    """The sevenllm shape: both solvers' work lands in the Case, in inspect's own bytes."""

    task = _one_sample_task([prompt_template(TEMPLATE), multiple_choice()])

    prepared = captured_case_records(task, _spec())

    assert prepared == [
        {
            "case": {"id": 1, "case_id": "1", "input": EXPECTED_CHAINED_INPUT},
            "grading_material": {"target": "B", "choices": ["21", "443", "80", "22"]},
        }
    ]


def test_a_system_message_leads_the_input_text() -> None:
    """Named deviation kept: a Benchmark cannot address the Candidate's system role, so the
    eval's system message becomes the input's leading text."""

    task = _one_sample_task([system_message("Answer tersely."), generate()])

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "Answer tersely.\n\nWhich port serves HTTPS?"


def test_a_template_reads_the_samples_metadata() -> None:
    """A field the imitation writer never saw: inspect fills template params from metadata."""

    sample = Sample(input="Which port serves HTTPS?", target="443", metadata={"domain": "web"})
    task = Task(
        dataset=MemoryDataset([sample]),
        solver=[prompt_template("[{domain}] {prompt}"), generate()],
    )

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "[web] Which port serves HTTPS?"


def test_the_tasks_setup_runs_before_its_solver() -> None:
    task = _one_sample_task(
        [prompt_template("second: {prompt}"), generate()],
        setup=prompt_template("first: {prompt}"),
    )

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "second: first: Which port serves HTTPS?"


def test_a_task_with_no_solver_serves_the_raw_input() -> None:
    """inspect's default solver is generate(): the input reaches the model untouched."""

    sample = Sample(input="What is 6 times 7?", target="42")
    task = Task(dataset=MemoryDataset([sample]))

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "What is 6 times 7?"
    assert prepared[0]["grading_material"] == {"target": "42"}


def test_kept_metadata_rides_the_grading_material() -> None:
    sample = Sample(input="Which port serves HTTPS?", target="443", metadata={"domain": "web"})
    task = Task(dataset=MemoryDataset([sample]))

    prepared = captured_case_records(task, _spec(keep_sample_metadata=True))

    assert prepared[0]["grading_material"] == {"target": "443", "metadata": {"domain": "web"}}


# ── what capture refuses, each by name and Case number ───────────────────────


@solver
def _never_generates() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


@solver
def _generates_twice() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        return await generate(state)

    return solve


@solver
def _shuffles_then_asks() -> Solver:
    # WHY the deprecated argument: it is the one inspect solver that reorders choices after
    # the dataset is read, which is the shape capture must refuse.
    return multiple_choice(shuffle=Random(7))


@solver
def _raises() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        raise KeyError("subject")

    return solve


@tool
def _calculator():  # type: ignore[no-untyped-def]
    async def execute(expression: str) -> str:
        """Evaluate an arithmetic expression.

        Args:
            expression: the arithmetic to evaluate.
        """
        return expression

    return execute


def test_a_solver_that_never_asks_the_model_is_refused() -> None:
    task = _one_sample_task([_never_generates()])

    with pytest.raises(CaptureError, match="case 1: the solver never called generate"):
        captured_case_records(task, _spec())


def test_a_solver_that_asks_twice_is_refused() -> None:
    """A second answer would be graded; the Candidate answers once."""

    task = _one_sample_task([_generates_twice()])

    with pytest.raises(CaptureError, match="case 1: the solver called generate twice"):
        captured_case_records(task, _spec())


def test_a_solver_that_hands_the_model_tools_is_refused() -> None:
    task = _one_sample_task([use_tools(_calculator()), generate()])

    with pytest.raises(CaptureError, match="case 1: the solver gave the model 1 tool"):
        captured_case_records(task, _spec())


def test_a_task_with_a_sandbox_is_refused_before_any_sample_runs() -> None:
    task = _one_sample_task(sandbox="docker")

    with pytest.raises(CaptureError, match="declares a sandbox"):
        captured_case_records(task, _spec())


def test_a_multi_turn_prompt_is_refused() -> None:
    """A Case is one text for the Candidate; a conversation with an assistant turn is not."""

    sample = Sample(
        input=[
            ChatMessageUser(content="What is 2 plus 2?"),
            ChatMessageAssistant(content="4"),
            ChatMessageUser(content="And 6 times 7?"),
        ],
        target="42",
    )
    task = Task(dataset=MemoryDataset([sample]))

    with pytest.raises(CaptureError, match="case 1: .*3 messages.*assistant"):
        captured_case_records(task, _spec())


def test_a_solver_that_reorders_the_choices_is_refused() -> None:
    """The Grading Material holds the Sample's order; a Case shown in another order would be
    graded against the wrong letters."""

    task = _one_sample_task([_shuffles_then_asks()])

    with pytest.raises(CaptureError, match="case 1: the solver reordered the choices"):
        captured_case_records(task, _spec())


def test_a_solver_that_raises_is_refused_with_its_error() -> None:
    task = _one_sample_task([_raises()])

    with pytest.raises(CaptureError, match="case 1: the solver raised KeyError: 'subject'"):
        captured_case_records(task, _spec())


# ── the image-side child captures too ────────────────────────────────────────

#: The sevenllm shape as a stand-in eval the child process can import.
CHAINED_EVAL: str = textwrap.dedent(
    f"""
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.solver import multiple_choice, prompt_template

    TEMPLATE = {TEMPLATE!r}

    @task
    def chained() -> Task:
        sample = Sample(input="Which port serves HTTPS?", choices=["21", "443", "80", "22"],
                        target="B", id=1)
        return Task(dataset=MemoryDataset([sample]),
                    solver=[prompt_template(TEMPLATE), multiple_choice()])
    """
)


@pytest.fixture
def chained_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""

    (tmp_path / "fake_chained_eval.py").write_text(CHAINED_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_chained_eval"


def test_the_image_side_child_renders_by_capture(chained_eval: str) -> None:
    """Spec R9: what every image build renders is what inspect's chain sends."""

    spec = TaskReplayCasesSpec(task=f"{chained_eval}:chained", case_count=1, case_digest=_UNSEALED)

    prepared = replayed_cases(spec)

    assert prepared[0]["case"]["input"] == EXPECTED_CHAINED_INPUT
