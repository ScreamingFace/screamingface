# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer's per-Benchmark choice for a whole-run metric that is not a mean (OME-1527).

FEATURE: whole-run metrics (R1, R2 "honour"). A scorer marks each Case; its metrics tally
the whole run, and a Task-level ``metrics=[...]`` replaces each scorer's whole-run metric
list (per-Case marking is untouched). When the headline metric is not a plain mean, the
importing agent chooses per Benchmark:

- ``--whole-run-metric honour`` writes the metric's reference on the row, so the run is
  scored with it (refused by name for what the tally cannot run);
- ``--whole-run-metric mean`` keeps the mean and writes a ``# NAMED DEVIATION:`` line
  naming the eval's metric; the row's fields, and so its revision, are what they were.

INVARIANT: with no choice the import is still refused, so nothing publishes the mean under
the eval's name by accident. The five published rows that stopped importing in 0ba6587f1
(xstest_safe/unsafe, coconot_original/contrast, bbeh) import again with ``mean``.
"""

from __future__ import annotations

import importlib
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai import Epochs, Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import (  # noqa: E402
    Metric,
    SampleScore,
    accuracy,
    grouped,
    match,
    metric,
    stderr,
)
from test_importer_refuses_task_metrics import fake_eval  # noqa: E402, F401 — the fixture

from screamingface_engine_inspect import importer as importer_module  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402
from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
    _facts_of,
    replay_for_import,
)
from screamingface_engine_inspect.importer import (  # noqa: E402
    ImporterError,
    WholeRunMetricChoice,
    main,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from screamingface_engine_inspect.task_replay_rows import render_task_replay_rows  # noqa: E402

_SCORERS: Any = importlib.import_module("inspect_ai.scorer")


def _module(name: str) -> Any:
    """One inspect_evals module by dotted name."""

    return importlib.import_module(f"inspect_evals.{name}")


def _task(metrics: list[Any], epochs: Epochs | None = None) -> Task:
    """A one-Sample exact-match Task declaring these Task-level metrics; nothing is fetched."""

    return Task(
        dataset=MemoryDataset([Sample(input="q", target="a")]),
        scorer=match(),
        metrics=metrics,
        epochs=epochs,
    )


def _facts(task: Task, choice: WholeRunMetricChoice | None) -> TaskReplayFacts:
    """The facts the import child reads off a built Task, with the agent's choice."""

    return _facts_of(task, _SCORERS, "inspect_evals.probe:task", None, False, choice)


def _row(facts: TaskReplayFacts) -> tuple[str, BenchmarkSpec]:
    """The rendered BenchmarkSpec row, as text and evaluated the way benchmarks.py would."""

    imported: TaskReplayImport = TaskReplayImport(
        declaration=TaskReplayCasesSpec(task=facts.task_ref, case_count=1, case_digest="e" * 64),
        case_sources=(CaseSource("url", "https://example.org/probe.jsonl", "unpinned"),),
        facts=facts,
    )
    text: str = render_task_replay_rows("probe", imported, "TODO").benchmark
    namespace: dict[str, Any] = {"BenchmarkSpec": BenchmarkSpec, "JudgeSpec": JudgeSpec}
    exec("declared = (\n" + text + ")", namespace)  # noqa: S102 — our own rendered row
    return text, namespace["declared"][0]


# ── 1. keep the mean: the five published rows import again ───────────────────────────────


def _xstest() -> list[Any]:
    return [_module("xstest.xstest").refusal_rate()]


def _coconot() -> list[Any]:
    return [_module("coconot.coconot").compliance_rate()]


def _bbeh() -> list[Any]:
    return [
        grouped(accuracy(), group_key="task", all=False),
        _module("bbeh.bbeh").harmonic_mean_across_tasks(),
    ]


#: (published row keys, the eval's own metrics as PR #1323 pins them, the headline's name).
_FIVE: list[tuple[tuple[str, ...], Callable[[], list[Any]], str]] = [
    (("xstest_safe", "xstest_unsafe"), _xstest, "refusal_rate"),
    (("coconot_original", "coconot_contrast"), _coconot, "compliance_rate"),
    (("bbeh",), _bbeh, "grouped"),
]


@pytest.mark.parametrize(("keys", "metrics", "headline"), _FIVE, ids=[c[2] for c in _FIVE])
def test_keeping_the_mean_imports_a_published_row_with_its_fields_unchanged(
    keys: tuple[str, ...], metrics: Callable[[], list[Any]], headline: str
) -> None:
    """The choice adds a comment and no field, so the published rows' revisions hold."""

    text, row = _row(_facts(_task(metrics()), "mean"))

    assert f"# NAMED DEVIATION: the eval scores the whole run with {headline};" in text
    assert row.whole_run_metric is None
    # INVARIANT: the deviation is said once, never also as a review TODO.
    assert f"its own metric inspect_evals/{headline}" not in text
    for key in keys:
        published: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == key)
        assert published.whole_run_metric is None


def test_the_import_child_carries_the_choice(fake_eval: str) -> None:  # noqa: F811
    replay = replay_for_import(f"{fake_eval}:rate_like_task", None, whole_run_metric="mean")

    assert replay.facts.mean_instead_of == "rate_like"
    assert replay.facts.whole_run_metric is None


def test_with_no_choice_the_refusal_names_both_choices() -> None:
    with pytest.raises(ImporterError, match="--whole-run-metric honour.*--whole-run-metric mean"):
        _facts(_task(_xstest()), None)


def test_a_choice_on_a_plain_mean_headline_is_refused() -> None:
    # WHY: a flag that changes nothing would still read, in the command history, as a decision.
    with pytest.raises(ImporterError, match="headline is already a plain mean"):
        _facts(_task([accuracy(), stderr()]), "mean")


# ── 2. honour: the row names the metric, or the importer says why it cannot ──────────────


def test_honouring_writes_the_metrics_reference_and_a_review_todo() -> None:
    text, row = _row(_facts(_task(_xstest()), "honour"))

    # WHY behind a gate: a Headline Score is higher-is-better up to 1, xstest's rate is 0..100
    # and lower is better on xstest_safe, and inspect metrics declare neither. Assembly
    # refuses the prefix, so only a reviewer deleting it can ship the row.
    assert row.whole_run_metric == "TODO:inspect_evals.xstest.xstest:refusal_rate"
    assert "# TODO(review): confirm refusal_rate is higher-is-better up to 1" in text
    assert "NAMED DEVIATION" not in text


def test_honouring_keeps_the_sample_metadata_the_metric_may_read() -> None:
    """WHY: under one of inspect's own scorers the importer drops the Sample metadata, but an
    honoured metric may read it (an F1 over "has a clause"); without it the metric reads an
    empty dict and crashes, or a ``.get(key, default)`` publishes a wrong number."""

    hle: Any = _module("hle.scorers")

    honoured: TaskReplayFacts = _facts(_task(list(hle.HLE_METRICS)), "honour")
    kept_mean: TaskReplayFacts = _facts(_task(list(hle.HLE_METRICS)), "mean")

    assert honoured.keep_sample_metadata is True
    # INVARIANT: keeping the mean shapes no Case, so a published row's Case Digest holds.
    assert kept_mean.keep_sample_metadata is False


@metric(scores="unreduced")
def raw_rate() -> Metric:
    """A metric that reads each Sample's raw Score, as inspect's ``frequency`` does."""

    def compute(scores: list[SampleScore]) -> float:
        return 0.0

    return compute


def test_honouring_a_metric_asking_for_unreduced_scores_is_refused_by_name() -> None:
    with pytest.raises(ImporterError, match="cannot honour raw_rate: it asks for unreduced"):
        _facts(_task([raw_rate()]), "honour")


def test_honouring_a_metric_built_with_arguments_is_refused_by_name() -> None:
    """bbeh's headline is inspect's grouped(accuracy(), group_key="task"): the row can name a
    constructor, not the metric object it was built with."""

    with pytest.raises(ImporterError, match="cannot honour grouped: .*created with arguments"):
        _facts(_task(_bbeh()), "honour")


def test_honouring_a_task_with_its_own_reducer_is_refused_by_name() -> None:
    """coconot reduces each Sample with its own word map; the tally replays inspect's default
    mean only, so the metric would read numbers the eval never made."""

    coconot: Any = _module("coconot.coconot")
    reducer: Any = _SCORERS.mean_score(value_to_float=coconot.original_compliance_value_to_float())

    with pytest.raises(ImporterError, match="its own epoch reducer mean"):
        _facts(_task(_coconot(), Epochs(1, reducer)), "honour")


def test_hle_headline_is_honourable_but_its_own_reducer_is_not() -> None:
    """HLE (OME-1457): its headline is its own ``accuracy``, which the row can name; its Task
    reduces with ``attempt_preserving_mean``, which the tally does not replay yet."""

    hle: Any = _module("hle.scorers")
    metrics: Any = _module("hle.metrics")

    honoured: TaskReplayFacts = _facts(_task(list(hle.HLE_METRICS)), "honour")
    assert honoured.whole_run_metric == "inspect_evals.hle.metrics:accuracy"
    with pytest.raises(ImporterError, match="attempt_preserving_mean"):
        _facts(_task(list(hle.HLE_METRICS), Epochs(1, metrics.attempt_preserving_mean())), "honour")


# ── 3. the command ───────────────────────────────────────────────────────────────────────

_SRC_DIR: Path = Path(importer_module.__file__).resolve().parent


def test_the_flag_reaches_the_import(tmp_path: Path) -> None:
    for name in ("prepare.py", "benchmarks.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    calls: list[Mapping[str, Any]] = []

    def recording(task_ref: str, task_args: Mapping[str, Any] | None, **options: Any) -> Any:
        calls.append(options)
        raise ImporterError("stop after recording")

    code: int = main(
        ["inspect_evals.xstest.xstest:xstest", "--key", "x", "--whole-run-metric", "mean"]
        + ["--engine-src", str(tmp_path)],
        import_by_task_replay=recording,
    )

    assert code == 1
    assert calls[0]["whole_run_metric"] == "mean"
