# pyright: reportMissingImports=false
# WHY file-level: the child half imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Task replay: fetch an Imported Benchmark's Cases by calling the eval's own task function.

FEATURE: Task-replay Imported Benchmarks (OME-1273) — evals whose Cases the importer cannot
see come from the eval's own loading code, pinned by a Case Digest.

Think of it as asking the eval to print its question booklet in a clean room, not to run the
test: the eval's task function is called in a fresh child process with empty caches, which
makes it load its dataset exactly as inspect would, and the prepared Cases come back through
a file. It never calls inspect's ``eval()``: no solver, scorer, model or Judge runs.
Stages, in execution order:

    Stage 1 — parent: write the declaration to a temp file; build the child's environment
              with its own empty inspect_evals and Hugging Face caches (a cache hit would
              skip the fetch, and a stale cache would hide a dead URL).
    Stage 2 — child: call the task function with its args, take the Task's dataset (after
              the eval's own filtering, shuffling and conversion), and render each Sample
              with the shared Case writer.
    Stage 3 — child: write the prepared Cases as JSON to the result file. WHY a file and
              not stdout: evals print while they load.
    Stage 4 — parent: a non-zero exit, a timeout or a missing result is a TaskReplayError
              carrying the child's last stderr lines, so the SKIPPED reason names the cause.
    Stage 5 — Case Preparation (:func:`prepare_replayed_cases`): refuse a different Case
              count, then a different Case Digest; write the Cases only when both match,
              otherwise write the SKIPPED marker with the reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import CHANGED_CASES_KEY
from screamingface_engine_inspect.prepare import (
    SKIPPED_MARKER,
    PreparedCase,
    PrepareError,
    TaskReplayCasesSpec,
    _resolve,
    _write_cases,
    case_digest,
    case_records,
)

#: Upper bound on one replay. A package's Cases download in minutes; this only stops a
#: stalled fetch from hanging the image build forever.
TASK_REPLAY_TIMEOUT_SECONDS: int = 1800

#: How much of the child's stderr the SKIPPED reason carries.
_STDERR_TAIL_LINES: int = 20


class TaskReplayError(PrepareError):
    """The replay produced no usable Cases. The message says why, in the child's own words."""


def replay_environment(cache_root: Path, base: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: the builder's, with every Case Source cache pointed at an
    empty directory under ``cache_root``."""

    env: dict[str, str] = dict(base)
    # INVARIANT: every cache a fetch could hit is redirected, so each replay really fetches.
    env["INSPECT_EVALS_CACHE_DIR"] = str(cache_root / "inspect_evals")
    env["HF_DATASETS_CACHE"] = str(cache_root / "hf_datasets")
    env["HF_HUB_CACHE"] = str(cache_root / "hf_hub")
    return env


def replayed_cases(
    spec: TaskReplayCasesSpec, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS
) -> list[PreparedCase]:
    """Call the eval's own task function in a fresh child process; return its prepared Cases.

    Args:
        spec: the Benchmark's Task-replay declaration; ``case_count`` and ``case_digest``
            are NOT checked here, the caller compares them.
        timeout: seconds before a stalled replay is abandoned.

    Returns:
        The prepared Cases, in the order the Task holds its Samples.

    Raises:
        TaskReplayError: the child failed, timed out, or wrote no result.
    """

    # Stage 1 — declaration file + clean-room environment.
    with tempfile.TemporaryDirectory(prefix="task-replay-") as scratch:
        root: Path = Path(scratch)
        spec_path: Path = root / "spec.json"
        result_path: Path = root / "result.json"
        spec_path.write_text(json.dumps(asdict(spec)), encoding="utf-8")
        command: list[str] = [sys.executable, "-m", __name__, str(spec_path), str(result_path)]
        try:
            completed: subprocess.CompletedProcess[str] = subprocess.run(  # noqa: S603 — argv is ours; no shell
                command,
                env=replay_environment(root / "cache", os.environ),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TaskReplayError(f"{spec.task}: replay timed out after {timeout:g}s") from exc
        # Stage 4 — turn any failure into a named reason.
        if completed.returncode != 0 or not result_path.is_file():
            tail: str = "\n".join(completed.stderr.strip().splitlines()[-_STDERR_TAIL_LINES:])
            raise TaskReplayError(
                f"{spec.task}: replay failed (exit {completed.returncode}): {tail}"
            )
        loaded: list[PreparedCase] = json.loads(result_path.read_text(encoding="utf-8"))
        return loaded


def prepare_replayed_cases(spec: TaskReplayCasesSpec, out: Path) -> dict[str, Any]:
    """Case Preparation for a Task-replay Benchmark: replay, check the seal, then write.

    Stage 5 of the module docstring. Any refusal or replay failure writes the SKIPPED marker
    instead of Cases, so one broken Case Source never takes the other Benchmarks in the image
    down with it (spec R10); the strict prepare CLI then fails on ``CHANGED_CASES_KEY``.

    Example: pinned ``case_count=2``; the task now yields 3 Cases → SKIPPED, reason
    "… the task yielded 3 Cases, pinned case count is 2".

    Args:
        spec: the Benchmark's Task-replay declaration.
        out: the empty directory to prepare into.

    Returns:
        The summary: ``cases`` and ``case_digest`` on success; on a skip, ``cases`` 0 plus
        ``skipped`` and ``CHANGED_CASES_KEY`` carrying the reason.
    """

    try:
        prepared: list[PreparedCase] = replayed_cases(spec)
        if len(prepared) != spec.case_count:
            raise TaskReplayError(
                f"{spec.task}: the task yielded {len(prepared)} Cases, "
                f"pinned case count is {spec.case_count}"
            )
        digest: str = case_digest(prepared)
        if digest != spec.case_digest:
            raise TaskReplayError(
                f"{spec.task}: Case Digest {digest} does not match the pinned {spec.case_digest}"
            )
    except TaskReplayError as exc:
        # WHY SKIPPED, not a raise: deployed images keep every other Benchmark (spec R10).
        reason: str = str(exc)
        print(f"WARNING: skipping {reason}", file=sys.stderr, flush=True)
        out.mkdir(parents=True, exist_ok=True)
        (out / SKIPPED_MARKER).write_text(reason + "\n", encoding="utf-8")
        return {"cases": 0, "skipped": reason, CHANGED_CASES_KEY: reason, "out": str(out)}
    _write_cases(prepared, out)
    return {"cases": len(prepared), "case_digest": digest, "out": str(out)}


def _replay_in_this_process(spec_path: Path, result_path: Path) -> None:
    """Stages 2 and 3 — the child's half: call the task function, render its Samples, write
    the result."""

    fields: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(**fields)
    task: Any = _resolve(spec.task)(**(spec.task_args or {}))
    prepared: list[PreparedCase] = case_records(list(task.dataset), spec)
    result_path.write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")


__all__ = [
    "TASK_REPLAY_TIMEOUT_SECONDS",
    "TaskReplayError",
    "prepare_replayed_cases",
    "replay_environment",
    "replayed_cases",
]


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, run via replayed_cases
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]))
