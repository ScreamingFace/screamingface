# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer keeps every conservable scorer of a Task (OME-1268, PR 4 of 5).

FEATURE: a Task with several scorers (SQuAD: f1 and exact) is no longer refused. The
first conservable scorer becomes the row's `scorer` (the Headline Score), the rest its
`extra_scorers`, their registry names its `named_scores`; a scorer the row cannot express
(one that grades with a judge, in a multi-scorer Task) is written as `dropped_scorers`
with a review TODO, never cut silently.

INVARIANT: a single-scorer Task with no extra metric renders without any Named Score
line (a registered Benchmark whose scorer declares an extra metric gains a "not
reproduced" comment on re-import, nothing else); a Task whose Headline Score's metric is
not a plain mean (SimpleQA's `simpleqa_metric`) is refused naming the metric (the
tripwire); a non-mean metric on a non-headline scorer is a note, not a refusal; an extra
scorer created with arguments, or two scorers sharing one registry name, is refused —
never written truncated.

Two halves. The reader half runs the import child on a stand-in eval written to tmp_path
(the test_import_replay pattern): it proves the child's wiring, not any real eval's fetch.
The renderer half hands facts straight to the row renderer, no child.
"""

from __future__ import annotations

import importlib
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import BenchmarkSpec, JudgeSpec  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    ImportReplay,
    TaskReplayFacts,
    TaskReplayImport,
    replay_for_import,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay import TaskReplayError  # noqa: E402
from screamingface_engine_inspect.task_replay_rows import (  # noqa: E402
    TaskReplayRows,
    render_task_replay_rows,
)

#: A stand-in eval whose tasks declare the scorer shapes this PR must read. `self_grader`
#: stands in for MATH's expression_equivalance (a judge-model kwarg, None by default: the
#: model under test); `formula_scorer` for SimpleQA's (a formula headline);
#: `mean_with_a_grouped_extra` for cyberseceval_4's (a mean plus a breakdown).
FAKE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, json_dataset
    from inspect_ai.scorer import (
        Metric, SampleScore, Score, Target, accuracy, exact, f1, match, metric, scorer, stderr,
    )
    from inspect_ai.solver import TaskState, generate, prompt_template

    DATA = os.environ["FAKE_NAMED_SCORES_DATA"]
    TEMPLATE = "Answer briefly.\\n\\n{prompt}\\n"

    @metric
    def harmonic_headline() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            return 0.0
        return compute

    @scorer(metrics=[accuracy(), stderr()])
    def self_grader(model=None):
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")
        return score

    @scorer(metrics=[harmonic_headline()])
    def formula_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value={"correct": 1.0})
        return score

    @scorer(metrics=[accuracy(), stderr(), {"by_topic": [accuracy()]}])
    def mean_with_a_grouped_block():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")
        return score

    @scorer(metrics=[accuracy(), stderr(), harmonic_headline()])
    def mean_with_a_grouped_extra():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")
        return score

    def _task(scorers):
        return Task(dataset=json_dataset(DATA, FieldSpec(input="q", target="a", id="id")),
                    solver=[prompt_template(TEMPLATE), generate()], scorer=scorers)

    @task
    def squad_like() -> Task:
        return _task([f1(), exact()])

    @task
    def math_like() -> Task:
        return _task([self_grader(model=None), exact(), match()])

    @task
    def judged_only() -> Task:
        return _task([self_grader(model=None), self_grader(model=None)])

    @task
    def single_judged() -> Task:
        return _task(self_grader(model=None))

    @task
    def bare() -> Task:
        return _task([])

    @task
    def single() -> Task:
        return _task(match(numeric=True))

    @task
    def formula() -> Task:
        return _task(formula_scorer())

    @task
    def cyse_like() -> Task:
        return _task([exact(), mean_with_a_grouped_extra()])

    @task
    def grouped_headline() -> Task:
        return _task(mean_with_a_grouped_extra())

    @task
    def grouped_block_after_headline() -> Task:
        return _task(mean_with_a_grouped_block())

    @task
    def extra_with_kwargs() -> Task:
        return _task([f1(), match(numeric=True)])

    @task
    def duplicate_names() -> Task:
        return _task([match(), match()])
    """
)

_ROWS: list[dict[str, object]] = [
    {"id": 1, "q": "When was it built?", "a": "1889"},
    {"id": 2, "q": "What is 2 plus 2?", "a": "4"},
]


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the import child can import it; return its module name."""

    (tmp_path / "fake_named_scores_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    (tmp_path / "cases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in _ROWS), encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_NAMED_SCORES_DATA", str(tmp_path / "cases.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_named_scores_eval"


# --- the reader: what the import child says about the Task's scorers --------------------


def test_a_two_scorer_task_reads_scorer_and_extra_scorers(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:squad_like", None)

    assert replay.facts.scorer == "inspect_ai.scorer:f1"
    assert replay.facts.extra_scorers == ("inspect_ai.scorer:exact",)
    assert replay.facts.named_scores == ("f1", "exact")
    assert replay.facts.dropped_scorers == ()
    assert replay.facts.headline_differs is False
    assert replay.facts.dropped_metrics == ()


def test_a_self_grading_scorer_is_dropped_by_name_and_the_headline_moves(fake_eval: str) -> None:
    """MATH's shape: the first scorer takes a judge model and defaults to the model under
    test. In a multi-scorer Task it is dropped by name; the headline moves to the next
    conservable scorer and the facts say so, so the row gets a review TODO."""

    replay: ImportReplay = replay_for_import(f"{fake_eval}:math_like", None)

    assert replay.facts.scorer == "inspect_ai.scorer:exact"
    assert replay.facts.extra_scorers == ("inspect_ai.scorer:match",)
    assert replay.facts.named_scores == ("exact", "match")
    assert replay.facts.dropped_scorers == ("self_grader",)
    assert replay.facts.headline_differs is True


def test_a_task_with_no_conservable_scorer_is_refused(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="no conservable scorer"):
        replay_for_import(f"{fake_eval}:judged_only", None)


def test_a_single_judged_scorer_still_takes_the_judged_path(fake_eval: str) -> None:
    # INVARIANT: a Task with ONE judged scorer is not a multi-scorer Task: nothing dropped.
    replay: ImportReplay = replay_for_import(f"{fake_eval}:single_judged", None)

    assert replay.facts.scorer == f"{fake_eval}:self_grader"
    assert replay.facts.dropped_scorers == ()
    assert replay.facts.extra_scorers == ()


def test_a_task_with_no_scorer_is_refused(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="no scorer"):
        replay_for_import(f"{fake_eval}:bare", None)


def test_a_single_scorer_task_reads_exactly_as_before(fake_eval: str) -> None:
    # Review Focus 5: nothing about a single-scorer row changes.
    replay: ImportReplay = replay_for_import(f"{fake_eval}:single", None)

    assert replay.facts.scorer == "inspect_ai.scorer:match"
    assert replay.facts.scorer_kwargs == {"numeric": True}
    assert (replay.facts.extra_scorers, replay.facts.named_scores) == ((), ())
    assert (replay.facts.dropped_scorers, replay.facts.dropped_metrics) == ((), ())


def test_a_formula_headline_metric_is_refused_naming_it(fake_eval: str) -> None:
    # The tripwire (spec §2.4): the headline must be a plain mean, or the reducer would
    # publish the wrong number as the Headline Score.
    with pytest.raises(TaskReplayError, match="harmonic_headline"):
        replay_for_import(f"{fake_eval}:formula", None)


def test_the_real_simpleqa_scorer_is_refused_naming_simpleqa_metric() -> None:
    """Spec §8.4: SimpleQA cannot import and silently publish mean(correct) as its headline.
    Read straight off a Task, no child: the real scorer object carries its real metrics."""

    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_evals.simpleqa import scorer as simpleqa_module

    from screamingface_engine_inspect.importer import ImporterError, _scorer_facts

    task = Task(
        dataset=MemoryDataset([Sample(input="q", target="a")]),
        scorer=simpleqa_module.simpleqa_scorer(),
    )
    with pytest.raises(ImporterError, match="simpleqa_metric"):
        _scorer_facts(task, simpleqa_module)


def test_a_grouped_metric_on_a_non_headline_scorer_is_a_named_deviation(fake_eval: str) -> None:
    # cyberseceval_4's shape, as the second scorer: imported, the extra metric noted.
    replay: ImportReplay = replay_for_import(f"{fake_eval}:cyse_like", None)

    assert replay.facts.named_scores == ("exact", "mean_with_a_grouped_extra")
    assert replay.facts.dropped_metrics == ("harmonic_headline",)


def test_a_grouped_extra_on_the_headline_scorer_is_still_a_plain_mean(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:grouped_headline", None)

    assert replay.facts.scorer == f"{fake_eval}:mean_with_a_grouped_extra"
    assert replay.facts.dropped_metrics == ("harmonic_headline",)


def test_a_grouped_metric_block_after_the_headline_is_noted_in_words(fake_eval: str) -> None:
    # Stack review on #1250: the `<unnamed metric>` sentinel hit the renderer's charset guard
    # and refused the whole import under the wrong label. The note is now plain words.
    replay: ImportReplay = replay_for_import(f"{fake_eval}:grouped_block_after_headline", None)

    assert replay.facts.dropped_metrics == ("a grouped metric block",)
    assert "a grouped metric block" in _rows(replay.facts).benchmark


def test_an_extra_scorer_created_with_arguments_is_refused(fake_eval: str) -> None:
    # Stack review on #1250: `match(numeric=True)` beside f1 was written as `match()` — the
    # row would pin the wrong configuration as faithful ("1,889" grades C in inspect_evals, I here).
    with pytest.raises(TaskReplayError, match=r"extra scorer match .*numeric.*True"):
        replay_for_import(f"{fake_eval}:extra_with_kwargs", None)


def test_two_scorers_sharing_a_registry_name_are_refused_before_any_file(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="one registry name"):
        replay_for_import(f"{fake_eval}:duplicate_names", None)


# --- the renderer: what the generated row says ----------------------------------------------


def _facts(**overrides: Any) -> TaskReplayFacts:
    values: dict[str, Any] = {
        "task_ref": "inspect_evals.squad.squad:squad",
        "task_args": None,
        "mcq": False,
        "scorer": "inspect_ai.scorer:f1",
        "scorer_kwargs": {},
        "custom_metrics": (),
        "keep_sample_metadata": False,
        **overrides,
    }
    return TaskReplayFacts(**values)


def _rows(facts: TaskReplayFacts) -> TaskReplayRows:
    imported = TaskReplayImport(
        declaration=TaskReplayCasesSpec(task=facts.task_ref, case_count=3, case_digest="e" * 64),
        case_sources=(),
        facts=facts,
    )
    return render_task_replay_rows("squad", imported, "cc-by-sa-4.0")


def _benchmark(rows: TaskReplayRows) -> BenchmarkSpec:
    """Evaluate the generated BenchmarkSpec row the way importing benchmarks.py would."""

    namespace: dict[str, Any] = {"BenchmarkSpec": BenchmarkSpec, "JudgeSpec": JudgeSpec}
    exec("declared = (\n" + rows.benchmark + ")", namespace)  # noqa: S102 — our own rendered row
    return namespace["declared"][0]


def test_a_two_scorer_row_declares_extra_scorers_and_named_scores() -> None:
    rows = _rows(_facts(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1", "exact")))

    assert 'extra_scorers=("inspect_ai.scorer:exact",)' in rows.benchmark
    assert 'named_scores=("f1", "exact")' in rows.benchmark
    assert "dropped_scorers" not in rows.benchmark
    row = _benchmark(rows)
    assert row.extra_scorers == ("inspect_ai.scorer:exact",)
    assert row.named_scores == ("f1", "exact")


def test_a_dropped_scorer_renders_as_a_named_deviation_with_a_review_todo() -> None:
    rows = _rows(
        _facts(
            scorer="inspect_evals.math.math:expression_exact_match",
            extra_scorers=("inspect_evals.math.math:expression_exact_match_sympy",),
            named_scores=("expression_exact_match", "expression_exact_match_sympy"),
            dropped_scorers=("expression_equivalance",),
            headline_differs=True,
        )
    )

    assert 'dropped_scorers=("expression_equivalance",)' in rows.benchmark
    assert "Named Deviation" in rows.benchmark
    assert "TODO(review): the Headline Score is expression_exact_match" in rows.benchmark
    assert "judge=JudgeSpec" not in rows.benchmark  # the headline is not judged
    assert _benchmark(rows).dropped_scorers == ("expression_equivalance",)


def test_a_dropped_metric_renders_as_a_not_reproduced_note() -> None:
    rows = _rows(_facts(dropped_metrics=("grouped_accuracy_metric",)))

    assert "grouped_accuracy_metric" in rows.benchmark
    assert "not reproduced" in rows.benchmark


def test_a_single_scorer_row_carries_no_named_score_line() -> None:
    # Narrowed from "renders byte-identically" (stack review on #1250): comparing the
    # default facts with explicitly empty ones compared a value with itself. The claim
    # that holds: a single-scorer Task with no extra metric gets none of this PR's lines.
    plain = _rows(_facts()).benchmark

    for marker in (
        "extra_scorers",
        "named_scores",
        "dropped_scorers",
        "TODO(review): the Headline Score",
        "not reproduced",
    ):
        assert marker not in plain


# --- OME-1602: shapes the importer used to write wrongly, now refused by name -------------

import sys  # noqa: E402
from collections.abc import Callable  # noqa: E402

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import GenerateConfig  # noqa: E402
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine_inspect.importer import (  # noqa: E402
    ImporterError,
    ScorerFacts,
    _scorer_facts,
    recorded_scorer_arguments,
)


def extract_answer(completion: str) -> str:
    """A stand-in for drop's answer extractor: the function a scorer is handed."""

    return completion.strip()


def replaced_reader(completion: str) -> str:
    """What this module's name ``replaced_reader`` holds now."""

    return completion.upper()


def _replaced_reader(completion: str) -> str:
    """A stand-in for a function whose module name was later rebound: it calls itself
    ``replaced_reader`` (set below), but importing that name gives back the function above."""

    return completion


_replaced_reader.__name__ = _replaced_reader.__qualname__ = "replaced_reader"


@scorer(metrics=[accuracy()])
def keyed(answer_fn: Callable[[str], str] | None = None) -> Scorer:
    """A stand-in for drop's scorer, which takes the function that pulls out the answer."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def worded(words: tuple[str, ...] = (), config: GenerateConfig | None = None) -> Scorer:
    """A stand-in for a scorer whose arguments are a tuple of words and a config object."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C")

    return score


def _built_with_recorder(made: Callable[[], Scorer]) -> Task:
    """One-Sample Task whose scorer is created while the import child's recorder listens."""

    with recorded_scorer_arguments():
        return Task(dataset=MemoryDataset([Sample(input="q", target="a")]), scorer=made())


def test_a_function_scorer_argument_is_refused_because_inspect_logs_only_its_name() -> None:
    """inspect logs a function as its name, so a row would rebuild the scorer with a string.
    Since PR 6 a module-level function is named by reference instead (next test); a lambda
    has no name an import can find, so it is still refused."""

    task: Task = _built_with_recorder(lambda: keyed(lambda completion: completion.strip()))

    with pytest.raises(
        ImporterError, match=r"keyed is created with answer_fn='<lambda>'.*function"
    ):
        _scorer_facts(task, sys.modules[__name__])


def test_a_module_level_function_argument_is_named_by_reference_not_by_its_logged_name() -> None:
    """drop's shape (OME-1602 PR 6): answer_fn=extract_answer becomes a reference the grader
    imports, and the logged string 'extract_answer' never reaches the literal kwargs, where it
    would rebuild the scorer with a string."""

    task: Task = _built_with_recorder(lambda: keyed(extract_answer))

    facts: ScorerFacts = _scorer_facts(task, sys.modules[__name__])

    assert facts.scorer_function_kwargs == {"answer_fn": f"{__name__}:extract_answer"}
    assert "answer_fn" not in facts.scorer_kwargs


def test_a_function_defined_inside_another_is_refused() -> None:
    """A nested function's qualified name holds ``<locals>``: no import reaches it."""

    def nested(completion: str) -> str:
        return completion

    task: Task = _built_with_recorder(lambda: keyed(nested))

    with pytest.raises(ImporterError, match=r"answer_fn='nested'"):
        _scorer_facts(task, sys.modules[__name__])


def test_a_function_from_outside_the_evals_package_is_refused_at_import() -> None:
    """The importer refuses the row assembly would refuse, by the same rule, so no row is
    written that only fails later (review finding on OME-1602 PR 6). The stand-in Task lives
    in this module, so its package is this module; textwrap is not inside it."""

    task: Task = _built_with_recorder(lambda: keyed(textwrap.dedent))

    with pytest.raises(
        ImporterError, match=r"answer_fn=textwrap:dedent, which points outside the eval's own"
    ):
        _scorer_facts(task, sys.modules[__name__])


def test_a_function_whose_name_now_points_elsewhere_is_refused() -> None:
    """Importing the logged name would give back a different function, so the row could not
    rebuild the same argument: ``_replaced_reader`` calls itself ``replaced_reader``, but that
    module name holds another function."""

    task: Task = _built_with_recorder(lambda: keyed(_replaced_reader))

    with pytest.raises(ImporterError, match=r"answer_fn='replaced_reader'"):
        _scorer_facts(task, sys.modules[__name__])


def test_an_object_scorer_argument_is_refused_because_its_logged_dict_is_not_the_object() -> None:
    """An object inspect logs as a dict was written into the row as that dict, so the row
    rebuilt the scorer with a dict where the eval passed a GenerateConfig."""

    task: Task = _built_with_recorder(lambda: worded(config=GenerateConfig(temperature=0.0)))

    with pytest.raises(ImporterError, match=r"worded is created with config=.*GenerateConfig"):
        _scorer_facts(task, sys.modules[__name__])


def test_a_tuple_scorer_argument_still_imports_because_it_round_trips_as_the_logged_list() -> None:
    """A tuple is logged as the equal list; the row writes the list and nothing is lost."""

    task: Task = _built_with_recorder(lambda: worded(("yes", "no")))

    facts: ScorerFacts = _scorer_facts(task, sys.modules[__name__])

    assert facts.scorer_kwargs == {"words": ["yes", "no"]}


#: A stand-in eval for the import child: each task is the smallest Task with one OME-1602
#: shape. It proves the child's wiring, not any real eval's scorer.
GUARDED_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.model import get_model
    from inspect_ai.scorer import Score, Target, accuracy, scorer
    from inspect_ai.solver import TaskState

    def extract_answer(completion):
        return completion.strip()

    @scorer(metrics=[accuracy()])
    def keyed(answer_fn=None):
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")
        return score

    def _task(scorers):
        return Task(dataset=MemoryDataset([Sample(input="What is 2 plus 2?", target="4", id=1)]),
                    scorer=scorers)

    @task
    def function_argument() -> Task:
        # A lambda: no module-level name the row could write (OME-1602 PR 6 names the rest).
        return _task(keyed(lambda completion: completion.strip()))

    @scorer(metrics=[accuracy()])
    def asks_the_grader():
        async def score(state: TaskState, target: Target) -> Score:
            await get_model(role="grader").generate("Is it right?")
            return Score(value="C")
        return score

    @task
    def grader_role() -> Task:
        return _task(asks_the_grader())
    """
)


@pytest.fixture
def guarded_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the OME-1602 stand-in eval where the import child can import it."""

    (tmp_path / "fake_guarded_eval.py").write_text(GUARDED_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_guarded_eval"


def test_the_import_child_records_scorer_arguments_so_a_function_argument_is_refused(
    guarded_eval: str,
) -> None:
    """Without the recorder in the child, the function would import as its logged name. Since
    PR 6 a module-level function is named by reference, so the stand-in passes a lambda, the
    shape that still has no name a row could write."""

    with pytest.raises(TaskReplayError, match=r"answer_fn='<lambda>'"):
        replay_for_import(f"{guarded_eval}:function_argument", None)


# F2 — judges the importer did not see: the grader role, the model under test, a panel.

from inspect_ai.model import get_model  # noqa: E402
from inspect_ai.scorer import exact  # noqa: E402


async def _ask_the_grader(question: str) -> str:
    """A stand-in for a same-package helper that reaches the judge for its scorer."""

    reply = await get_model(role="grader").generate(question)
    return reply.completion


@scorer(metrics=[accuracy()])
def asks_the_grader() -> Scorer:
    """A stand-in for simpleqa's scorer: it never names a judge, it asks for the grader role."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model(role="grader").generate("Is it right?")
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def asks_through_a_helper() -> Scorer:
    """The grader role asked one helper down, as anima's scorer does."""

    async def score(state: TaskState, target: Target) -> Score:
        await _ask_the_grader("Is it right?")
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def asks_the_candidate() -> Scorer:
    """A scorer that grades with whatever model is under test: get_model() with no model."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model().generate("Is it right?")
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def counts_tokens(model: str = "openai/gpt-4o") -> Scorer:
    """A stand-in for math's exact-match scorers: get_model(model) names its model, so the
    body rule must not read it as a judge."""

    async def score(state: TaskState, target: Target) -> Score:
        get_model(model)
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def panel_of_judges(grader_models: list[str] | None = None) -> Scorer:
    """A stand-in for fortress's scorer, which grades with a list of judges."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C")

    return score


def _one_sample_task(scorers: Scorer | list[Scorer]) -> Task:
    """One-Sample Task with the given scorers, built in this process."""

    return Task(dataset=MemoryDataset([Sample(input="q", target="a")]), scorer=scorers)


def test_a_scorer_asking_for_the_grader_role_reads_as_judged_by_that_role() -> None:
    """simpleqa's shape: no judge kwarg, so the old reader wrote an unjudged row whose
    grader role nobody binds; the role now takes the judged row's path."""

    facts: ScorerFacts = _scorer_facts(_one_sample_task(asks_the_grader()), sys.modules[__name__])

    assert facts.judge_role == "grader"


def test_the_grader_role_asked_by_a_same_package_helper_is_read_too() -> None:
    task: Task = _one_sample_task(asks_through_a_helper())

    assert _scorer_facts(task, sys.modules[__name__]).judge_role == "grader"


def test_a_scorer_that_grades_with_the_model_under_test_is_refused() -> None:
    """A bare get_model() inside a scorer grades with the Candidate's own model; a Benchmark
    grades with a pinned judge, never the Candidate."""

    with pytest.raises(ImporterError, match=r"asks_the_candidate reads the model under test"):
        _scorer_facts(_one_sample_task(asks_the_candidate()), sys.modules[__name__])


def test_a_panel_of_judges_is_refused_because_a_benchmark_pins_one_judge() -> None:
    """fortress's shape: a list of judges passed the old judge check, so the row would call
    every one of them, unmetered."""

    task: Task = _one_sample_task(panel_of_judges(grader_models=["a/judge-1", "b/judge-2"]))

    with pytest.raises(ImporterError, match=r"panel_of_judges grades with a panel of 2 judges"):
        _scorer_facts(task, sys.modules[__name__])


def test_a_scorer_that_names_its_own_model_is_not_read_as_a_judge() -> None:
    """get_model(model) is not the model under test; math's exact-match scorers must stay."""

    facts: ScorerFacts = _scorer_facts(_one_sample_task(counts_tokens()), sys.modules[__name__])

    assert facts.judge_role is None


def test_a_role_judged_scorer_beside_an_exact_one_is_dropped_by_name() -> None:
    """In a multi-scorer Task a judged scorer cannot be seated, whichever way it reaches
    its judge, so it is dropped by name as before."""

    task: Task = _one_sample_task([asks_the_grader(), exact()])

    facts: ScorerFacts = _scorer_facts(task, sys.modules[__name__])

    # One scorer kept grades like a single-scorer row: no lone Named Score (OME-1602 PR 5,
    # owner-approved change; a lone name tells the grader to expect a dict).
    assert (facts.named_scores, facts.dropped_scorers) == ((), ("asks_the_grader",))


def test_the_import_child_carries_the_grader_role_back(guarded_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{guarded_eval}:grader_role", None)

    assert replay.facts.judge_role == "grader"


def test_a_grader_role_row_renders_a_todo_judge_that_fills_the_grader_role() -> None:
    """The TODO judge keeps the row unshippable until a human pins the judge (OME-1240);
    the role says which judge the scorer asks for (OME-1370)."""

    rows: TaskReplayRows = _rows(
        _facts(scorer="inspect_evals.simpleqa.scorer:simpleqa_scorer", judge_role="grader")
    )

    assert 'judge=JudgeSpec(model="TODO", model_role="grader"),' in rows.benchmark
    assert _benchmark(rows).judge == JudgeSpec(model="TODO", model_role="grader")


# F5 — an extra scorer's own whole-run metric

from inspect_ai.scorer import Metric, SampleScore, metric  # noqa: E402


@metric
def harmonic_balance() -> Metric:
    """A stand-in for stereoset's whole-run formula: not a mean of the per-Case scores."""

    def compute(scores: list[SampleScore]) -> float:
        return 0.0

    return compute


@scorer(metrics=[harmonic_balance()])
def balanced() -> Scorer:
    """A stand-in for stereoset's second scorer, scored over the run by its own formula."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1.0)

    return score


def test_an_extra_scorer_with_its_own_whole_run_metric_is_refused() -> None:
    """stereoset's shape: only the headline's metric was checked, so the extra scorer's
    formula quietly became a mean published under its Named Score column."""

    task: Task = _one_sample_task([exact(), balanced()])

    with pytest.raises(
        ImporterError, match=r"extra scorer balanced scores the whole run with harmonic_balance"
    ):
        _scorer_facts(task, sys.modules[__name__])


# F1, review finding: a scorer the recorder never saw ---------------------------------------

#: A Task scored by inspect's multi_scorer, which never passes through the @scorer decorator
#: the recorder watches. Imported by the import child only.
MULTI_SCORED_EVAL: str = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import exact, includes, multi_scorer

    @task
    def multi_scored() -> Task:
        return Task(
            dataset=MemoryDataset([Sample(input="What is 2 plus 2?", target="4", id=1)]),
            scorer=multi_scorer([exact(), includes()], "mean"),
        )
    """
)


@pytest.fixture
def multi_scored_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the multi_scorer stand-in eval where the import child can import it."""

    (tmp_path / "fake_multi_scored_eval.py").write_text(MULTI_SCORED_EVAL, encoding="utf-8")
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_multi_scored_eval"


def test_a_scorer_the_recorder_never_saw_is_refused_because_unrecorded_is_not_clean(
    multi_scored_eval: str,
) -> None:
    """multi_scorer's list of scorers is no literal: read from the log alone, the row would
    rebuild multi_scorer with no scorers, and the argument check was skipped for want of a
    record."""

    with pytest.raises(TaskReplayError, match=r"scorer multi_scorer was built without passing"):
        replay_for_import(f"{multi_scored_eval}:multi_scored", None)


# Review findings on the first cut of F2 ---------------------------------------------------


@scorer(metrics=[accuracy()])
def judged_by_default(judge_model: str = "openai/gpt-4o") -> Scorer:
    """niah's shape: a judge parameter nobody passes, so the scorer grades with its default."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model(judge_model).generate("Is it right?")
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def asks_a_role_it_was_given(grader_role: str = "grader") -> Scorer:
    """hle's shape: the role is an argument, never a literal the reader can name."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model(role=grader_role).generate("Is it right?")
        return Score(value="C")

    return score


def test_an_extra_scorer_judging_with_its_default_judge_is_dropped_by_name() -> None:
    """An extra scorer is built bare at grading time, so its default judge would grade the
    Named Score outside benchmark identity; it cannot be seated, like any judged scorer."""

    task: Task = _one_sample_task([exact(), judged_by_default()])

    facts: ScorerFacts = _scorer_facts(task, sys.modules[__name__])

    # One scorer kept grades like a single-scorer row: no lone Named Score (OME-1602 PR 5,
    # owner-approved change; a lone name tells the grader to expect a dict).
    assert (facts.named_scores, facts.dropped_scorers) == ((), ("judged_by_default",))


def test_a_role_held_in_a_variable_is_refused_because_no_row_can_name_it() -> None:
    task: Task = _one_sample_task(asks_a_role_it_was_given())

    with pytest.raises(ImporterError, match=r"asks_a_role_it_was_given asks for a model role"):
        _scorer_facts(task, sys.modules[__name__])


# Review findings on the second cut of F2 --------------------------------------------------

from screamingface_engine_inspect.judge_shape import JudgeShape  # noqa: E402


@scorer(metrics=[accuracy()])
def asks_two_roles() -> Scorer:
    """A scorer with a grader and a critic: the row can bind only one role to its judge."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model(role="grader").generate("Is it right?")
        await get_model(role="critic").generate("Is it fair?")
        return Score(value="C")

    return score


@scorer(metrics=[accuracy()])
def asks_the_critic() -> Scorer:
    """One role, but not the grader role assembly binds."""

    async def score(state: TaskState, target: Target) -> Score:
        await get_model(role="critic").generate("Is it fair?")
        return Score(value="C")

    return score


def test_a_scorer_asking_two_roles_is_refused_because_the_second_would_go_unbound() -> None:
    """The old reader kept roles[0] only, so a human pinned the grader and the critic role
    graded with the Candidate's own model."""

    with pytest.raises(ImporterError, match=r"asks_two_roles asks for the model role\(s\) "):
        _scorer_facts(_one_sample_task(asks_two_roles()), sys.modules[__name__])


def test_a_scorer_asking_a_role_other_than_grader_is_refused() -> None:
    with pytest.raises(
        ImporterError, match=r"asks_the_critic asks for the model role\(s\) 'critic'"
    ):
        _scorer_facts(_one_sample_task(asks_the_critic()), sys.modules[__name__])


def test_a_scorer_the_reader_cannot_find_is_refused_because_unread_is_not_judge_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before, a scorer whose source the reader could not find read as judge-free, and the
    row landed with no judge bound (sciknoweval's shape reads the same way)."""

    import screamingface_engine_inspect.importer as importer_module

    monkeypatch.setattr(
        importer_module, "judge_shape", lambda _reference: JudgeShape(unread=("no source",))
    )

    with pytest.raises(ImporterError, match=r"exact could not be read in full \(no source\)"):
        _scorer_facts(_one_sample_task(exact()), sys.modules[__name__])


def test_a_judge_parameter_left_at_its_default_renders_the_todo_judge() -> None:
    """niah's shape used to render a judge-free row that only failed later, in CI's
    assembly lane; the TODO judge fails it by name the moment it is reviewed."""

    rows: TaskReplayRows = _rows(_facts(scorer=f"{__name__}:judged_by_default", scorer_kwargs={}))

    assert 'judge=JudgeSpec(model="TODO"),' in rows.benchmark


# --- OME-1602: an extra scorer the importing agent leaves out by name ---


def _stereoset_task() -> Any:
    """stereoset's two scorers on a stand-in dataset, as its real Task declares them."""

    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample

    stereoset_module = importlib.import_module("inspect_evals.stereoset.stereoset")

    return Task(
        dataset=MemoryDataset([Sample(input="q", target=["A"], choices=["x", "y", "z"])]),
        scorer=[stereoset_module.multiple_choice_scorer(), stereoset_module.stereoset_scorer()],
    )


def test_an_extra_scorer_dropped_by_name_is_a_named_deviation_on_the_row() -> None:
    """stereoset's bias score runs a whole-run metric no Named Score column can carry, so the
    import refuses it as an extra scorer; the owner chose to leave it out by name instead
    (OME-1602), and the row then shows the drop."""

    stereoset_module = importlib.import_module("inspect_evals.stereoset.stereoset")

    with pytest.raises(ImporterError, match="stereotype_score"):
        _scorer_facts(_stereoset_task(), stereoset_module)

    facts: ScorerFacts = _scorer_facts(
        _stereoset_task(), stereoset_module, drop_scorers=("stereoset_scorer",)
    )

    # One scorer left grades like a single-scorer row: no lone Named Score, which would tell
    # the grader to expect a dict and fail every Case on the scorer's plain "C".
    assert facts.named_scores == ()
    assert facts.scorer == "inspect_evals.stereoset.stereoset:multiple_choice_scorer"
    assert facts.dropped_scorers == ("stereoset_scorer",)


@pytest.mark.parametrize(
    ("name", "reason"),
    [("multiple_choice_scorer", "headline scorer"), ("bias_scorer", "declares no scorer")],
)
def test_the_headline_or_an_unknown_name_cannot_be_dropped(name: str, reason: str) -> None:
    """Dropping the headline would grade by something else under the eval's name; a name the
    Task does not declare is a typo that would otherwise drop nothing silently."""

    stereoset_module = importlib.import_module("inspect_evals.stereoset.stereoset")

    with pytest.raises(ImporterError, match=reason):
        _scorer_facts(_stereoset_task(), stereoset_module, drop_scorers=(name,))


def test_a_scorer_already_dropped_as_judged_cannot_be_dropped_again_by_name() -> None:
    """A --drop-scorer that names a scorer the import already left out would read as a
    decision with no effect; it is refused so the flag always means what it says."""

    task: Task = Task(
        dataset=MemoryDataset([Sample(input="q", target="a")]),
        scorer=[asks_the_grader(), exact()],
    )

    with pytest.raises(ImporterError, match="already left out"):
        _scorer_facts(task, sys.modules[__name__], drop_scorers=("asks_the_grader",))
