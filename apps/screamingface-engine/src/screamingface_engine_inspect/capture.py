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
    Stage 4 — after the chain: refuse a chain that never asked, or asked twice, or read the
              model under test (OME-1602, F3: the Case would be built for a model named
              "none"), or reordered the choices (the Grading Material holds the Sample's
              order); turn the recorded messages into the one input text (a fixed
              conversation becomes the candidate-input envelope, R14); cross the writer's
              validated boundary and build the prepared Case.
    Stage 5 — import child only (``answered_pass``, OME-1602, F4): run the chain once more
              with a real-looking reply, and refuse a chain that asks the model again after
              it (a judge inside the solver chain, which the blank reply never wakes).

Example: Sample "Which port serves HTTPS?" with choices 21/443/80/22, chain
``[prompt_template("You are a security analyst. {prompt}"), multiple_choice()]`` →
input "Answer the following multiple choice question. … You are a security analyst. Which
port serves HTTPS?\\n\\nA) 21\\nB) 443\\nC) 80\\nD) 22", Grading Material target B.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import dataclass
from inspect import currentframe
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any, Literal

from screamingface_engine_inspect.conversation_input import conversation_input
from screamingface_engine_inspect.picture_input import picture_case_text
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
    from inspect_ai.model import ChatMessage, ModelName
    from inspect_ai.solver import TaskState

#: The model name the stand-in state carries. Nothing resolves it: no model is created, and
#: a read of it by the eval's code is refused (OME-1602, F3).
STAND_IN_MODEL: str = "none/stand-in"

#: How a system message joins the input text: as leading text, blank line, then the prompt.
#: Named deviation (contracteval pattern): a Benchmark cannot address a Candidate's system
#: role, so the eval's system instruction rides ahead of the user prompt.
#: AIDEV-NOTE: picture_input.py's ``_SYSTEM_SEPARATOR`` is its twin for picture Cases; change both.
_MESSAGE_SEPARATOR: str = "\n\n"


class CaptureError(PrepareError):
    """The solver chain did something a single-answer Case cannot hold. Names the Case."""


@dataclass(frozen=True)
class ModelRead:
    """One read of the model under test by the eval's own code: who read it, and where."""

    #: The reading function's module, ``inspect_evals.mmlu.mmlu``.
    module: str
    #: The reading function's qualified name, ``mmlu_multiple_choice.<locals>.solve``.
    function: str
    #: ``file:line`` of the read, for the refusal.
    where: str


#: Reads of the model under test that leave the Case the same under any model name, by module
#: and function (not by line, which moves on every pin bump). Each entry says why.
_EXEMPT_MODEL_READS: frozenset[tuple[str, str]] = frozenset(
    {
        # WHY: mmlu_0_shot's solver reads the model only to size max_tokens for its own
        # generate call; the prompt it sends, and so its Case, is the same for any model.
        ("inspect_evals.mmlu.mmlu", "mmlu_multiple_choice.<locals>.solve"),
    }
)


@contextmanager
def model_reads() -> Iterator[list[ModelRead]]:
    """While open, record every time the eval's own code asks which model is under test.

    WHY: the replay child's model is ``none/none``, and ``get_model()`` returns a model named
    "none" instead of raising, so a solver that cuts or words the prompt for the model
    (InfiniteBench truncates 1.2M characters to its context size) seals a Case built for
    "none" (OME-1602, F3). Reads are recorded, never raised here, so the chain still runs as
    inspect would and a chain that fails for its own reason is named by that reason.

    What is seen: every ``get_model()`` that resolves the active model, plus each read of a
    TaskState's model name made through :func:`_watched_model_name`. That includes a
    ``role=`` read: with the role unbound and no ``default``, inspect falls back to the
    active model, so ``get_model(role="grader")`` in a solver reads the model under test.
    Reads made by inspect's own code are not the eval's and are skipped.

    AIDEV-NOTE: this wraps the private ``inspect_ai.model._model.active_model`` (pinned
    inspect_ai 0.3.263), which every ``get_model()`` with no model, role match or default
    calls; ``get_model`` looks the name up at call time, so rebinding it here is seen.
    Re-verify on any pin bump.
    """

    from inspect_ai.model import _model as model_module

    original: Any = getattr(model_module, "active_model")
    get_model_code: Any = getattr(model_module, "get_model").__code__
    reads: list[ModelRead] = []

    def watched_active_model() -> Any:
        """inspect's active_model, noting the eval code that called get_model() for it."""

        frame: FrameType | None = currentframe()
        caller: FrameType | None = None if frame is None else frame.f_back
        if caller is not None and caller.f_code is get_model_code:
            _note_read(caller.f_back, reads)
        return original()

    setattr(model_module, "active_model", watched_active_model)
    try:
        yield reads
    finally:
        setattr(model_module, "active_model", original)


def refuse_model_reads(reads: Sequence[ModelRead], reader: str) -> None:
    """Refuse the first read of the model under test that is not exempt (F3).

    ``reader`` names who read it in the refusal: ``case 3: the solver`` or ``the task
    function``.
    """

    refused: list[ModelRead] = _not_exempt(reads)
    if refused:
        raise CaptureError(
            f"{reader} read the model under test at {refused[0].where}; the Case would be cut "
            "or worded for a model named 'none', not for the Candidate"
        )


def _not_exempt(reads: Sequence[ModelRead]) -> list[ModelRead]:
    """The reads no exemption covers, in the order they happened."""

    return [read for read in reads if (read.module, read.function) not in _EXEMPT_MODEL_READS]


def _note_read(frame: FrameType | None, reads: list[ModelRead]) -> None:
    """Record the frame as a read, unless it is inspect's own code reading its own state."""

    if frame is None or _is_inspects_own(frame.f_code.co_filename):
        return
    reads.append(
        ModelRead(
            module=str(frame.f_globals.get("__name__", "")),
            function=frame.f_code.co_qualname,
            where=f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}",
        )
    )


def _is_inspects_own(filename: str) -> bool:
    """True for a file inside the inspect_ai package."""

    import inspect_ai

    package_file: str | None = inspect_ai.__file__
    return package_file is not None and Path(filename).is_relative_to(Path(package_file).parent)


def _watched_model_name(reads: list[ModelRead]) -> ModelName:
    """The stand-in state's model name, noting each time the eval's code reads it (F3).

    persistbench writes ``str(state.model)`` into its system prompt; that read goes through
    here. The class is built per call so every copy of the name (a deep-copied state) shares
    the one ``reads`` list it closes over.
    """

    from inspect_ai.model import ModelName

    class WatchedModelName(ModelName):
        """inspect's ModelName, noting reads of its name by code outside inspect."""

        def __getattribute__(self, attribute: str) -> Any:
            """A read of ``api`` or ``name`` is a read of the model under test."""

            if attribute in ("api", "name"):
                frame: FrameType | None = currentframe()
                _note_read(None if frame is None else frame.f_back, reads)
            return super().__getattribute__(attribute)

        def __str__(self) -> str:
            """``str(state.model)`` reads the model under test."""

            frame: FrameType | None = currentframe()
            _note_read(None if frame is None else frame.f_back, reads)
            return super().__str__()

        def __eq__(self, pattern: object) -> bool:
            """``state.model == "gpt"`` reads the model under test too."""

            frame: FrameType | None = currentframe()
            _note_read(None if frame is None else frame.f_back, reads)
            return super().__eq__(pattern)

    return WatchedModelName(STAND_IN_MODEL)


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


def captured_case_records(
    task: Task, spec: TaskReplayCasesSpec, *, answered_pass: bool = False
) -> list[PreparedCase]:
    """Render every Sample of ``task`` by capture and build the prepared Cases.

    Args:
        task: the built Task, as the eval's task function returned it.
        spec: the declaration whose writer options apply (``has_answer_key``,
            ``keep_sample_metadata``) and whose ``excluded_sample_ids`` are left out; its
            seal is not read here.
        answered_pass: also run each Sample's chain a second time with a real-looking reply,
            refusing a chain that asks the model again after it (OME-1602, F4). The import
            child turns it on; image builds replay an import that already passed it.

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
    inputs: list[tuple[str, list[str] | None]] = asyncio.run(
        _captured_inputs(task, samples, answered_pass)
    )
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
    task: Task, samples: Sequence[Sample], answered_pass: bool
) -> list[tuple[str, list[str] | None]]:
    """Stage 2 — run the chain on each Sample under one event loop, then, when asked, once
    more with a real-looking reply (F4)."""

    inputs: list[tuple[str, list[str] | None]] = []
    for case_id, sample in enumerate(samples, 1):
        inputs.append(await _capture_one(task, sample, case_id))
        if answered_pass:
            await _refuse_a_judge_after_the_answer(task, sample, case_id)
    return inputs


def _sample_state(sample: Sample, case_id: int, reads: list[ModelRead]) -> TaskState:
    """Stage 2 — the TaskState inspect's sample runner would build for a deep copy of the
    Sample, with its own store, registered as the active sample state.

    WHY a deep copy of the Sample: inspect copies it before building the state, so a solver
    that writes state.metadata never reaches the Sample, and so never the Grading Material.
    """

    from inspect_ai._eval.task.util import sample_messages
    from inspect_ai.scorer import Target
    from inspect_ai.solver import TaskState
    from inspect_ai.solver._task_state import set_sample_state
    from inspect_ai.util._store import init_subtask_store

    # AIDEV-NOTE: sample_messages, set_sample_state and init_subtask_store are private
    # inspect helpers, the same ones task_run_sample uses to build a Sample's messages and
    # give each Sample its own store and active state — safe under the exact == pin;
    # re-verify on any pin bump.
    sample = deepcopy(sample)
    state: TaskState = TaskState(
        model=_watched_model_name(reads),
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
    return state


def _chain(task: Task) -> Any:
    """The Task's setup then solver, as one solver."""

    from inspect_ai.solver import chain

    steps: list[Any] = ([task.setup] if task.setup is not None else []) + [task.solver]
    return chain(steps)


async def _capture_one(task: Task, sample: Sample, case_id: int) -> tuple[str, list[str] | None]:
    """Stages 2 to 4 for one Sample: the input text and the choices as the model saw them."""

    stand_in: _StandIn = _StandIn(case_id)
    reads: list[ModelRead]
    with model_reads() as reads:
        state: TaskState = _sample_state(sample, case_id, reads)
        try:
            await _chain(task)(state, stand_in.generate)
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
    refuse_model_reads(reads, f"case {case_id}: the solver")
    return _input_text(stand_in.messages, case_id), stand_in.choices


#: The reply the answered pass gives. WHY not empty: a judge in the chain often runs only on
#: a real reply (air_bench returns early on an empty one), so the blank pass never shows it.
_STAND_IN_ANSWER: str = "ANSWER: A"


@dataclass
class _AnsweringStandIn:
    """The answered pass's stand-in model: answers every ask, counting them, and notes how
    many model reads came before the first answer."""

    reads: list[ModelRead]
    asks: int = 0
    reads_before_answer: int | None = None

    async def generate(self, state: TaskState, *_: Any, **__: Any) -> TaskState:
        """Answer with ``_STAND_IN_ANSWER``; never raise, so the chain runs to its end."""

        from inspect_ai.model import ModelOutput

        self.asks += 1
        if self.reads_before_answer is None:
            self.reads_before_answer = len(self.reads)
        output: ModelOutput = ModelOutput.from_content(STAND_IN_MODEL, _STAND_IN_ANSWER)
        state.output = output
        state.messages.append(output.message)
        return state


@contextmanager
def _every_model_fetch(reads: list[ModelRead]) -> Iterator[None]:
    """While open, record EVERY ``get_model`` call the eval's code makes, whatever it asks
    for: no model, a role, or a model by name (F4).

    WHY a profile hook and not :func:`model_reads`: a judge fetched by role or by name never
    resolves the active model, and the eval bound ``get_model`` by name at import, so only
    a call on the function's code object is seen everywhere. The hook runs only in the
    import child's answered pass, on this thread, and restores the previous hook after.

    AIDEV-NOTE: reads the code object of the private ``inspect_ai.model._model.get_model``
    (pinned inspect_ai 0.3.263); re-verify on any pin bump.
    """

    from inspect_ai.model import _model as model_module

    get_model_code: Any = getattr(model_module, "get_model").__code__
    previous: Any = sys.getprofile()

    def profile(frame: FrameType, event: str, _: Any) -> None:
        """Note a call into get_model by the frame that made it."""

        if event == "call" and frame.f_code is get_model_code:
            _note_read(frame.f_back, reads)

    sys.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)


async def _refuse_a_judge_after_the_answer(task: Task, sample: Sample, case_id: int) -> None:
    """F4 — run the Sample's chain again with a real-looking reply, and refuse a chain that
    asks the model again after it: a second ``generate`` (air_bench's judge turn), any
    ``get_model`` call after the answer (a judge fetched by role, by name, or the model
    under test), or a read of the model's name after it.

    WHY a refusal: the Candidate answers once and the Benchmark grades the reply with the
    scorer only, so a judge inside the chain would make every Case fail at grading. Only
    solvers placed after generate that ASK again are refused; one that parses or rewrites
    the state still captures.
    """

    reads: list[ModelRead] = []
    stand_in: _AnsweringStandIn = _AnsweringStandIn(reads)
    with _every_model_fetch(reads):
        state: TaskState = _sample_state(sample, case_id, reads)
        # WHY suppress: this pass only watches what the chain asks; an error it raises with a
        # real-looking reply (the judge reaching the "none" model, or a provider with no
        # key) is not the finding, and the call that raised was recorded before it ran.
        with suppress(Exception):
            await _chain(task)(state, stand_in.generate)
    answered_at: int = (
        len(reads) if stand_in.reads_before_answer is None else stand_in.reads_before_answer
    )
    after: list[ModelRead] = reads[answered_at:]
    if stand_in.asks > 1 or _not_exempt(after):
        raise CaptureError(
            f"case {case_id}: after the Candidate answers, the solver asks the model again (a "
            "judge or a second turn in the solver chain); the Benchmark grades the reply with "
            "the scorer only"
        )


def _input_text(messages: Sequence[ChatMessage], case_id: int) -> str:
    """Stage 4 — the messages the model saw, as the one text the Candidate sees.

    Three shapes:

    * One prompt: any number of leading system messages, then exactly one user message.
      The texts join with a blank line, as they always have, so these Cases keep their bytes.
    * A fixed conversation (OME-1527, R14): any other run of user and assistant turns that
      ends on a user turn. It becomes the candidate-input envelope with every turn kept in
      order and role, so the Candidate still answers once, with the next turn.
    * One prompt holding pictures (OME-1271): the v2 envelope, each picture inline
      (``picture_input.py``, which also refuses audio, video, documents and a picture
      anywhere but the one user message).

    Refused: a tool turn, an assistant turn that calls tools, a system turn inside a
    conversation (a Benchmark cannot address the Candidate's system role, the rule the
    one-prompt fold above follows), an empty or blank turn (hand-built healthbench refused
    it too), and a conversation that does not end on a user turn.

    Example: user "What is 2 plus 2?", assistant "4", user "And 6 times 7?" →
    ``{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user","content":"What
    is 2 plus 2?"},{"role":"assistant","content":"4"},{"role":"user","content":"And 6 times
    7?"}]}``.
    """

    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    picture_text: str | None = picture_case_text(messages, case_id)
    if picture_text is not None:
        return picture_text
    system_count: int = 0
    while system_count < len(messages) and isinstance(messages[system_count], ChatMessageSystem):
        system_count += 1
    shape_is_one_prompt: bool = len(messages) == system_count + 1 and isinstance(
        messages[-1], ChatMessageUser
    )
    if shape_is_one_prompt:
        return _MESSAGE_SEPARATOR.join(message.text for message in messages)
    return _conversation_text(messages, case_id)


def _conversation_text(messages: Sequence[ChatMessage], case_id: int) -> str:
    """Stage 4, a fixed conversation — every turn a text turn, the last one the user's, sealed
    into the candidate-input envelope in order and role (R14)."""

    from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser

    roles: list[str] = [message.role for message in messages]
    for index, message in enumerate(messages):
        if isinstance(message, ChatMessageSystem):
            # WHY: the system role is the Candidate's (a recipe's own instructions); a
            # Benchmark only hands over the question. A one-prompt Case folds its system text
            # into the prompt for that reason (``_MESSAGE_SEPARATOR``); inside a conversation
            # there is no single prompt to fold into, so the Case is refused, never re-roled.
            raise CaptureError(
                f"case {case_id}: the solver sent a system turn inside a conversation "
                f"({', '.join(roles)}); a Benchmark cannot address the Candidate's system role"
            )
        if not isinstance(message, ChatMessageUser | ChatMessageAssistant):
            raise CaptureError(
                f"case {case_id}: the solver sent a {message.role} message ({', '.join(roles)}); "
                "a conversation Case holds user and assistant turns only"
            )
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            raise CaptureError(
                f"case {case_id}: an assistant turn calls tools; a conversation Case is text "
                "turns only"
            )
        if not message.text.strip():
            # WHY: a blank turn is a damaged row, not a question; the Candidate would be paid
            # to answer nothing. Hand-built healthbench's preparer refused it the same way.
            raise CaptureError(
                f"case {case_id}: conversation turn {index + 1} ({message.role}) is empty"
            )
    if not messages or not isinstance(messages[-1], ChatMessageUser):
        raise CaptureError(
            f"case {case_id}: the solver sent {len(messages)} messages ({', '.join(roles)}); "
            "a Case ends on the user turn the Candidate answers"
        )
    return conversation_input(
        [{"role": message.role, "content": message.text} for message in messages]
    )


__all__ = [
    "STAND_IN_MODEL",
    "CaptureError",
    "ModelRead",
    "captured_case_records",
    "model_reads",
    "refuse_model_reads",
]
