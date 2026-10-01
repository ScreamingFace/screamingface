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
    _custom_metrics,
    _scorer_reference,
    _solver_facts,
)
from screamingface_engine_inspect.prepare import PreparedCase, TaskReplayCasesSpec, case_records
from screamingface_engine_inspect.task_replay import (
    TASK_REPLAY_TIMEOUT_SECONDS,
    TaskReplayError,
    _failure_reason,
    _log_child_stderr,
    replay_environment,
)

#: The digest the import child's spec carries: nothing compares it (replayed_cases never does).
UNSEALED_DIGEST: str = "0" * 64

#: inspect's own scorers live here; none of them reads the Sample metadata (D11).
_INSPECT_SCORER_PREFIX: str = "inspect_ai.scorer:"


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
    timeout: float = TASK_REPLAY_TIMEOUT_SECONDS,
) -> ImportReplay:
    """Run the import child once and read back Cases, Case Sources and facts.

    Args:
        task_ref: ``"module:attr"`` of the eval's task function.
        task_args: forwarded to the task function; None for none.
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
    task: Any, module: Any, task_ref: str, task_args: dict[str, Any] | None
) -> TaskReplayFacts:
    """Stage 3a — read the built Task with the Hugging Face reader's own readers."""

    template_ref, choice_ref, system_ref, custom, uses_multiple_choice = _solver_facts(
        task, module, task_ref
    )
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
    )


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
    facts: TaskReplayFacts = _facts_of(task, module, task_ref, task_args)
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref,
        case_count=0,
        case_digest=UNSEALED_DIGEST,
        task_args=task_args,
        prompt_template=facts.prompt_template,
        choice_template=facts.choice_template,
        system_message=facts.system_message,
        keep_sample_metadata=facts.keep_sample_metadata,
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


__all__ = [
    "UNSEALED_DIGEST",
    "ImportReplay",
    "TaskReplayFacts",
    "replay_for_import",
]


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, run via replay_for_import
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]))
