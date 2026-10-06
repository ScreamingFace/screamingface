# pyright: reportMissingImports=false
# WHY file-level: the solver run imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Capture rendering: a Task-replay Case is what the eval's own solvers send the model.

FEATURE: Task-replay Imported Benchmarks (OME-1273, spec R2, R9). Think of it as sitting a
stand-in student at the desk: the eval's real ``setup`` and ``solver`` run on each Sample
exactly as inspect would run them, and the moment they ask the model (the first ``generate``)
the stand-in writes down the messages it was shown and answers nothing. That transcript is
the Case. No imitation of any solver lives here; chained solvers (sevenllm's
``prompt_template`` then ``multiple_choice``) come out right because both really ran.

What runs: the Task's ``setup`` and ``solver`` chain, per Sample, up to the first
``generate``. What never runs: inspect's ``eval()``, a model, a scorer, a Judge, a sandbox,
a tool. Stages, in execution order:

    Stage 1 — refuse a Task that declares a sandbox: its solvers expect a container; then
              drop the Samples the declaration excludes by id, a Named Deviation (R18).
    Stage 2 — per Sample: build the TaskState inspect would build (a deep copy of the
              Sample's input as messages, its choices, target and metadata), give it its own
              store and register it as the active sample state, as inspect's sample runner
              does, then run ``setup`` then ``solver`` with the stand-in ``generate``.
    Stage 3 — the stand-in, on its one allowed call: refuse tools; record the messages and
              the choices as shown; answer with an empty ModelOutput so post-answer solver
              work (answer parsing) runs as it would on a blank reply.
    Stage 4 — after the chain: refuse a chain that never asked, or asked twice, or reordered
              the choices (the Grading Material holds the Sample's order); turn the recorded
              messages into the one input text; cross the writer's validated boundary and
              build the prepared Case.

Example: Sample "Which port serves HTTPS?" with choices 21/443/80/22, chain
``[prompt_template("You are a security analyst. {prompt}"), multiple_choice()]`` →
input "Answer the following multiple choice question. … You are a security analyst. Which
port serves HTTPS?\\n\\nA) 21\\nB) 443\\nC) 80\\nD) 22", Grading Material target B.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from screamingface_engine_inspect.prepare import (
    PreparedCase,
    PrepareError,
    TaskReplayCasesSpec,
    prepared_case,
    without_excluded_samples,
)

if TYPE_CHECKING:
    from inspect_ai import Task
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ChatMessage
    from inspect_ai.solver import TaskState

#: The model name the stand-in state carries. Nothing resolves it: no model is created.
STAND_IN_MODEL: str = "none/stand-in"

#: How a system message joins the input text: as leading text, blank line, then the prompt.
#: Named deviation (contracteval pattern): a Benchmark cannot address a Candidate's system
#: role, so the eval's system instruction rides ahead of the user prompt.
_MESSAGE_SEPARATOR: str = "\n\n"


class CaptureError(PrepareError):
    """The solver chain did something a single-answer Case cannot hold. Names the Case."""


@dataclass
class _StandIn:
    """The stand-in model: records what the first ``generate`` was shown, answers nothing."""

    case_id: int
    messages: list[ChatMessage] | None = None
    choices: list[str] | None = None

    async def generate(
        self, state: TaskState, tool_calls: Literal["loop", "single", "none"] = "loop", **_: Any
    ) -> TaskState:
        """Stage 3 — the one ``generate`` the chain may make (inspect's ``Generate`` shape;
        ``tool_calls`` and the generation config are accepted and ignored: no model runs)."""

        from inspect_ai.model import ModelOutput

        if self.messages is not None:
            raise CaptureError(f"case {self.case_id}: the solver called generate twice")
        if state.tools:
            raise CaptureError(
                f"case {self.case_id}: the solver gave the model {len(state.tools)} tool(s); "
                "a tool-using eval is not a single-answer Benchmark"
            )
        # WHY a deep copy: the chain keeps mutating these message objects after the answer
        # (a solver placed after generate rewrites the prompt); the Case is what was SENT.
        self.messages = deepcopy(list(state.messages))
        self.choices = [choice.value for choice in state.choices] if state.choices else None
        # WHY an empty answer and not a stop: solvers parse the reply after generate
        # (multiple_choice reads ANSWER: letters); on a blank reply they find nothing, so the
        # state we check afterwards is the state inspect would hold after a silent model.
        output: ModelOutput = ModelOutput.from_content(STAND_IN_MODEL, "")
        state.output = output
        state.messages.append(output.message)
        return state


def captured_case_records(task: Task, spec: TaskReplayCasesSpec) -> list[PreparedCase]:
    """Render every Sample of ``task`` by capture and build the prepared Cases.

    Args:
        task: the built Task, as the eval's task function returned it.
        spec: the declaration whose writer options apply (``has_answer_key``,
            ``keep_sample_metadata``) and whose ``excluded_sample_ids`` are left out; its
            seal is not read here.

    Returns:
        One prepared Case per kept Sample, numbered from 1, in the order the Task holds them.

    Raises:
        CaptureError: the Task or one Sample's chain cannot be a single-answer Case; the
            message names the Case number and the reason.
        PrepareError: a Sample fails the writer's validated boundary.
    """

    # Stage 1
    if task.sandbox is not None:
        raise CaptureError(
            f"the task declares a sandbox ({task.sandbox.type}); its solvers expect a "
            "container, which Case Preparation never starts"
        )
    samples: list[Sample] = list(task.dataset)
    # WHY before capture: an excluded Sample may be one capture cannot render (sad's empty
    # questions), and the Cases are numbered over what is kept (spec R18).
    if spec.excluded_sample_ids is not None:
        samples = without_excluded_samples(spec.excluded_sample_ids, samples)
    inputs: list[tuple[str, list[str] | None]] = asyncio.run(_captured_inputs(task, samples))
    prepared: list[PreparedCase] = []
    for case_id, (sample, (input_text, shown_choices)) in enumerate(
        zip(samples, inputs, strict=True), start=1
    ):
        record: PreparedCase = prepared_case(sample, case_id, input_text, spec)
        kept_choices: list[str] | None = record["grading_material"].get("choices")
        # INVARIANT: the letters the Candidate answers with index the Grading Material's
        # choices. A solver that reorders them (multiple_choice's deprecated shuffle) would
        # grade B against the wrong option.
        if kept_choices is not None and shown_choices != kept_choices:
            raise CaptureError(
                f"case {case_id}: the solver reordered the choices before asking the model; "
                "pass a task arg that disables the shuffle"
            )
        prepared.append(record)
    return prepared


async def _captured_inputs(
    task: Task, samples: Sequence[Sample]
) -> list[tuple[str, list[str] | None]]:
    """Stage 2 — run the chain on each Sample under one event loop."""

    return [await _capture_one(task, sample, case_id) for case_id, sample in enumerate(samples, 1)]


async def _capture_one(task: Task, sample: Sample, case_id: int) -> tuple[str, list[str] | None]:
    """Stages 2 to 4 for one Sample: the input text and the choices as the model saw them."""

    from inspect_ai._eval.task.util import sample_messages
    from inspect_ai.model import ModelName
    from inspect_ai.scorer import Target
    from inspect_ai.solver import TaskState, chain
    from inspect_ai.solver._task_state import set_sample_state
    from inspect_ai.util._store import init_subtask_store

    # AIDEV-NOTE: sample_messages, set_sample_state and init_subtask_store are private
    # inspect helpers, the same ones task_run_sample uses to build a Sample's messages and
    # give each Sample its own store and active state — safe under the exact == pin;
    # re-verify on any pin bump.
    # WHY a deep copy of the Sample: inspect copies it before building the state, so a solver
    # that writes state.metadata never reaches the Sample, and so never the Grading Material.
    sample = deepcopy(sample)
    state: TaskState = TaskState(
        model=ModelName(STAND_IN_MODEL),
        sample_id=sample.id if sample.id is not None else case_id,
        epoch=1,
        input=sample.input,
        target=Target(sample.target),
        choices=sample.choices,
        messages=sample_messages(sample),
        metadata=sample.metadata,
    )
    # INVARIANT: one store per Sample, as under eval(); without this, store() is one object
    # across every Sample in the child and a counting solver renders "seen 1, seen 2, …".
    init_subtask_store(state.store)
    set_sample_state(state)
    stand_in: _StandIn = _StandIn(case_id)
    steps: list[Any] = ([task.setup] if task.setup is not None else []) + [task.solver]
    try:
        await chain(steps)(state, stand_in.generate)
    except CaptureError:
        raise
    except Exception as exc:  # noqa: BLE001 — the eval's own solver code; any raise is named
        raise CaptureError(
            f"case {case_id}: the solver raised {type(exc).__name__}: {exc}"
        ) from exc
    if stand_in.messages is None:
        raise CaptureError(
            f"case {case_id}: the solver never called generate, so nothing was sent to the model"
        )
    return _input_text(stand_in.messages, case_id), stand_in.choices


def _input_text(messages: Sequence[ChatMessage], case_id: int) -> str:
    """Stage 4 — the messages the model saw, as the one text the Candidate sees.

    Accepted: any number of leading system messages, then exactly one user message, all
    plain text. Refused: anything else (assistant or tool turns, several user turns, images
    or audio), because a Case is one text and the Candidate answers it once.
    """

    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    roles: list[str] = [message.role for message in messages]
    system_count: int = 0
    while system_count < len(messages) and isinstance(messages[system_count], ChatMessageSystem):
        system_count += 1
    shape_is_one_prompt: bool = len(messages) == system_count + 1 and isinstance(
        messages[-1], ChatMessageUser
    )
    if not shape_is_one_prompt:
        raise CaptureError(
            f"case {case_id}: the solver sent {len(messages)} messages ({', '.join(roles)}); "
            "a Case is system text then one user prompt"
        )
    texts: list[str] = []
    for message in messages:
        if not isinstance(message.content, str) and any(
            part.type != "text" for part in message.content
        ):
            raise CaptureError(
                f"case {case_id}: a {message.role} message carries non-text content; "
                "a Case is text only"
            )
        texts.append(message.text)
    return _MESSAGE_SEPARATOR.join(texts)


__all__ = ["STAND_IN_MODEL", "CaptureError", "captured_case_records"]
