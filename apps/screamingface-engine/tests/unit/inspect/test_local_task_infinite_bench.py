# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""InfiniteBench Math.Find as a LOCAL inspect Task, cut once for every model (OME-1602).

What these tests pin, and why:

- the cut is inspect_evals' own character cut at inspect_evals' default budget, byte for byte,
  so the only deviation is that no model's name picks the budget;
- the Task never asks which model is answering, so its Cases are the same for every Candidate
  (inspect_evals' truncation solver calls `get_model()`, which Task replay refuses by name);
- the solver chain is inspect_evals', in inspect_evals' order, with only the cut swapped;
- the row: 350 Cases, graded by inspect's own `exact()`, no judge.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai._util.registry import registry_info  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import ChatMessageSystem, ChatMessageUser  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.infinite_bench import (  # noqa: E402
    infinite_bench as inspect_evals_infinite_bench,
)
from inspect_evals.infinite_bench.truncate_input import truncate_raw_text  # noqa: E402

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.local_tasks.infinite_bench import (  # noqa: E402
    infinite_bench as local,
)
from screamingface_engine_inspect.local_tasks.infinite_bench.infinite_bench import (  # noqa: E402
    MAX_CHARS,
    fixed_cut,
    fixed_cut_solver,
    infinite_bench_math_find,
)

#: A model name missing from inspect_evals' context-size table: inspect_evals then cuts at 128k
#: tokens with its character estimate, the budget this Task fixes for everyone.
_UNLISTED_MODEL: str = "some-model-inspect-evals-does-not-list"


def _long_list(count: int) -> str:
    """A Math.Find-shaped input: an instruction, a long list of numbers, the question."""

    numbers: str = ", ".join(str((index * 7919) % 100_003) for index in range(count))
    return f"Find the largest number from the list below:\n\n[{numbers}]\n\nThe largest is: "


def test_the_budget_is_inspect_evals_default_128k_tokens_as_characters() -> None:
    assert MAX_CHARS == int((128_000 - 500) * 3.5) == 446_250


@pytest.mark.parametrize("count", [10, 80_000, 200_000])
def test_the_cut_is_inspect_evals_own_cut_for_a_model_it_does_not_list(count: int) -> None:
    """NAMED DEVIATION pinned: the cut equals inspect_evals' `truncate_raw_text` at its default
    budget for every input, short or long, so the Cases differ from inspect_evals' only for a
    model inspect_evals' table lists or tokenizes (gpt*, the Claude 3 family)."""

    text: str = _long_list(count)

    assert fixed_cut(text) == truncate_raw_text(text, _UNLISTED_MODEL)


def test_a_long_input_keeps_its_instruction_and_its_question() -> None:
    """The cut drops the middle: the instruction at the start and the question at the end both
    survive, so the Candidate still knows what to find."""

    text: str = _long_list(200_000)
    cut: str = fixed_cut(text)

    assert len(text) > MAX_CHARS >= len(cut) - len("...")
    assert cut.startswith("Find the largest number from the list below:")
    assert cut.endswith("The largest is: ")
    assert "..." in cut


def test_the_cut_never_asks_which_model_is_answering(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: the Cases are the same for every Candidate. inspect_evals' solver reads
    `get_model().name`; this one must not, so a `get_model` that raises cannot stop it."""

    def no_model(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the cut asked for the model")

    monkeypatch.setattr(inspect_evals_infinite_bench, "get_model", no_model)
    state: TaskState = TaskState(
        model="none/none",  # type: ignore[arg-type]
        sample_id=1,
        epoch=1,
        input="unused",
        messages=[
            ChatMessageSystem(content="You are a helpful assistant."),
            ChatMessageUser(content=_long_list(200_000)),
        ],
    )

    async def unused_generate(state: TaskState, *_args: Any, **_kwargs: Any) -> TaskState:
        return state

    cut_solver: Any = fixed_cut_solver()
    solved: TaskState = asyncio.run(cut_solver(state, unused_generate))

    assert solved.messages[0].content == "You are a helpful assistant."
    assert solved.messages[1].content == fixed_cut(_long_list(200_000))


def test_the_solver_chain_is_inspect_evals_with_only_the_cut_swapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System message, the cut, the prompt template, `generate()`: inspect_evals' order, with
    inspect_evals' `truncate_input_solver` replaced by this Task's fixed cut."""

    # A one-Sample stand-in dataset, so the Task builds without the Hub.
    stand_in = MemoryDataset([Sample(input="Find the largest number.", target="7")])
    monkeypatch.setattr(local, "hf_dataset", lambda **_kwargs: stand_in)

    steps: list[Any] = list(getattr(infinite_bench_math_find().solver, "_solvers"))

    assert [registry_info(step).name for step in steps] == [
        "inspect_ai/system_message",
        "fixed_cut_solver",
        "inspect_ai/prompt_template",
        "inspect_ai/generate",
    ]


def test_the_row_serves_350_cases_graded_by_inspects_exact_match() -> None:
    benchmark = imported_benchmark("infinite_bench_math_find")

    assert benchmark.benchmark.case_count == 350
    assert benchmark.judge is None
