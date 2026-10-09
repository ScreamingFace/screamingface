# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Pin how the importer treats a Task's own ``metrics=[...]`` today (OME-1527, PR 1 of 20).

FEATURE: Imported Benchmarks, whole-run metrics. An inspect Task may score the whole run
with its own metric, declared on the Task (xstest: ``Task(metrics=[refusal_rate()])``). A
Benchmark publishes the mean of its Cases.

Mental model: a scorer marks each Case; its metrics tally the whole run. When inspect builds
the Task it REPLACES each scorer's whole-run metric list with the Task's ``metrics=[...]``
(per-Case marking is untouched), so the importer's scorer-level headline check already sees
Task-level metrics. Three
invariants follow, each pinned below with the published Benchmarks' own declarations:

1. A Task-level headline that is not a plain mean (xstest, coconot, bbeh) is refused, so its
   mean is never published under the eval's name.
2. A plain mean plus a ``stderr`` (race_h, mgsm_en, squad) imports.
3. A plain-mean headline with extra metrics (worldsense) imports, and each extra is written
   once, as a "not reproduced" note, never also as a review TODO.

AIDEV-NOTE: xstest_safe/unsafe, coconot_original/contrast and bbeh have not been
re-importable since 0ba6587f1 (2026-10-07). OME-1527 PR #2 (R1) gives them a per-row choice:
honour the eval's metric, or keep the mean under a Named Deviation. Their published rows and
revisions must not move.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import accuracy, grouped, match, mean, stderr  # noqa: E402

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
    _facts_of,
    replay_for_import,
)
from screamingface_engine_inspect.importer import ImporterError  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay import TaskReplayError  # noqa: E402
from screamingface_engine_inspect.task_replay_rows import (  # noqa: E402
    TaskReplayRows,
    render_task_replay_rows,
)

_SCORERS: Any = importlib.import_module("inspect_ai.scorer")


def _module(name: str) -> Any:
    """One inspect_evals module by dotted name (its package re-exports the task function
    under the module's own name, so attribute access would return the function)."""

    return importlib.import_module(f"inspect_evals.{name}")


def _task_with(metrics: list[Any]) -> Task:
    """A one-Sample exact-match Task declaring these Task-level metrics; nothing is fetched.

    WHY a stand-in Task with the eval's real metric objects: calling the eval's task function
    downloads its dataset; each case below also checks the eval's source declares exactly
    this list, so the stand-in cannot drift from the pinned inspect_evals.
    """

    return Task(
        dataset=MemoryDataset([Sample(input="q", target="a")]), scorer=match(), metrics=metrics
    )


def _facts(task: Task, task_ref: str) -> TaskReplayFacts:
    """The facts the import child reads off a built Task (its Stage 3a, in-process)."""

    return _facts_of(task, _SCORERS, task_ref, None, False)


# ── 1. a Task-level non-mean headline is refused ─────────────────────────────────────────


def _xstest() -> list[Any]:
    return [_module("xstest.xstest").refusal_rate()]


def _coconot() -> list[Any]:
    return [_module("coconot.coconot").compliance_rate()]


def _bbeh() -> list[Any]:
    return [
        grouped(accuracy(), group_key="task", all=False),
        _module("bbeh.bbeh").harmonic_mean_across_tasks(),
    ]


#: (eval module, text its Task declaration contains, the eval's metrics rebuilt, the
#: headline metric the refusal names).
_REFUSED: list[tuple[str, str, Callable[[], list[Any]], str]] = [
    ("xstest.xstest", "metrics=[refusal_rate()]", _xstest, "refusal_rate"),
    ("coconot.coconot", "metrics=[compliance_rate()]", _coconot, "compliance_rate"),
    ("bbeh.bbeh", "harmonic_mean_across_tasks(),  # harmonic mean across tasks", _bbeh, "grouped"),
]


@pytest.mark.parametrize(
    ("module", "declared", "metrics", "headline"), _REFUSED, ids=[c[0] for c in _REFUSED]
)
def test_a_task_level_headline_that_is_not_a_mean_is_never_published_as_the_mean(
    module: str, declared: str, metrics: Callable[[], list[Any]], headline: str
) -> None:
    """xstest's refusal rate, coconot's compliance rate and bbeh's per-task grouping are
    not the mean of the Cases; importing them as-is would publish the wrong number."""

    assert declared in inspect.getsource(_module(module))

    with pytest.raises(ImporterError, match=f"headline metric {headline} "):
        _facts(_task_with(metrics()), f"inspect_evals.{module}:task")


def test_the_refusal_says_task_metrics_reach_it_and_where_whole_run_metrics_land() -> None:
    """The old message said "declare a reducer (OME-1268)"; OME-1268 shipped multi-score
    boards, not reducers, so the pointer led nowhere."""

    with pytest.raises(ImporterError) as refused:
        _facts(_task_with(_xstest()), "inspect_evals.xstest.xstest:xstest")

    message: str = str(refused.value)
    assert "OME-1527 (R1)" in message
    assert "Task-level metrics=[...]" in message
    assert "OME-1268" not in message
    assert "reducer" not in message


#: A stand-in eval whose Task declares a whole-run rate (xstest's shape) on an exact-match
#: scorer. It proves inspect's swap of the scorer's metric list happens in the real import
#: child too, not how any real eval loads its Samples.
FAKE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Task, task
    from inspect_ai.dataset import FieldSpec, json_dataset
    from inspect_ai.scorer import match, metric

    DATA = os.environ["FAKE_TASK_METRICS_DATA"]

    @metric
    def rate_like():
        def compute(scores):
            return 100.0 * sum(s.score.as_float() == 0 for s in scores) / len(scores)
        return compute

    @task
    def rate_like_task() -> Task:
        return Task(dataset=json_dataset(DATA, FieldSpec(input="q", target="a", id="id")),
                    scorer=match(), metrics=[rate_like()])
    """
)


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the import child can import it; return its module name."""

    (tmp_path / "fake_task_metrics_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    (tmp_path / "cases.jsonl").write_text(
        json.dumps({"id": 1, "q": "What is 6 times 7?", "a": "42"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_TASK_METRICS_DATA", str(tmp_path / "cases.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_task_metrics_eval"


def test_the_import_child_refuses_a_task_level_rate_too(fake_eval: str) -> None:
    with pytest.raises(TaskReplayError, match="headline metric rate_like "):
        replay_for_import(f"{fake_eval}:rate_like_task", None)


# ── 2. a plain mean plus a stderr imports ────────────────────────────────────────────────

#: race_h, mgsm_en and squad declare a plain mean plus a clustered stderr at Task level.
_IMPORTED: list[tuple[str, str, Callable[[], list[Any]]]] = [
    (
        "race_h.race_h",
        'metrics=[accuracy(), stderr(cluster="article_hash")]',
        lambda: [accuracy(), stderr(cluster="article_hash")],
    ),
    (
        "mgsm.mgsm",
        'metrics=[accuracy(), stderr(cluster="question_id")]',
        lambda: [accuracy(), stderr(cluster="question_id")],
    ),
    (
        "squad.squad",
        'metrics=[mean(), stderr(cluster="context_hash")]',
        lambda: [mean(), stderr(cluster="context_hash")],
    ),
]


@pytest.mark.parametrize(
    ("module", "declared", "metrics"), _IMPORTED, ids=[c[0] for c in _IMPORTED]
)
def test_a_task_level_plain_mean_with_a_clustered_stderr_imports_with_nothing_dropped(
    module: str, declared: str, metrics: Callable[[], list[Any]]
) -> None:
    # WHY stderr's arguments do not matter: a standard error is a confidence figure beside
    # the mean, never the number published.
    assert declared in inspect.getsource(_module(module))

    facts: TaskReplayFacts = _facts(_task_with(metrics()), f"inspect_evals.{module}:task")

    assert facts.scorer == "inspect_ai.scorer:match"
    assert facts.dropped_metrics == ()


# ── 3. extra metrics after a plain-mean headline are noted once ──────────────────────────

_WORLDSENSE_TASK: str = "inspect_evals.worldsense.worldsense:worldsense"


def _worldsense_rows() -> TaskReplayRows:
    """worldsense's Task-level metrics through the child's fact reader and the row renderer."""

    worldsense: Any = _module("worldsense.worldsense")
    assert "metrics=[accuracy(), stderr(), ws_accuracy(), ws_bias()]" in inspect.getsource(
        worldsense
    )
    facts: TaskReplayFacts = _facts(
        _task_with([accuracy(), stderr(), worldsense.ws_accuracy(), worldsense.ws_bias()]),
        _WORLDSENSE_TASK,
    )
    imported: TaskReplayImport = TaskReplayImport(
        declaration=TaskReplayCasesSpec(task=_WORLDSENSE_TASK, case_count=1, case_digest="e" * 64),
        case_sources=(CaseSource("url", "https://example.org/worldsense.jsonl", "unpinned"),),
        facts=facts,
    )
    return render_task_replay_rows("worldsense_again", imported, "TODO")


def test_extra_task_level_metrics_after_a_plain_mean_import_as_not_reproduced_notes() -> None:
    row: str = _worldsense_rows().benchmark

    assert "# The eval also reports ws_accuracy; the Benchmark reports each" in row
    assert "# The eval also reports ws_bias; the Benchmark reports each" in row


def test_a_noted_metric_is_not_also_left_as_a_review_todo() -> None:
    # WHY: the note already names the deviation; a TODO beside it asks for it twice, and a
    # reviewer resolving one may leave the other behind.
    row: str = _worldsense_rows().benchmark

    assert "its own metric inspect_evals/ws_accuracy" not in row
    assert "its own metric inspect_evals/ws_bias" not in row


def test_a_task_level_metric_with_no_note_keeps_its_review_todo() -> None:
    # INVARIANT: only a duplicate goes; stderr is never a dropped metric, so its TODO is the
    # one place the row says the eval's stderr is not reported.
    row: str = _worldsense_rows().benchmark

    assert "its own metric inspect_ai/stderr" in row
