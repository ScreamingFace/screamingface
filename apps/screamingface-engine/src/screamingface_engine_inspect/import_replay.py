# pyright: reportMissingImports=false
# WHY file-level: the child half imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Import-mode Task replay: the runs the importer makes before it writes a declaration (OME-1273).

FEATURE: Task-replay Imported Benchmarks (spec R2–R4). The image side (task_replay.py)
replays a DECLARATION it already has. The importer has none yet: it needs the Cases, where
they came from, and the solver and scorer facts of the built Task, all from one clean child.
This module is that child and its parent-side call. It never calls inspect's ``eval()``: no
solver, scorer, model or Judge runs.

Stages of ``replay_for_import``, in execution order:

    Stage 1 — parent: write request.json (task, args, cache root); build the clean-room
              environment exactly as the image side does (replay_environment).
    Stage 2 — child: import the task module, THEN install the Case Source recorder, so a
              name the module bound at import (`from inspect_ai.util import download`) is
              rebound too; call the task function with its args.
    Stage 3 — child: read the facts off the built Task with the importer's own readers
              (_solver_facts, _scorer_reference, _custom_metrics); render the Samples with
              the shared Case writer, using those facts.
    Stage 4 — child: write result.json: prepared Cases, Sample ids, Case Sources, facts.
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
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from screamingface_engine_inspect.case_sources import CaseSource, CaseSourceRecorder
from screamingface_engine_inspect.importer import (
    ImporterError,
    _custom_metrics,
    _scorer_reference,
    _solver_facts,
    _solver_list,
)
from screamingface_engine_inspect.prepare import (
    PreparedCase,
    TaskReplayCasesSpec,
    _resolve,
    case_digest,
    case_records,
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

#: inspect's own scorers live here; none of them reads the Sample metadata (D11).
_INSPECT_SCORER_PREFIX: str = "inspect_ai.scorer:"
#: The review flag the importer writes for a choice template no module attribute holds.
_UNPREPARED_TEMPLATE_FLAG: str = "(custom choice template is not prepared)"


@dataclass(frozen=True)
class TaskReplayFacts:
    """What the importer reads off the built Task: the prompt and scorer facts (spec R6)."""

    task_ref: str
    task_args: dict[str, Any] | None
    prompt_template: str | None
    choice_template: str | None
    system_message: str | None
    unreproduced_solvers: tuple[str, ...]
    mcq: bool
    scorer: str
    scorer_kwargs: dict[str, Any]
    custom_metrics: tuple[str, ...]
    keep_sample_metadata: bool
    #: False when the eval's own question lists the options (see TaskReplayCasesSpec).
    render_choices: bool = True


@dataclass(frozen=True)
class ImportReplay:
    """One import-mode run: the Cases, the upstream Sample ids, where they came from, and the
    Task's facts."""

    prepared: list[PreparedCase]
    sample_ids: tuple[str | None, ...]
    case_sources: tuple[CaseSource, ...]
    facts: TaskReplayFacts


def replay_for_import(
    task_ref: str,
    task_args: Mapping[str, Any] | None,
    *,
    choice_template: str | None = None,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
) -> ImportReplay:
    """Run the import child once and read back Cases, Case Sources and facts.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function; None for none.
        choice_template: ``"module:attr"`` of a constant holding the choice template the
            Task builds at run time (agieval); the child refuses it unless it equals the
            template the Task's multiple_choice solver holds. None to read the Task as is.
        timeout: seconds before a stalled replay is abandoned.

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
            "cache_root": str(cache_root),
            "choice_template": choice_template,
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
    facts: TaskReplayFacts = TaskReplayFacts(
        **{
            **raw_facts,
            "unreproduced_solvers": tuple(raw_facts["unreproduced_solvers"]),
            "custom_metrics": tuple(raw_facts["custom_metrics"]),
        }
    )
    return ImportReplay(
        prepared=result["prepared"],
        sample_ids=tuple(result["sample_ids"]),
        case_sources=tuple(CaseSource(**source) for source in result["case_sources"]),
        facts=facts,
    )


def _facts_of(
    task: Any,
    module: Any,
    task_ref: str,
    task_args: dict[str, Any] | None,
    choice_template: str | None,
) -> TaskReplayFacts:
    """Stage 3a — read the built Task with the Hugging Face reader's own readers."""

    template_ref, choice_ref, system_ref, custom, uses_multiple_choice = _solver_facts(
        task, module, task_ref
    )
    if choice_template is not None:
        choice_ref, custom = _verified_choice_template(task, choice_template, custom)
    scorer_ref, scorer_kwargs, scorer_name = _scorer_reference(task, module)
    return TaskReplayFacts(
        task_ref=task_ref,
        task_args=task_args,
        prompt_template=template_ref,
        choice_template=choice_ref,
        system_message=system_ref,
        unreproduced_solvers=custom,
        # INVARIANT: the same two MCQ witnesses as read_inspect_task — the multiple_choice
        # solver, OR the choice scorer (mmlu hides its solver inside its own @solver).
        mcq=uses_multiple_choice or scorer_name == "choice",
        scorer=scorer_ref,
        scorer_kwargs=scorer_kwargs,
        custom_metrics=_custom_metrics(task),
        # WHY (D11): an eval's own scorer may read state.metadata (chembench), and the
        # metadata sits inside the Case Digest, so it is decided here, never by a hand edit.
        keep_sample_metadata=not scorer_ref.startswith(_INSPECT_SCORER_PREFIX),
        # WHY only when nothing unreproduced runs: a solver we do not reproduce may render
        # the options itself (sad), and dropping them would lose part of the question.
        render_choices=uses_multiple_choice or scorer_name == "choice" or bool(custom),
    )


def _verified_choice_template(
    task: Any, reference: str, flags: tuple[str, ...]
) -> tuple[str, tuple[str, ...]]:
    """Accept a template constant only when it IS the template the Task's solver holds.

    WHY: some evals build their choice template at run time (agieval fills
    ``MULTIPLE_CHOICE_TEMPLATE_EN`` with an empty few-shot and CoT string), so no module
    attribute holds it and the Case would otherwise render with inspect's default wording.
    INVARIANT: the override can point at the eval's own wording, never invent a prompt.

    Returns:
        The reference, and the flags without the "template is not prepared" one it resolves.

    Raises:
        ImporterError: no multiple_choice solver holds a template, or it differs.
    """

    held: str | None = _held_choice_template(task)
    if held is None or _resolve(reference) != held:
        raise ImporterError(
            f"choice template {reference} does not equal the template the Task's "
            f"multiple_choice solver holds ({held!r})"
        )
    return reference, tuple(flag for flag in flags if not flag.endswith(_UNPREPARED_TEMPLATE_FLAG))


def _held_choice_template(task: Any) -> str | None:
    """The template the Task's multiple_choice solver was built with, if it has one."""

    from inspect_ai._util.registry import registry_info, registry_params

    solvers: list[Any] = [*_solver_list(task.setup), *_solver_list(task.solver)]
    for solver in solvers:
        name: str = registry_info(solver).name.rpartition("/")[2]
        if name == "chain" and hasattr(solver, "__iter__"):
            solvers.extend(solver)  # a solver list is one chain; its links hold the facts
        elif name == "multiple_choice":
            return registry_params(solver).get("template")
    return None


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
    recorder.install()
    task: Any = getattr(module, attribute)(**(task_args or {}))
    # Stage 3 — facts from the built Task, then the Cases through the shared writer.
    facts: TaskReplayFacts = _facts_of(
        task, module, task_ref, task_args, request.get("choice_template")
    )
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=0,
        case_digest=UNSEALED_DIGEST,
        task_args=task_args,
        prompt_template=facts.prompt_template,
        choice_template=facts.choice_template,
        system_message=facts.system_message,
        keep_sample_metadata=facts.keep_sample_metadata,
        render_choices=facts.render_choices,
    )
    samples: list[Any] = list(task.dataset)
    prepared: list[PreparedCase] = case_records(samples, spec)
    # Stage 4 — one file back to the parent. WHY sample_ids: the writer numbers Cases 1..N,
    # so the upstream ids R4's duplicate check reads exist only here.
    result: dict[str, Any] = {
        "prepared": prepared,
        "sample_ids": [None if sample.id is None else str(sample.id) for sample in samples],
        "case_sources": [asdict(source) for source in recorder.sources],
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
    choice_template: str | None = None,
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
) -> TaskReplayImport:
    """Import one eval by Task replay: run 1 reads, the declaration is sealed, run 2 proves it.

    Think of it as printing the question booklet twice and checking both prints match before
    the booklet is filed. Stages, in execution order:

        Stage 1 — run 1, the import child: Cases, Sample ids, Case Sources, facts.
        Stage 2 — refuse by name (spec R4): the task raised; no Samples; Samples but no Case
                  Source; two Samples share an id (id-less Samples never collide).
        Stage 3 — seal: the declaration carries run 1's Case count and Case Digest, plus the
                  facts that shape a Case (templates, keep_sample_metadata).
        Stage 4 — run 2, the IMAGE-SIDE child (task_replay.replayed_cases) on that
                  declaration: what every build will do. A different digest is refused: an
                  unseeded shuffle would pass once and go SKIPPED at every build.

    Example: the stand-in eval's two arithmetic Cases seal to one digest; its four-row
    unseeded shuffle seals to one order and replays to another 23 times in 24 → refused.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function in both runs; None for none.
        choice_template: a verified choice-template constant (see replay_for_import); the
            sealed declaration points at it, so run 2 renders with it too.
        timeout: seconds before either run is abandoned.

    Returns:
        The sealed declaration, the Case Sources run 1 recorded, and the Task's facts.

    Raises:
        ImporterError: one of the Stage 2 or Stage 4 refusals, named.
    """

    # Stage 1
    try:
        first: ImportReplay = replay_for_import(
            task_ref, task_args, choice_template=choice_template, timeout=timeout
        )
    except TaskReplayError as exc:
        raise ImporterError(str(exc)) from exc
    # Stage 2
    _refuse_unsealable(task_ref, first)
    # Stage 3
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=len(first.prepared),
        case_digest=case_digest(first.prepared),
        task_args=dict(task_args) if task_args else None,
        prompt_template=first.facts.prompt_template,
        choice_template=first.facts.choice_template,
        system_message=first.facts.system_message,
        keep_sample_metadata=first.facts.keep_sample_metadata,
        render_choices=first.facts.render_choices,
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
            "shuffle or generated Cases; pass task args that fix the order, e.g. "
            "--task-arg shuffle=False or --task-arg seed=42"
        )
    return TaskReplayImport(
        declaration=declaration, case_sources=first.case_sources, facts=first.facts
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
