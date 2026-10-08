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
    # row would pin the wrong configuration as faithful ("1,889" grades C upstream, I here).
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
