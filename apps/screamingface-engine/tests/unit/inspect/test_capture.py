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
from inspect_ai.util import store  # noqa: E402

from screamingface_engine_inspect.capture import CaptureError, captured_case_records  # noqa: E402
from screamingface_engine_inspect.prepare import PrepareError, TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay import (  # noqa: E402
    TaskReplayError,
    replay_environment,
    replayed_cases,
)

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


def test_a_question_that_lists_its_own_options_keeps_its_answer_by_value() -> None:
    """worldsense's shape: the question already lists numbered options, the chain is a bare
    generate(), and the answer key is the option's value, not a letter. The Case is the
    question as written and the key stays "2"; nothing renders the options again."""

    sample = Sample(
        input="Ann is before Bo. (1) yes (2) no (3) unsure", choices=["1", "2", "3"], target="2"
    )
    task = Task(dataset=MemoryDataset([sample]))

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "Ann is before Bo. (1) yes (2) no (3) unsure"
    assert prepared[0]["grading_material"] == {"target": "2", "choices": ["1", "2", "3"]}


def test_an_answer_key_that_names_no_option_is_refused() -> None:
    sample = Sample(input="Which?", choices=["1", "2"], target="7")
    task = Task(dataset=MemoryDataset([sample]))

    with pytest.raises(PrepareError, match="neither a letter within 2 choices nor"):
        captured_case_records(task, _spec())


def test_kept_metadata_rides_the_grading_material() -> None:
    sample = Sample(input="Which port serves HTTPS?", target="443", metadata={"domain": "web"})
    task = Task(dataset=MemoryDataset([sample]))

    prepared = captured_case_records(task, _spec(keep_sample_metadata=True))

    assert prepared[0]["grading_material"] == {"target": "443", "metadata": {"domain": "web"}}


# ── the per-Sample context inspect's sample runner gives a solver ─────────────


def test_a_solver_after_generate_cannot_rewrite_the_case() -> None:
    """The Case is what was SENT: a rewrite after the answer must not reach it (review
    finding on #1219: the stand-in kept the live message objects)."""

    sample = Sample(input="What is 6 times 7?", target="42")
    task = Task(
        dataset=MemoryDataset([sample]), solver=[generate(), prompt_template("AFTER: {prompt}")]
    )

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "What is 6 times 7?"


@solver
def _counts_in_the_store() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        seen: int = store().get("seen", 0) + 1
        store().set("seen", seen)
        state.user_prompt.text = f"seen {seen}"
        return state

    return solve


def test_each_sample_gets_its_own_store() -> None:
    """Under eval() every Sample starts with an empty store; a counting solver renders
    "seen 1" for each. One shared store would render seen 1, seen 2, seen 3."""

    samples = [Sample(input="Q?", target="A") for _ in range(3)]
    task = Task(dataset=MemoryDataset(samples), solver=[_counts_in_the_store(), generate()])

    prepared = captured_case_records(task, _spec())

    assert [item["case"]["input"] for item in prepared] == ["seen 1", "seen 1", "seen 1"]


@solver
def _writes_metadata() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.metadata["leak"] = True
        return state

    return solve


def test_a_solver_writing_metadata_never_reaches_the_grading_material() -> None:
    """inspect deep-copies the Sample before building the state; so does capture, or a
    solver's scratch note would land inside the sealed Grading Material."""

    sample = Sample(input="Q?", target="A", metadata={"k": 1})
    task = Task(dataset=MemoryDataset([sample]), solver=[_writes_metadata(), generate()])

    prepared = captured_case_records(task, _spec(keep_sample_metadata=True))

    assert prepared[0]["grading_material"] == {"target": "A", "metadata": {"k": 1}}
    assert sample.metadata == {"k": 1}


def test_a_one_message_list_input_is_one_prompt() -> None:
    """A Sample may carry its input as a single chat message; that is one prompt, not a
    conversation, and the writer must not refuse it as "not text"."""

    sample = Sample(input=[ChatMessageUser(content="What is 6 times 7?")], target="42")
    task = Task(dataset=MemoryDataset([sample]))

    prepared = captured_case_records(task, _spec())

    assert prepared[0]["case"]["input"] == "What is 6 times 7?"


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


def test_a_conversation_that_ends_on_an_assistant_turn_is_refused() -> None:
    """A fixed conversation is a Case (OME-1527, R14; see test_conversation_cases.py), but
    only when it ends on the user turn the Candidate answers; one that ends on the assistant's
    own turn leaves the Candidate nothing to reply to."""

    sample = Sample(
        input=[
            ChatMessageUser(content="What is 2 plus 2?"),
            ChatMessageAssistant(content="4"),
        ],
        target="4",
    )
    task = Task(dataset=MemoryDataset([sample]))

    with pytest.raises(CaptureError, match="case 1: .*2 messages.*assistant.*ends on the user"):
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


# ── no model is reachable from the child ─────────────────────────────────────

#: A solver that builds its own model instead of using the generate it was handed. Stand-in
#: for cyberseceval_4's multiturn_phishing solver; it proves the child's environment, not
#: that eval's prompt.
OWN_MODEL_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.model import get_model
    from inspect_ai.solver import Generate, Solver, TaskState, generate, solver

    @solver
    def own_model() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            reply = await get_model().generate("hello")
            state.user_prompt.text = f"{state.user_prompt.text} [model said {reply.completion!r}]"
            return state
        return solve

    @task
    def phishing() -> Task:
        return Task(dataset=MemoryDataset([Sample(input="Q?", target="A")]),
                    solver=[own_model(), generate()])
    """
)


@pytest.fixture
def own_model_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it, with a model name in
    the parent's environment as a builder's shell might carry."""

    (tmp_path / "fake_own_model_eval.py").write_text(OWN_MODEL_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    monkeypatch.setenv("INSPECT_EVAL_MODEL", "mockllm/model")
    return "fake_own_model_eval"


def test_the_child_environment_names_no_model(tmp_path: Path) -> None:
    env = replay_environment(tmp_path, {"INSPECT_EVAL_MODEL": "mockllm/model", "PATH": "/bin"})

    assert env["INSPECT_EVAL_MODEL"] == "none/none"


def test_a_solver_that_builds_its_own_model_is_refused_in_the_child(own_model_eval: str) -> None:
    """INVARIANT: nothing in the child reaches a model. A solver that calls get_model()
    bypasses the stand-in; with the parent's INSPECT_EVAL_MODEL set, the model's words would
    land inside the Case (review finding on #1219). The child's environment names no model,
    so the call raises and capture refuses the Sample by name."""

    spec = TaskReplayCasesSpec(
        task=f"{own_model_eval}:phishing", case_count=1, case_digest=_UNSEALED
    )

    with pytest.raises(TaskReplayError, match="case 1: the solver raised PrerequisiteError"):
        replayed_cases(spec)


# ── a Named Deviation: Samples the declaration leaves out (spec R18) ─────────

#: Three Samples, the middle one with nothing to ask: the shape of sad_stages_full, whose
#: upstream records 15, 59 and 103 have an empty body. A stand-in for that eval's data, not its
#: prompt; it proves which Samples become Cases, not how sad renders them.
GAP_SAMPLES: list[Sample] = [
    Sample(input="First question?", target="A", id="q:0"),
    Sample(input="", target="B", id="q:1"),
    Sample(input="Third question?", target="C", id="q:2"),
]


def _gap_task() -> Task:
    """A Task over GAP_SAMPLES with inspect's default generate()."""

    return Task(dataset=MemoryDataset(list(GAP_SAMPLES)))


def test_an_empty_sample_is_refused_without_an_exclusion() -> None:
    """Why the deviation exists: the Case boundary never prepares a Case with nothing to ask."""

    with pytest.raises(PrepareError, match="case 2: sample input is empty"):
        captured_case_records(_gap_task(), _spec())


def test_excluded_samples_are_left_out_and_the_rest_renumbered() -> None:
    """Spec R18: the listed ids never become Cases; the kept ones are numbered 1..N, so the
    Case count is what is left, as on the Hugging Face path."""

    prepared = captured_case_records(_gap_task(), _spec(excluded_sample_ids=("q:1",)))

    assert [(case["case"]["case_id"], case["case"]["input"]) for case in prepared] == [
        ("1", "First question?"),
        ("2", "Third question?"),
    ]
    assert [case["grading_material"]["target"] for case in prepared] == ["A", "C"]


def test_an_excluded_id_the_dataset_no_longer_holds_is_refused() -> None:
    """INVARIANT: the exclusion was written against one dataset; an id that is gone means it
    describes nothing we can check, so Case Preparation stops instead of serving it."""

    with pytest.raises(PrepareError, match="q:9 are not in the dataset"):
        captured_case_records(_gap_task(), _spec(excluded_sample_ids=("q:1", "q:9")))


#: GAP_SAMPLES as a stand-in eval the image-side child can import.
GAP_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample

    @task
    def gap() -> Task:
        return Task(dataset=MemoryDataset([
            Sample(input="First question?", target="A", id="q:0"),
            Sample(input="", target="B", id="q:1"),
            Sample(input="Third question?", target="C", id="q:2"),
        ]))
    """
)


@pytest.fixture
def gap_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""

    (tmp_path / "fake_gap_eval.py").write_text(GAP_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_gap_eval"


def test_the_image_side_child_leaves_the_excluded_samples_out(gap_eval: str) -> None:
    """The ids cross into the child as JSON and still drop the Sample: what every image build
    serves is what the import sealed."""

    spec = TaskReplayCasesSpec(
        task=f"{gap_eval}:gap",
        case_count=2,
        case_digest=_UNSEALED,
        excluded_sample_ids=("q:1",),
    )

    prepared = replayed_cases(spec)

    assert [case["case"]["input"] for case in prepared] == ["First question?", "Third question?"]


# ── OME-1602, F3: the model under test read while the Case is built ──────────

from inspect_ai.model import get_model  # noqa: E402


@solver
def _names_the_model() -> Solver:
    """InfiniteBench's shape: the prompt is cut or worded for the model being evaluated."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.user_prompt.text = f"{state.user_prompt.text} (for {get_model().name})"
        return state

    return solve


@solver
def _reads_the_state_model() -> Solver:
    """persistbench's shape: the system prompt names ``str(state.model)``."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.user_prompt.text = f"{state.user_prompt.text} (for {state.model})"
        return state

    return solve


@pytest.fixture
def child_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model name the replay child carries, so get_model() resolves as it does there."""

    monkeypatch.setenv("INSPECT_EVAL_MODEL", "none/none")


@pytest.mark.usefixtures("child_model_name")
def test_a_solver_reading_the_model_under_test_is_refused_because_the_case_is_built_for_none() -> (
    None
):
    """get_model() returns a model named "none" in the replay child; it never raises, so the
    Case was cut or worded for "none" and every Candidate got that Case."""

    task = _one_sample_task([_names_the_model(), generate()])

    with pytest.raises(
        CaptureError, match=r"case 1: the solver read the model under test at test_capture\.py:\d+"
    ):
        captured_case_records(task, _spec())


def test_a_solver_reading_the_states_model_name_is_refused() -> None:
    task = _one_sample_task([_reads_the_state_model(), generate()])

    with pytest.raises(CaptureError, match=r"case 1: the solver read the model under test"):
        captured_case_records(task, _spec())


@pytest.mark.usefixtures("child_model_name")
def test_mmlus_token_sizing_read_is_exempt_because_its_case_is_the_same_under_any_model() -> None:
    """mmlu_0_shot reads the model only to size max_tokens for its generate call; the prompt
    it sends is the same under any model name, so its row keeps importing."""

    pytest.importorskip("inspect_evals")
    from inspect_evals.mmlu.mmlu import mmlu_multiple_choice

    prepared = captured_case_records(_one_sample_task([mmlu_multiple_choice()]), _spec())

    assert "Which port serves HTTPS?" in prepared[0]["case"]["input"]


#: A task function that reads the model while it builds the Task: niah's shape, which sizes
#: its haystack for the model's tokenizer.
BUILD_READ_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.model import get_model

    @task
    def sized() -> Task:
        name = get_model().name
        return Task(dataset=MemoryDataset([Sample(input=f"Q for {name}?", target="A")]))
    """
)


@pytest.fixture
def build_read_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""

    (tmp_path / "fake_build_read_eval.py").write_text(BUILD_READ_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_build_read_eval"


def test_a_task_function_reading_the_model_is_refused_in_the_child(build_read_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{build_read_eval}:sized", case_count=1, case_digest=_UNSEALED)

    with pytest.raises(
        TaskReplayError,
        match=r"the task function read the model under test at fake_build_read_eval\.py:\d+",
    ):
        replayed_cases(spec)


# ── OME-1602, F4: a judge inside the solver chain ────────────────────────────


@solver
def _judges_a_real_reply() -> Solver:
    """air_bench's shape: after the answer, the chain asks the model again to judge it, but
    only when the reply is not empty, so a blank stand-in reply never shows it."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not state.output.completion:
            return state
        state.user_prompt.text = f"Judge this reply: {state.output.completion}"
        return await generate(state)

    return solve


@solver
def _asks_its_own_judge_after_the_answer() -> Solver:
    """A judge built inside the chain from the model under test, after a real reply."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.output.completion:
            await get_model().generate(f"Judge: {state.output.completion}")
        return state

    return solve


def test_a_judge_turn_after_a_real_reply_passes_the_blank_capture() -> None:
    """Why the answered pass exists: on the blank reply the judge never runs, so capture
    alone seals the Case and every Case then fails at grading."""

    prepared = captured_case_records(
        _one_sample_task([generate(), _judges_a_real_reply()]), _spec()
    )

    assert prepared[0]["case"]["input"] == "Which port serves HTTPS?"


def test_a_second_ask_after_a_real_reply_is_refused_by_the_answered_pass() -> None:
    task = _one_sample_task([generate(), _judges_a_real_reply()])

    with pytest.raises(CaptureError, match=r"case 1: after the Candidate answers, the solver asks"):
        captured_case_records(task, _spec(), answered_pass=True)


@pytest.mark.usefixtures("child_model_name")
def test_a_model_read_after_a_real_reply_is_refused_by_the_answered_pass() -> None:
    """The judge's own error is ignored in that pass; reading the model after the answer is
    the refusal."""

    task = _one_sample_task([generate(), _asks_its_own_judge_after_the_answer()])

    with pytest.raises(CaptureError, match=r"case 1: after the Candidate answers"):
        captured_case_records(task, _spec(), answered_pass=True)


def test_post_answer_parsing_and_rewrites_still_pass_the_answered_pass() -> None:
    """A solver after generate that only reads or rewrites the state is not a judge; the
    chained multiple_choice parse and the rewrite of #1219 both still capture."""

    rewritten = _one_sample_task([generate(), prompt_template("AFTER: {prompt}")])
    chained = _one_sample_task([prompt_template(TEMPLATE), multiple_choice()])

    assert captured_case_records(rewritten, _spec(), answered_pass=True)[0]["case"]["input"] == (
        "Which port serves HTTPS?"
    )
    assert captured_case_records(chained, _spec(), answered_pass=True)[0]["case"]["input"] == (
        EXPECTED_CHAINED_INPUT
    )


#: air_bench's shape as a stand-in eval the import child can import.
JUDGE_IN_CHAIN_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import match
    from inspect_ai.solver import Generate, Solver, TaskState, generate, solver

    @solver
    def annotate() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if not state.output.completion:
                return state
            state.user_prompt.text = f"Judge this reply: {state.output.completion}"
            return await generate(state)
        return solve

    @task
    def judged_in_chain() -> Task:
        return Task(dataset=MemoryDataset([Sample(input="Q?", target="A", id=1)]),
                    solver=[generate(), annotate()], scorer=match())
    """
)


@pytest.fixture
def judge_in_chain_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the import child can import it."""

    (tmp_path / "fake_judge_in_chain_eval.py").write_text(JUDGE_IN_CHAIN_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_judge_in_chain_eval"


def test_the_import_child_runs_the_answered_pass(judge_in_chain_eval: str) -> None:
    from screamingface_engine_inspect.import_replay import replay_for_import

    with pytest.raises(TaskReplayError, match=r"after the Candidate answers, the solver asks"):
        replay_for_import(f"{judge_in_chain_eval}:judged_in_chain", None)


# ── review findings: every ask after the answer, and the import child's build watch ──


@solver
def _builds_a_judge_by_role_after_the_answer() -> Solver:
    """A judge fetched by role after a real reply; its own error must not hide it."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.output.completion:
            await get_model(role="grader").generate(f"Judge: {state.output.completion}")
        return state

    return solve


@solver
def _builds_a_judge_by_name_after_the_answer() -> Solver:
    """A judge fetched by name after a real reply: it raises with no key, and is still a judge."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.output.completion:
            await get_model("openai/gpt-4o").generate(f"Judge: {state.output.completion}")
        return state

    return solve


@pytest.mark.usefixtures("child_model_name")
def test_a_judge_fetched_by_role_after_the_answer_is_refused() -> None:
    task = _one_sample_task([generate(), _builds_a_judge_by_role_after_the_answer()])

    with pytest.raises(CaptureError, match=r"case 1: after the Candidate answers"):
        captured_case_records(task, _spec(), answered_pass=True)


def test_a_judge_fetched_by_name_after_the_answer_is_refused() -> None:
    task = _one_sample_task([generate(), _builds_a_judge_by_name_after_the_answer()])

    with pytest.raises(CaptureError, match=r"case 1: after the Candidate answers"):
        captured_case_records(task, _spec(), answered_pass=True)


def test_the_import_child_refuses_a_task_function_reading_the_model(build_read_eval: str) -> None:
    """The import child builds the Task itself, so it needs its own build-time watch: without
    it, run 1 seals Cases built for "none"."""

    from screamingface_engine_inspect.import_replay import replay_for_import

    with pytest.raises(
        TaskReplayError,
        match=r"the task function read the model under test at fake_build_read_eval\.py:\d+",
    ):
        replay_for_import(f"{build_read_eval}:sized", None)
