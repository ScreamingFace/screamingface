"""Task replay: fetch an Imported Benchmark's Cases by calling the eval's own task function.

FEATURE: Task-replay Imported Benchmarks (OME-1273) — evals whose Cases the importer cannot
see come from the eval's own loading code, pinned by a Case Digest.

Think of it as asking the eval to print its question booklet in a clean room, not to run the
test: the eval's task function is called in a fresh child process with empty caches, which
makes it load its dataset exactly as inspect would, and the prepared Cases come back through
a file. Each Sample's prompt is captured from the Task's own solvers, run up to their first
``generate`` (:mod:`screamingface_engine_inspect.capture`). It never calls inspect's
``eval()``: no model, scorer or Judge runs, and nothing is paid for.
Stages, in execution order:

    Stage 1 — parent: write the declaration to a temp file; build the child's environment
              with its own empty inspect_evals and Hugging Face caches (a cache hit would
              skip the fetch, and a stale cache would hide a dead URL) and no model name in
              INSPECT_EVAL_MODEL, so nothing in the child can reach a model.
    Stage 2 — child: import the task module, install the fetch-pin enforcer with the
              declaration's Hub commits and seeds (OME-1460), call the task function with its
              args, take the Task's dataset (after the eval's own filtering, shuffling and
              conversion), and render each Sample by capture, then write it with the shared
              Case writer. WHY enforce at every build, not only at import: a build that let
              the eval fetch unforced would read whatever commit the Hub serves that day.
    Stage 3 — child: write the prepared Cases AND the provenance block (the recorder's
              fetches and forced seeds, the Sample counts, the inspect pins;
              :mod:`screamingface_engine_inspect.replay_provenance`) as JSON to the result
              file. WHY a file and not stdout: evals print while they load.
    Stage 4 — parent: a non-zero exit, a timeout, or a missing or unreadable result is a
              TaskReplayError carrying the child's final error line, so the SKIPPED reason
              names the cause; the stderr tail goes to the build log. The child's output is
              decoded leniently: it only feeds the log and the reason, and one byte that is
              not UTF-8 must not crash the whole image build.
    Stage 5 — Case Preparation (:func:`prepare_replayed_cases`): refuse a different Case
              count, then a different Case Digest; write the Cases only when both match,
              otherwise write the SKIPPED marker with the reason. Either way the bundle gets
              ``provenance.json`` (before ``cases.json``) and the summary carries the block.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, NamedTuple

from screamingface_engine.benchmarks.deployment import UNCONFIRMED_CASES_KEY
from screamingface_engine_inspect.capture import captured_case_records
from screamingface_engine_inspect.case_set import what_moved
from screamingface_engine_inspect.case_sources import CaseSourceRecorder
from screamingface_engine_inspect.fetch_pins import FetchPins
from screamingface_engine_inspect.prepare import (
    SKIPPED_MARKER,
    PreparedCase,
    PrepareError,
    TaskReplayCasesSpec,
    _resolve,
    _write_cases,
    case_digest,
    skip_without_hf_token,
)
from screamingface_engine_inspect.replay_provenance import (
    PROVENANCE_KEY,
    replay_provenance,
    write_provenance,
)

#: Upper bound on one replay. A package's Cases download in minutes; this only stops a
#: stalled fetch from hanging the image build forever.
TASK_REPLAY_TIMEOUT_SECONDS: int = 1800

#: How much of the child's stderr the SKIPPED reason carries.
_STDERR_TAIL_LINES: int = 20


class TaskReplayError(PrepareError):
    """The replay produced no usable Cases. The message says why, in the child's own words."""


class TaskReplay(NamedTuple):
    """What one replay returns: the prepared Cases and where they came from."""

    cases: list[PreparedCase]
    provenance: dict[str, Any]


def replay_environment(cache_root: Path, base: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: the builder's, with every Case Source cache pointed at an
    empty directory under ``cache_root``."""

    env: dict[str, str] = dict(base)
    # INVARIANT: the builder's cached Hugging Face login stays readable (OME-1460, R8).
    # WHY pinned before XDG moves: huggingface_hub reads its token from HF_HOME/token and
    # derives HF_HOME from XDG_CACHE_HOME when HF_HOME is unset, so redirecting XDG below
    # would send it looking in the child's own empty cache, and a gated dataset (xstest)
    # would fail to load for a dev logged in with `hf auth login`. Only the token is kept.
    env["HF_TOKEN_PATH"] = _hf_token_path(base)
    # INVARIANT: on Linux, where images are built, every cache a Case Source fetch reads is
    # redirected, so each replay really fetches. XDG_CACHE_HOME moves inspect_ai's own cache
    # (platformdirs), which its hf_dataset reads back when called without a revision.
    # AIDEV-NOTE: platformdirs honours XDG_CACHE_HOME on macOS too at this pin (4.11), so a
    # dev Mac redirects inspect_ai's cache as Linux does; an earlier note here said otherwise.
    # HF_HOME is left alone on purpose: it also holds a cached login token (kept reachable
    # by HF_TOKEN_PATH above even when HF_HOME is only XDG's default).
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    # INVARIANT: no model is reachable from the child. Capture hands the solvers a stand-in
    # generate, but a solver that calls get_model() itself reads INSPECT_EVAL_MODEL, and the
    # builder's shell may carry one; "none/none" makes that call raise, so capture refuses
    # the Sample by name instead of a real model's words landing inside a Case.
    env["INSPECT_EVAL_MODEL"] = "none/none"
    env["INSPECT_EVALS_CACHE_DIR"] = str(cache_root / "inspect_evals")
    env["HF_DATASETS_CACHE"] = str(cache_root / "hf_datasets")
    env["HF_HUB_CACHE"] = str(cache_root / "hf_hub")
    env["HF_MODULES_CACHE"] = str(cache_root / "hf_modules")
    env["HF_XET_CACHE"] = str(cache_root / "hf_xet")
    env["HF_ASSETS_CACHE"] = str(cache_root / "hf_assets")
    return env


def _hf_token_path(base: Mapping[str, str]) -> str:
    """Where huggingface_hub would read the builder's login token, by its own rule.

    HF_TOKEN_PATH if set; else HF_HOME/token; else XDG_CACHE_HOME/huggingface/token; else
    ~/.cache/huggingface/token (huggingface_hub.constants, 1.x).
    """

    if base.get("HF_TOKEN_PATH"):
        return base["HF_TOKEN_PATH"]
    cache_home: str = base.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    hf_home: str = base.get("HF_HOME") or os.path.join(cache_home, "huggingface")
    return os.path.join(os.path.expanduser(hf_home), "token")


def _failure_reason(stderr: str | bytes | None) -> str:
    """The child's last non-empty stderr line, usually its final exception line.

    WHY one line: the reason is baked into the SKIPPED marker and returned to callers at run
    time, so it must name the cause, not dump builder paths; the full tail goes to the log.
    """

    text: str = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr or ""
    lines: list[str] = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no error output"


def _log_child_stderr(task_ref: str, stderr: str | bytes | None) -> None:
    """Copy the tail of the child's stderr into the build log, where the full story belongs."""

    text: str = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr or ""
    tail: list[str] = text.strip().splitlines()[-_STDERR_TAIL_LINES:]
    if tail:
        print(f"{task_ref}: replay stderr (last {len(tail)} lines):", file=sys.stderr)
        print("\n".join(tail), file=sys.stderr, flush=True)


def replayed_cases(
    spec: TaskReplayCasesSpec, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS
) -> list[PreparedCase]:
    """Call the eval's own task function in a fresh child process; return its prepared Cases.

    The import path's entry point (``import_replay``); Case Preparation calls
    :func:`replay_with_provenance` to keep the provenance too.

    Raises:
        TaskReplayError: the child failed, timed out, or wrote no result.
    """

    return replay_with_provenance(spec, timeout=timeout).cases


def replay_with_provenance(
    spec: TaskReplayCasesSpec, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS
) -> TaskReplay:
    """Call the eval's own task function in a fresh child process; return its prepared
    Cases and the provenance block, with the replay's wall time added as ``seconds``.

    Args:
        spec: the Benchmark's Task-replay declaration; ``case_count`` and ``case_digest``
            are NOT checked here, the caller compares them.
        timeout: seconds before a stalled replay is abandoned.

    Returns:
        The prepared Cases, in the order the Task holds its Samples, and their provenance.

    Raises:
        TaskReplayError: the child failed, timed out, or wrote no result.
    """

    # WHY the parent times it: the child can't see its own interpreter start-up.
    started: float = time.monotonic()
    # Stage 1 — declaration file + clean-room environment.
    with tempfile.TemporaryDirectory(prefix="task-replay-") as scratch:
        root: Path = Path(scratch)
        spec_path: Path = root / "spec.json"
        result_path: Path = root / "result.json"
        cache_root: Path = root / "cache"
        spec_path.write_text(json.dumps(asdict(spec)), encoding="utf-8")
        command: list[str] = [
            sys.executable,
            "-m",
            __name__,
            str(spec_path),
            str(result_path),
            str(cache_root),
        ]
        try:
            completed: subprocess.CompletedProcess[str] = subprocess.run(  # noqa: S603 — argv is ours; no shell
                command,
                env=replay_environment(cache_root, os.environ),
                capture_output=True,
                # WHY lenient: this text only feeds the log and the one-line reason. Strict
                # decoding raised UnicodeDecodeError on one Latin-1 byte, which no caller
                # catches, so the whole image build crashed (spec R10).
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log_child_stderr(spec.task, exc.stderr)
            raise TaskReplayError(f"{spec.task}: replay timed out after {timeout:g}s") from exc
        # Stage 4 — turn any failure into a one-line named reason; the tail goes to the log.
        if completed.returncode != 0 or not result_path.is_file():
            _log_child_stderr(spec.task, completed.stderr)
            raise TaskReplayError(
                f"{spec.task}: replay failed (exit {completed.returncode}): "
                f"{_failure_reason(completed.stderr)}"
            )
        try:
            loaded: Any = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # WHY: a child killed mid-write can exit 0 and leave a cut-off file; that is
            # this Benchmark's failure, not the image build's (spec R10).
            raise TaskReplayError(f"{spec.task}: replay wrote an unreadable result: {exc}") from exc
        if not (
            isinstance(loaded, dict)
            and isinstance(loaded.get("prepared"), list)
            and isinstance(loaded.get(PROVENANCE_KEY), dict)
        ):
            raise TaskReplayError(f"{spec.task}: replay wrote a result of the wrong shape")
        provenance: dict[str, Any] = {
            **loaded[PROVENANCE_KEY],
            "seconds": round(time.monotonic() - started, 3),
        }
        return TaskReplay(cases=loaded["prepared"], provenance=provenance)


def prepare_replayed_cases(
    spec: TaskReplayCasesSpec, out: Path, *, benchmark_key: str | None = None
) -> dict[str, Any]:
    """Case Preparation for a Task-replay Benchmark: replay, check the seal, then write.

    Stage 5 of the module docstring. Any refusal or replay failure writes the SKIPPED marker
    instead of Cases, so one broken Case Source never takes the other Benchmarks in the image
    down with it (spec R10); the strict prepare CLI then fails on ``UNCONFIRMED_CASES_KEY``.

    Example: Benchmark ``mgsm_en`` pinned ``case_count=2``; the task now yields 3 Cases →
    SKIPPED, reason "mgsm_en: inspect_evals.mgsm.mgsm:mgsm: the task yielded 3 Cases, pinned
    case count is 2".

    Args:
        spec: the Benchmark's Task-replay declaration.
        out: the empty directory to prepare into.
        benchmark_key: the Benchmark the reason names first, as R10 asks, so a board visitor
            reads the board's key before the inspect task path. Assembly always passes it.

    Returns:
        The summary: ``cases`` and ``case_digest`` on success; on a skip, ``cases`` 0 plus
        ``skipped`` and ``UNCONFIRMED_CASES_KEY`` carrying the reason. A gated Benchmark
        skipped for want of a token carries no ``UNCONFIRMED_CASES_KEY`` (OME-1460, F7).
        Whenever the replay itself finished (success, or a count or digest mismatch), the
        summary also carries ``provenance`` and the bundle holds ``provenance.json``.

    Raises:
        PrepareError: a gated Benchmark with no token and no skip flag (R8).
    """

    if spec.needs_hf_token:
        # WHY before the replay: without a token the gated fetch can only fail, and a PR
        # build must say "no secret", not "replay failed" (OME-1460, R8).
        gated: str = ", ".join(sorted(spec.source_pins)) or spec.task
        skipped: dict[str, Any] | None = skip_without_hf_token(gated, out)
        if skipped is not None:
            return skipped
    provenance: dict[str, Any] | None = None
    try:
        replay: TaskReplay = replay_with_provenance(spec)
        prepared: list[PreparedCase] = replay.cases
        provenance = replay.provenance
        if len(prepared) != spec.case_count:
            raise TaskReplayError(
                f"{spec.task}: the task yielded {len(prepared)} Cases, "
                f"pinned case count is {spec.case_count}"
            )
        digest: str = case_digest(prepared)
        if digest != spec.case_digest:
            raise TaskReplayError(
                f"{spec.task}: Case Digest {digest} does not match the pinned {spec.case_digest}"
                # OME-1492: "same N Cases in another order" or "text changed", when sealed.
                + what_moved(spec, prepared)
            )
    except TaskReplayError as exc:
        # WHY SKIPPED, not a raise: deployed images keep every other Benchmark (spec R10).
        reason: str = f"{benchmark_key}: {exc}" if benchmark_key else str(exc)
        print(f"WARNING: skipping {reason}", file=sys.stderr, flush=True)
        out.mkdir(parents=True, exist_ok=True)
        (out / SKIPPED_MARKER).write_text(reason + "\n", encoding="utf-8")
        skipped_summary: dict[str, Any] = {
            "cases": 0,
            "skipped": reason,
            UNCONFIRMED_CASES_KEY: reason,
            "out": str(out),
        }
        # WHY keep the block on a mismatch: that's exactly when on-call needs the commit
        # and the seed. A child that crashed returned none, so there is nothing to add.
        if provenance is not None:
            write_provenance(out, provenance)
            skipped_summary[PROVENANCE_KEY] = provenance
        return skipped_summary
    write_provenance(out, provenance)
    _write_cases(prepared, out)
    return {
        "cases": len(prepared),
        "case_digest": digest,
        "out": str(out),
        PROVENANCE_KEY: provenance,
    }


def fetch_pins_of(spec: TaskReplayCasesSpec) -> FetchPins:
    """What a replay of this declaration forces onto the eval's fetches (OME-1460)."""

    return FetchPins(
        source_pins=dict(spec.source_pins),
        shuffle_seed=spec.shuffle_seed,
        choice_shuffle_seed=spec.choice_shuffle_seed,
    )


def _replay_in_this_process(spec_path: Path, result_path: Path, cache_root: Path) -> None:
    """Stages 2 and 3 — the child's half: call the task function with the fetch pins
    enforced, render its Samples, write the result."""

    fields: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(**fields)
    # INVARIANT: the module is imported BEFORE the enforcer installs, so a fetch helper it
    # bound by name at import (gsm8k's `hf_dataset`) is rebound too (R1, R4). The recorder
    # also records every fetch and forced seed; that record becomes the provenance block (OME-1492).
    task_function: Any = _resolve(spec.task)
    recorder: CaseSourceRecorder = CaseSourceRecorder(cache_root)
    recorder.install(fetch_pins_of(spec))
    task: Any = task_function(**(spec.task_args or {}))
    # WHY count before capture: capture drops the declaration's excluded Samples, and the
    # block reports both sides of that cut.
    yielded: int = len(task.dataset)
    prepared: list[PreparedCase] = captured_case_records(task, spec)
    # WHY built after capture: a solver can fetch a file while rendering a Sample, and that
    # fetch belongs in the record too.
    block: dict[str, Any] = replay_provenance(recorder, spec, yielded=yielded, kept=len(prepared))
    result_path.write_text(
        json.dumps({"prepared": prepared, PROVENANCE_KEY: block}, ensure_ascii=False),
        encoding="utf-8",
    )


__all__ = [
    "TASK_REPLAY_TIMEOUT_SECONDS",
    "TaskReplay",
    "TaskReplayError",
    "fetch_pins_of",
    "prepare_replayed_cases",
    "replay_environment",
    "replay_with_provenance",
    "replayed_cases",
]


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, run via replayed_cases
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
