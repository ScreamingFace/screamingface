# pyright: reportMissingImports=false
# WHY file-level: the child half imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Import-mode Task replay: the runs the importer makes before it writes a declaration (OME-1273).

FEATURE: Task-replay Imported Benchmarks (spec R2–R4). The image side (task_replay.py)
replays a DECLARATION it already has. The importer has none yet: it needs the Cases, where
they came from, and the scorer facts of the built Task, all from one clean child. This module
is that child and its parent-side call. It never calls inspect's ``eval()``: no model, scorer
or Judge runs; the Task's own solvers run only up to their first ``generate``, by capture.

Stages of ``replay_for_import``, in execution order:

    Stage 1 — parent: write request.json (task, args, cache root); build the clean-room
              environment exactly as the image side does (replay_environment).
    Stage 2 — child: import the task module, THEN install the Case Source recorder, so a
              name the module bound at import (`from inspect_ai.util import download`) is
              rebound too; call the task function with its args. The recorder learns the
              Hub commits (no pins exist yet) and forces the dev's seeds (OME-1460).
    Stage 3 — child: read the facts off the built Task with the importer's own readers
              (_scorer_facts, _custom_metrics, plus the multiple_choice witness); render
              the Samples by capture (the Task's own solvers with a stand-in generate).
    Stage 4 — child: write result.json: prepared Cases, Sample ids, Case Sources, the Hub
              fetches (repo, revision read), facts.
              WHY a file: evals print while they load.
    Stage 5 — parent: a non-zero exit, a timeout or an unreadable result is a
              TaskReplayError carrying the child's final error line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import Any

from screamingface_engine_inspect.capture import captured_case_records
from screamingface_engine_inspect.case_set import case_set_digest
from screamingface_engine_inspect.case_sources import RENDER_PHASE, CaseSource, CaseSourceRecorder
from screamingface_engine_inspect.fetch_pins import (
    FetchPinError,
    FetchPins,
    HubPins,
    source_pins_of,
)
from screamingface_engine_inspect.importer import (
    ImporterError,
    ScorerFacts,
    WholeRunMetricChoice,
    _custom_metrics,
    _hub_dataset_info,
    _refuse_several_epochs,
    _scorer_facts,
    _solver_list,
)
from screamingface_engine_inspect.prepare import (
    INSPECT_SCORER_PREFIX,
    PreparedCase,
    TaskReplayCasesSpec,
    case_digest,
)
from screamingface_engine_inspect.task_replay import (
    TASK_REPLAY_TIMEOUT_SECONDS,
    TaskReplayError,
    _failure_reason,
    _log_child_stderr,
    replay_environment,
    replayed_cases,
)

#: The digest the import child's spec carries: nothing compares it (replayed_cases never does).
UNSEALED_DIGEST: str = "0" * 64


@dataclass(frozen=True)
class TaskReplayFacts:
    """What the importer reads off the built Task: the scorer facts and the MCQ witness
    (spec R6). WHY no prompt facts: the Cases are captured from the Task's own solvers, so
    nothing here could describe the prompt better than they do."""

    task_ref: str
    task_args: dict[str, Any] | None
    mcq: bool
    scorer: str
    scorer_kwargs: dict[str, Any]
    custom_metrics: tuple[str, ...]
    keep_sample_metadata: bool
    #: The Named Scores declaration, read the Hugging Face reader's way (OME-1268).
    extra_scorers: tuple[str, ...] = ()
    named_scores: tuple[str, ...] = ()
    dropped_scorers: tuple[str, ...] = ()
    headline_differs: bool = False
    dropped_metrics: tuple[str, ...] = ()
    #: The importing agent's whole-run-metric choice, as the row writes it (OME-1527).
    whole_run_metric: str | None = None
    mean_instead_of: str | None = None


@dataclass(frozen=True)
class ImportReplay:
    """One import-mode run: the Cases, the upstream Sample ids, where they came from, and the
    Task's facts."""

    prepared: list[PreparedCase]
    sample_ids: tuple[str | None, ...]
    case_sources: tuple[CaseSource, ...]
    facts: TaskReplayFacts
    #: Every top-level Hub fetch as (repo id, revision it read), in call order (OME-1460).
    hub_fetches: tuple[tuple[str, str | None], ...] = ()
    #: The declared seeds some hf_dataset call needed ("shuffle_seed", "choice_shuffle_seed").
    seeds_applied: frozenset[str] = frozenset()


def replay_for_import(
    task_ref: str,
    task_args: Mapping[str, Any] | None,
    *,
    excluded_sample_ids: tuple[str, ...] | None = None,
    has_answer_key: bool = True,
    shuffle_seed: int | None = None,
    choice_shuffle_seed: int | None = None,
    keep_sample_metadata: bool = False,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
    whole_run_metric: WholeRunMetricChoice | None = None,
) -> ImportReplay:
    """Run the import child once and read back Cases, Case Sources and facts.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function; None for none.
        excluded_sample_ids: upstream Sample ids capture leaves out (spec R18); None for none.
        has_answer_key: False when the Benchmark has no answer key, so an empty one is
            accepted (spec R19).
        shuffle_seed: forced onto an ``hf_dataset`` row shuffle the eval makes without one.
        choice_shuffle_seed: forced onto a bare ``shuffle_choices=True``.
        keep_sample_metadata: keep the Sample metadata even under one of inspect's own
            scorers, because a Judge template reads it (coconot's rubric).
        timeout: seconds before a stalled replay is abandoned.
        whole_run_metric: the agent's choice for a headline metric that is not a plain mean,
            honour it or keep the mean (OME-1527); None refuses such a Task.

    Returns:
        The child's Cases (numbered 1..N by the shared writer), the upstream Sample ids in
        the same order (None for a Sample with no id), the recorded Case Sources and the facts.

    Raises:
        TaskReplayError: the child failed, timed out, or wrote an unreadable result.
    """

    # Stage 1 — request file + clean-room environment.
    with tempfile.TemporaryDirectory(prefix="task-replay-import-") as scratch:
        root: Path = Path(scratch)
        cache_root: Path = root / "cache"
        request_path: Path = root / "request.json"
        result_path: Path = root / "result.json"
        request: dict[str, Any] = {
            "task": task_ref,
            "task_args": dict(task_args) if task_args else None,
            "excluded_sample_ids": list(excluded_sample_ids) if excluded_sample_ids else None,
            "has_answer_key": has_answer_key,
            "shuffle_seed": shuffle_seed,
            "choice_shuffle_seed": choice_shuffle_seed,
            "keep_sample_metadata": keep_sample_metadata,
            "whole_run_metric": whole_run_metric,
            "cache_root": str(cache_root),
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        command: list[str] = [sys.executable, "-m", __name__, str(request_path), str(result_path)]
        try:
            completed: subprocess.CompletedProcess[str] = subprocess.run(  # noqa: S603 — argv is ours; no shell
                command,
                env=replay_environment(cache_root, os.environ),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log_child_stderr(task_ref, exc.stderr)
            raise TaskReplayError(f"{task_ref}: replay timed out after {timeout:g}s") from exc
        # Stage 5 — any failure is one named line; the tail goes to the log.
        if completed.returncode != 0 or not result_path.is_file():
            _log_child_stderr(task_ref, completed.stderr)
            raise TaskReplayError(
                f"{task_ref}: replay failed (exit {completed.returncode}): "
                f"{_failure_reason(completed.stderr)}"
            )
        try:
            result: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TaskReplayError(f"{task_ref}: replay wrote an unreadable result: {exc}") from exc
    return _import_replay_from_result(result)


def _import_replay_from_result(result: Mapping[str, Any]) -> ImportReplay:
    """Rebuild the typed run from result.json (JSON has lists where the facts keep tuples)."""

    raw_facts: dict[str, Any] = dict(result["facts"])
    # WHY each name: JSON has no tuple; every tuple-typed fact comes back as a list and the
    # frozen facts (and the pins hashed from them) must see the same type the child built.
    tuple_facts: tuple[str, ...] = (
        "custom_metrics",
        "extra_scorers",
        "named_scores",
        "dropped_scorers",
        "dropped_metrics",
    )
    facts: TaskReplayFacts = TaskReplayFacts(
        **{**raw_facts, **{name: tuple(raw_facts.get(name, ())) for name in tuple_facts}}
    )
    return ImportReplay(
        prepared=result["prepared"],
        sample_ids=tuple(result["sample_ids"]),
        case_sources=tuple(CaseSource(**source) for source in result["case_sources"]),
        facts=facts,
        hub_fetches=tuple((str(repo), revision) for repo, revision in result["hub_fetches"]),
        seeds_applied=frozenset(result["seeds_applied"]),
    )


def _facts_of(
    task: Any,
    module: Any,
    task_ref: str,
    task_args: dict[str, Any] | None,
    samples_carry_choices: bool,
    whole_run_metric: WholeRunMetricChoice | None = None,
) -> TaskReplayFacts:
    """Stage 3a — read the built Task with the importer's scorer readers; ``whole_run_metric``
    is the agent's choice for a non-mean headline (OME-1527)."""

    # WHY first: a Task that asks each Sample several times is refused before any of its
    # scorer facts are read (OME-1458).
    _refuse_several_epochs(task)
    scorers: ScorerFacts = _scorer_facts(task, module, whole_run_metric)
    return TaskReplayFacts(
        task_ref=task_ref,
        task_args=task_args,
        # INVARIANT: three MCQ witnesses — the multiple_choice solver,
        # OR the choice scorer (mmlu hides its solver inside its own @solver), OR Samples
        # that carry choices (worldsense asks for "1"/"2"/"3"
        # with generate() and a pattern scorer). Any of them refuses mid-run feedback (OME-796).
        mcq=_uses_multiple_choice(task) or scorers.scorer_name == "choice" or samples_carry_choices,
        scorer=scorers.scorer,
        scorer_kwargs=scorers.scorer_kwargs,
        custom_metrics=_custom_metrics(task),
        # WHY (D11): an eval's own scorer may read state.metadata (chembench), and the
        # metadata sits inside the Case Digest, so it is decided here, never by a hand edit.
        # An honoured whole-run metric may read it too (an F1 over "has a clause"), even
        # under one of inspect's own scorers (OME-1527); only an honour import moves.
        keep_sample_metadata=(
            not scorers.scorer.startswith(INSPECT_SCORER_PREFIX)
            or scorers.whole_run_metric is not None
        ),
        extra_scorers=scorers.extra_scorers,
        named_scores=scorers.named_scores,
        dropped_scorers=scorers.dropped_scorers,
        headline_differs=scorers.headline_differs,
        dropped_metrics=scorers.dropped_metrics,
        whole_run_metric=scorers.whole_run_metric,
        mean_instead_of=scorers.mean_instead_of,
    )


def _uses_multiple_choice(task: Any) -> bool:
    """Whether the Task's setup or solver chain holds inspect's multiple_choice solver.

    WHY only this witness: capture renders the prompt from the real chain, so nothing else
    about the solvers needs reading.
    """

    from inspect_ai._util.registry import registry_info

    pending: list[Any] = [*_solver_list(task.setup), *_solver_list(task.solver)]
    for solver in pending:
        name: str = registry_info(solver).name.rpartition("/")[2]
        if name == "chain" and hasattr(solver, "__iter__"):
            pending.extend(solver)
        elif name == "multiple_choice":
            return True
    return False


def _replay_in_this_process(request_path: Path, result_path: Path) -> None:
    """Stages 2 to 4 — the child's half."""

    request: dict[str, Any] = json.loads(request_path.read_text(encoding="utf-8"))
    task_ref: str = request["task"]
    task_args: dict[str, Any] | None = request["task_args"]
    module_name, _, attribute = task_ref.partition(":")
    module: Any = import_module(module_name)
    # Stage 2 — the recorder installs AFTER the import, so names bound at import are rebound.
    # It is never uninstalled: this process exists only for this one replay.
    recorder: CaseSourceRecorder = CaseSourceRecorder(Path(request["cache_root"]))
    # WHY source_pins=None: this run is where the Hub commits are learned (OME-1460); the
    # seeds are the dev's, known already, so they are forced here as in every later run.
    recorder.install(
        FetchPins(
            source_pins=None,
            shuffle_seed=request["shuffle_seed"],
            choice_shuffle_seed=request["choice_shuffle_seed"],
        )
    )
    task: Any = getattr(module, attribute)(**(task_args or {}))
    # WHY count here: every Case Source recorded from now on was fetched by a solver while
    # capture rendered a Sample, not by the loader; the row says so (CaseSource.phase).
    loaded: int = len(recorder.sources)
    samples: list[Any] = list(task.dataset)
    # Stage 3 — facts from the built Task, then the Cases by capture.
    facts: TaskReplayFacts = _facts_of(
        task,
        module,
        task_ref,
        task_args,
        any(sample.choices for sample in samples),
        request.get("whole_run_metric"),
    )
    if request["keep_sample_metadata"]:
        facts = replace(facts, keep_sample_metadata=True)
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=0,
        case_digest=UNSEALED_DIGEST,
        task_args=task_args,
        keep_sample_metadata=facts.keep_sample_metadata,
        has_answer_key=request["has_answer_key"],
        excluded_sample_ids=(
            None
            if request["excluded_sample_ids"] is None
            else tuple(request["excluded_sample_ids"])
        ),
    )
    prepared: list[PreparedCase] = captured_case_records(task, spec)
    sources: list[CaseSource] = [
        source if index < loaded else replace(source, phase=RENDER_PHASE)
        for index, source in enumerate(recorder.sources)
    ]
    # Stage 4 — one file back to the parent. WHY sample_ids: the writer numbers Cases 1..N,
    # so the upstream ids R4's duplicate check reads exist only here.
    result: dict[str, Any] = {
        "prepared": prepared,
        "sample_ids": [None if sample.id is None else str(sample.id) for sample in samples],
        "case_sources": [asdict(source) for source in sources],
        "hub_fetches": recorder.hub_fetches,
        "seeds_applied": sorted(recorder.seeds_applied),
        "facts": asdict(facts),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


@dataclass(frozen=True)
class TaskReplayImport:
    """What the importer writes from: the sealed declaration, its Case Sources and facts."""

    declaration: TaskReplayCasesSpec
    case_sources: tuple[CaseSource, ...]
    facts: TaskReplayFacts


def import_by_task_replay(
    task_ref: str,
    task_args: Mapping[str, Any] | None,
    *,
    excluded_sample_ids: tuple[str, ...] | None = None,
    has_answer_key: bool = True,
    shuffle_seed: int | None = None,
    choice_shuffle_seed: int | None = None,
    keep_sample_metadata: bool = False,
    dataset_info: Callable[[str, str | None], Any] | None = None,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
    whole_run_metric: WholeRunMetricChoice | None = None,
) -> TaskReplayImport:
    """Import one eval by Task replay: run 1 reads, the declaration is sealed, run 2 proves it.

    Think of it as printing the question booklet twice and checking both prints match before
    the booklet is filed. Stages, in execution order:

        Stage 1 — run 1, the import child: Cases, Sample ids, Case Sources, facts.
        Stage 2 — refuse by name (spec R4): the task raised; no Samples; Samples but no Case
                  Source; two Samples share an id (id-less Samples never collide).
        Stage 3 — seal: the declaration carries run 1's Case count and Case Digest, the one
                  fact that shapes a Case (keep_sample_metadata), the things only the
                  importing agent can say (which Sample ids to leave out, R18; that the
                  Benchmark has no answer key, R19; the seeds, D1), and, per Hub repo run 1
                  read, the commit the Hub resolves that revision to plus the Hub's gate
                  (OME-1460, :func:`~screamingface_engine_inspect.fetch_pins.source_pins_of`).
        Stage 4 — run 2, the IMAGE-SIDE child (task_replay.replayed_cases) on that
                  declaration: what every build will do, with the pins and seeds forced. A
                  different digest is refused: an unseeded shuffle the enforcer cannot reach
                  (a MemoryDataset.shuffle() in the eval's own code) would pass once and go
                  SKIPPED at every build; so is HEAD moving between the two runs.

    Example: the stand-in eval's two arithmetic Cases seal to one digest; its four-row
    unseeded shuffle seals to one order and replays to another 23 times in 24 → refused.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function in both runs; None for none.
        excluded_sample_ids: upstream Sample ids both runs leave out (R18); None for none.
        has_answer_key: False when the Benchmark has no answer key, in both runs (R19).
        shuffle_seed: the seed both runs force onto an unseeded ``hf_dataset`` row shuffle.
        choice_shuffle_seed: the seed both runs force onto a bare ``shuffle_choices=True``.
        keep_sample_metadata: keep the Sample metadata although the scorer is inspect's own,
            because a Judge template reads it; False lets the scorer decide (D11).
        dataset_info: ``(repo id, revision) → Hub dataset info`` (HfApi().dataset_info by
            default); injectable for tests.
        timeout: seconds before either run is abandoned.
        whole_run_metric: honour the eval's non-mean headline metric or keep the mean
            (OME-1527); None refuses such a Task. Run 1 reads it; it shapes no Case.

    Returns:
        The sealed declaration, the Case Sources run 1 recorded, and the Task's facts.

    Raises:
        ImporterError: one of the Stage 2 or Stage 4 refusals, named.
    """

    # Stage 1
    try:
        first: ImportReplay = replay_for_import(
            task_ref,
            task_args,
            excluded_sample_ids=excluded_sample_ids,
            has_answer_key=has_answer_key,
            shuffle_seed=shuffle_seed,
            choice_shuffle_seed=choice_shuffle_seed,
            keep_sample_metadata=keep_sample_metadata,
            timeout=timeout,
            whole_run_metric=whole_run_metric,
        )
    except TaskReplayError as exc:
        raise ImporterError(str(exc)) from exc
    # Stage 2
    _refuse_unsealable(task_ref, first)
    _refuse_inert_seeds(task_ref, first, shuffle_seed, choice_shuffle_seed)
    # Stage 3
    try:
        hub: HubPins = source_pins_of(
            first.hub_fetches, dataset_info=dataset_info or _hub_dataset_info
        )
    except FetchPinError as exc:
        raise ImporterError(f"{task_ref}: {exc}") from exc
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=len(first.prepared),
        case_digest=case_digest(first.prepared),
        # OME-1492: the order-blind seal, so a later reorder reads as "order only". Sealed
        # from run 1 like the Case Digest; run 2's matching digest proves it too.
        case_set_digest=case_set_digest(first.prepared),
        task_args=dict(task_args) if task_args else None,
        keep_sample_metadata=first.facts.keep_sample_metadata,
        has_answer_key=has_answer_key,
        excluded_sample_ids=excluded_sample_ids,
        source_pins=hub.source_pins,
        shuffle_seed=shuffle_seed,
        choice_shuffle_seed=choice_shuffle_seed,
        needs_hf_token=hub.needs_hf_token,
    )
    # Stage 4
    try:
        second: list[PreparedCase] = replayed_cases(declaration, timeout=timeout)
    except TaskReplayError as exc:
        raise ImporterError(str(exc)) from exc
    second_digest: str = case_digest(second)
    if second_digest != declaration.case_digest:
        raise ImporterError(
            f"{task_ref}: two Task replays produced different Cases (Case Digest "
            f"{declaration.case_digest[:12]}… then {second_digest[:12]}…) — an unseeded "
            "shuffle, generated Cases, or a per-run value such as a temp path in a Sample's "
            "metadata; pass task args that fix the order, e.g. --task-arg shuffle=False or "
            "--task-arg seed=42"
        )
    return TaskReplayImport(
        declaration=declaration, case_sources=first.case_sources, facts=first.facts
    )


def _refuse_inert_seeds(
    task_ref: str, first: ImportReplay, shuffle_seed: int | None, choice_shuffle_seed: int | None
) -> None:
    """Stage 2 — refuse a declared seed no hf_dataset call needed (OME-1460, R10): written on
    the row, it would promise an order nothing pins."""

    declared: dict[str, int | None] = {
        "shuffle_seed": shuffle_seed,
        "choice_shuffle_seed": choice_shuffle_seed,
    }
    for name, seed in declared.items():
        if seed is not None and name not in first.seeds_applied:
            raise ImporterError(
                f"{task_ref}: {name}={seed} was never applied — the eval makes no unseeded "
                "hf_dataset shuffle it would pin; leave it out"
            )


def _refuse_unsealable(task_ref: str, first: ImportReplay) -> None:
    """Stage 2 — the R4 refusals that need only run 1, each named."""

    if not first.prepared:
        raise ImporterError(f"{task_ref}: the task yielded no Samples")
    if not first.case_sources:
        raise ImporterError(
            f"{task_ref}: the task yielded {len(first.prepared)} Samples but no Case Source "
            "was recorded — a fetch nobody can see is a fetch nobody can review; the eval "
            "downloads through a primitive the recorder does not wrap"
        )
    seen: set[str] = set()
    for sample_id in first.sample_ids:
        # WHY skip None: inspect numbers id-less Samples itself at eval time.
        if sample_id is None:
            continue
        if sample_id in seen:
            raise ImporterError(f"{task_ref}: two Samples share the id {sample_id}")
        seen.add(sample_id)


__all__ = [
    "UNSEALED_DIGEST",
    "ImportReplay",
    "TaskReplayFacts",
    "TaskReplayImport",
    "import_by_task_replay",
    "replay_for_import",
]


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, run via replay_for_import
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]))
