# Task-replay Case Preparation (image side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At image build, prepare a Task-replay Imported Benchmark by calling the eval's own
task function in a child process (never inspect's `eval()`: no solver, scorer or model runs), and serve its Cases only when their Case Digest matches the pinned one.

**Architecture:** `prepare.py` gains the shared Case writer, the Case Digest and a second
declaration type (`TaskReplayCasesSpec`, own registry `TASK_REPLAY_CASES`). A new
`task_replay.py` calls the task function in a child process with empty caches and turns a mismatch into a
`SKIPPED` marker. `benchmarks.py` assembles either declaration type. The core prepare CLI fails
at the end when `SCREAMINGFACE_FAIL_ON_CHANGED_CASES=1` and any bundle was skipped for changed
Cases; only the PR image job sets it.

**Tech Stack:** Python 3.12, uv, pytest, `inspect-ai` 0.3.263, `inspect-evals` 0.20.0, Docker
BuildKit, GitHub Actions.

**Spec:** `docs/spec/2026-09-30-OME-1273-task-replay-import.md` (approved 2026-09-30). This plan
is PR 2 of the stack, covering R5, R9, R10, R11 and R12. PRs 3-6 get their own plan when they start.

## Global Constraints

- Work in a fresh worktree off `upstream/main`: `git worktree add .claude/worktrees/ome-1273-task-replay-image -b OME-1273-task-replay-image upstream/main`.
- All paths below are relative to `apps/screamingface-engine/` unless they start with `.github/`.
- Test command (the `inspect` extra is required): `uv sync --extra inspect --inexact` once, then `uv run pytest <path> -q`.
- Gates before the PR: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest tests/unit -q`.
- `tests/unit/inspect/test_published_revisions.py` must pass unchanged. No published Benchmark Revision moves.
- `cases.json` and `targets/<id>.json` for every existing Benchmark stay byte-identical.
- Glossary words only (`CONTEXT.md`): Case, Case Preparation, Case Source, Case Digest, Grading Material, Benchmark Revision. Never "board", "bake", "exam" or "row" in new code, comments or test names.
- Plain `test_` functions, no classes. Type every argument, return value and non-obvious local.
- Commits: conventional, `feat(screamingface-engine): …`, no `Co-Authored-By`. Stage explicit paths, never `git add -A`.
- Files that import inspect carry the existing file-level `# pyright: reportMissingImports=false` header.

## Review Focus

1. **The eval prints to stdout.** Many evals log or print while loading. The child protocol must not read stdout, so a chatty eval still replays. Pinned in Task 2.
2. **The fetch hangs.** A stalled download must end in `SKIPPED` after a bounded time, not a build that never finishes. Pinned in Task 2 (timeout) and Task 3.
3. **Case text that isn't ASCII.** The Case Digest must be computed over UTF-8 text, never over `\u` escapes, so it matches the files on disk. Pinned in Task 1.
4. **The builder already has an inspect_evals cache configured.** A stale cache on a developer's machine must not hide a dead URL: the child always gets its own empty cache directories. Pinned in Task 2.
5. **A key declared in both registries.** Assembly must refuse it by name instead of silently picking one. Pinned in Task 4.

---

### Task 1: Shared Case writer and the Case Digest

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (`emit_cases`, `_emit`, add `PreparedCase`, `case_records`, `case_digest`, extend `__all__`)
- Test: `tests/unit/inspect/test_case_digest.py` (new)

**Interfaces:**
- Produces: `PreparedCase = dict[str, dict[str, Any]]`, with keys `"case"` (`{"id", "case_id", "input"}`) and `"grading_material"` (`{"target", "choices"?, "metadata"?}`).
- Produces: `case_records(samples: Sequence[Sample], spec: CasesSpec | TaskReplayCasesSpec) -> list[PreparedCase]`. `TaskReplayCasesSpec` arrives in Task 2; in this task, annotate `spec: CasesSpec` and widen the annotation in Task 2.
- Produces: `case_digest(prepared: Sequence[PreparedCase]) -> str` (64 lowercase hex).
- Produces: `_write_cases(prepared: Sequence[PreparedCase], out: Path) -> None`, the file writer, refusing a non-empty `out` exactly as `_emit` does today.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/inspect/test_case_digest.py
# pyright: reportMissingImports=false
"""The Case Digest: one fingerprint over exactly what Case Preparation writes (spec R5).

INVARIANT: the digest is computed from the same records the writer writes, so a Case that
differs on disk always has a different digest, and nothing else can move it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.prepare import (  # noqa: E402
    PreparedCase,
    _write_cases,
    case_digest,
)

_PREPARED: list[PreparedCase] = [
    {"case": {"id": 1, "case_id": "1", "input": "What is 6 times 7?"}, "grading_material": {"target": "42"}},
    {
        "case": {"id": 2, "case_id": "2", "input": "Wie viel ist 2 plus 2? — vier"},
        "grading_material": {"target": "4"},
    },
]


def test_case_digest_is_pinned_so_its_definition_cannot_drift_silently() -> None:
    """WHY a literal: every Task-replay declaration stores this value. A change to the
    serialisation (key order, separators, escaping) would SKIP every such Benchmark."""
    assert case_digest(_PREPARED) == "765b395557508c36f4e5cf19ec9c4bb4936ca38301fbcd889aa46191735725a4"


def test_case_digest_moves_when_any_written_field_moves() -> None:
    changed_target: list[PreparedCase] = [_PREPARED[0], {**_PREPARED[1], "grading_material": {"target": "5"}}]
    reordered: list[PreparedCase] = [_PREPARED[1], _PREPARED[0]]
    assert case_digest(changed_target) != case_digest(_PREPARED)
    assert case_digest(reordered) != case_digest(_PREPARED)


def test_written_files_are_utf8_so_the_digest_matches_what_is_on_disk(tmp_path: Path) -> None:
    """Review Focus 3: non-ASCII text is written as UTF-8, never as \\u escapes."""
    _write_cases(_PREPARED, tmp_path)
    assert "— vier" in (tmp_path / "cases.json").read_text(encoding="utf-8")
    assert (tmp_path / "targets" / "2.json").read_text(encoding="utf-8") == '{"target":"4"}'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_case_digest.py -q`
Expected: FAIL with `ImportError: cannot import name 'PreparedCase'`.

- [ ] **Step 3: Implement.** In `prepare.py`, add below `SKIPPED_MARKER`:

```python
#: One prepared Case as the writer writes it: the public ``case`` row of ``cases.json``
#: and its private ``grading_material`` record (``targets/<id>.json``).
type PreparedCase = dict[str, dict[str, Any]]


def case_digest(prepared: Sequence[PreparedCase]) -> str:
    """Fingerprint the prepared Cases: the sha256 of exactly what the writer writes.

    Think of it as a seal on the envelope of Cases: any change to any Case's id, input or
    Grading Material, or to their order, breaks the seal. Canonical JSON (sorted keys, no
    whitespace, UTF-8 without escapes) keeps the seal independent of dict order.

    Example: the two Cases in ``test_case_digest.py`` seal to ``765b3955…``; changing one
    target from "4" to "5" gives a different digest.
    """

    canonical: str = json.dumps(
        list(prepared), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Add `import hashlib` to the imports. Extract the Stage 5 loop of `emit_cases` into `case_records`, and the file writes of `_emit` into `_write_cases`:

```python
def case_records(samples: Sequence[Sample], spec: CasesSpec) -> list[PreparedCase]:
    """Stage 5 — turn Samples into prepared Cases: the rendered input plus its Grading Material.

    Shared by both preparation paths, so a Hugging Face Benchmark and a Task-replay Benchmark
    can never drift on how a Case is written.
    """

    template: str | None = None if spec.prompt_template is None else _resolve(spec.prompt_template)
    choice_template: str | None = (
        None if spec.choice_template is None else _resolve(spec.choice_template)
    )
    system_text: str | None = _resolved_system_text(spec)
    prepared: list[PreparedCase] = []
    for case_id, sample in enumerate(samples, start=1):
        target, choices = _validated_answer_key(sample, case_id, spec.has_answer_key)
        input_text: str = _prompt(sample, choices, template, choice_template)
        if system_text is not None:
            # Named deviation (contracteval pattern): the eval's SYSTEM
            # instruction becomes the input's leading text, render untouched.
            input_text = f"{system_text}\n\n{input_text}"
        # WHY "case_id" beside "id": the benchmark's url4 protocol template reads
        # $item.case_id per Case (the transport contract's string spelling);
        # "id" is the integer that cases.json rows and the targets/ files key on.
        record: dict[str, Any] = (
            {"target": target} if choices is None else {"target": target, "choices": choices}
        )
        if spec.keep_sample_metadata and sample.metadata:
            record["metadata"] = _validated_metadata(sample.metadata, case_id)
        prepared.append(
            {
                "case": {"id": case_id, "case_id": str(case_id), "input": input_text},
                "grading_material": record,
            }
        )
    return prepared


def _write_cases(prepared: Sequence[PreparedCase], out: Path) -> None:
    """Stage 6 — write the public booklet and the private Grading Material records."""

    grading_material_dir: Path = out / "targets"
    # WHY refuse a dirty out: a re-prepare into a used directory would leave orphan
    # targets/*.json from a previous, larger prepare — the image build always starts
    # fresh, and this makes that assumption loud instead of silent.
    if (out / "cases.json").exists() or (
        grading_material_dir.is_dir() and any(grading_material_dir.iterdir())
    ):
        raise PrepareError(f"refusing to prepare into non-empty directory {out}")
    grading_material_dir.mkdir(parents=True, exist_ok=True)
    for item in prepared:
        (grading_material_dir / f"{item['case']['id']}.json").write_text(
            json.dumps(item["grading_material"], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    (out / "cases.json").write_text(
        json.dumps([item["case"] for item in prepared], ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
```

Then `emit_cases` ends with:

```python
    require_commit_sha(spec.dataset_revision)
    samples: list[Sample] = _pinned_samples(spec, rows, expected_cases)
    if spec.choice_shuffle_seed is not None:
        _shuffle_choices(samples, spec.choice_shuffle_seed)
    prepared: list[PreparedCase] = case_records(samples, spec)
    _write_cases(prepared, out)
    return {"cases": len(prepared), "dataset_revision": spec.dataset_revision, "out": str(out)}
```

Delete `_emit` (its two callers are now `emit_cases` and nothing else; `grep -n "_emit(" src/screamingface_engine_inspect/prepare.py` must return only definitions you kept). Keep the `emit_cases` docstring's stage list; Stage 5 now reads "per Sample, via :func:`case_records`". Add `"PreparedCase"`, `"case_digest"`, `"case_records"` to `__all__`.

- [ ] **Step 4: Run the new tests and the existing Case tests**

Run: `uv run pytest tests/unit/inspect/test_case_digest.py tests/unit/inspect/test_inspect_cases.py tests/unit/inspect/test_inspect_gsm8k_benchmark.py tests/unit/inspect/test_inspect_mmlu_benchmark.py -q`
Expected: all PASS. The existing tests are the byte-identical guard for the refactor.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/prepare.py tests/unit/inspect/test_case_digest.py
git commit -m "feat(screamingface-engine): share the Case writer and add the Case Digest"
```

---

### Task 2: The Task-replay declaration and the child-process replay

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (add `TaskReplayCasesSpec`, `TASK_REPLAY_CASES`; widen `case_records` and `_resolved_system_text` to the union)
- Create: `src/screamingface_engine_inspect/task_replay.py`
- Test: `tests/unit/inspect/test_task_replay.py` (new)

**Interfaces:**
- Consumes: `PreparedCase`, `case_records`, `_resolve`, `PrepareError` from Task 1.
- Produces, in `prepare.py`:

```python
@dataclass(frozen=True)
class TaskReplayCasesSpec:
    """One Task-replay Imported Benchmark's Case Preparation, as pure data (OME-1273).

    The Cases come from calling the eval's own task function (``task``, a ``"module:attr"``
    reference, called with ``task_args``); building its Task loads the dataset. No
    evaluation runs: no solver, scorer or model, so no dataset pin applies. ``case_count`` and
    ``case_digest`` are CAPTURED at import; Case Preparation serves nothing unless both
    match. The prompt fields mean exactly what they mean on :class:`CasesSpec`.
    """

    task: str
    case_count: int
    case_digest: str
    task_args: dict[str, Any] | None = None
    prompt_template: str | None = None
    choice_template: str | None = None
    system_message: str | None = None
    keep_sample_metadata: bool = False
    has_answer_key: bool = True


#: Every Task-replay Imported Benchmark's Case Preparation, keyed like BENCHMARK_CASES.
#: Empty until PR 5 of OME-1273 imports agieval, medqa and mgsm.
TASK_REPLAY_CASES: dict[str, TaskReplayCasesSpec] = {}
```

- Produces, in `task_replay.py`:
  - `TASK_REPLAY_TIMEOUT_SECONDS: int = 1800`
  - `class TaskReplayError(PrepareError)`: the replay did not produce Cases; the message is the reason.
  - `replay_environment(cache_root: Path, base: Mapping[str, str]) -> dict[str, str]`
  - `replayed_cases(spec: TaskReplayCasesSpec, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS) -> list[PreparedCase]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/inspect/test_task_replay.py
# pyright: reportMissingImports=false
"""Task replay: the eval's own task runs in a child process and yields prepared Cases (spec R2, R9).

INVARIANT: the child always starts with empty caches and reports through a file, never
stdout, so what it returns is what a fresh fetch produces and nothing an eval prints can
corrupt it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.prepare import TaskReplayCasesSpec, case_digest  # noqa: E402
from screamingface_engine_inspect.task_replay import (  # noqa: E402
    TaskReplayError,
    replay_environment,
    replayed_cases,
)

#: A stand-in eval: its task builds Samples the way an inspect_evals loader would.
FAKE_EVAL: str = textwrap.dedent(
    '''
    import time
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample

    @task
    def arithmetic(extra: bool = False) -> Task:
        print("downloading from https://example.invalid/cases.jsonl")  # Review Focus 1
        samples = [Sample(input="What is 6 times 7?", target="42"),
                   Sample(input="What is 2 plus 2?", target="4")]
        if extra:
            samples.append(Sample(input="What is 1 plus 1?", target="2"))
        return Task(dataset=MemoryDataset(samples))

    @task
    def broken() -> Task:
        raise RuntimeError("upstream URL returned 404")

    @task
    def stalled() -> Task:
        time.sleep(30)
        return Task(dataset=MemoryDataset([]))
    '''
)


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""
    (tmp_path / "fake_replay_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return "fake_replay_eval"


def test_replay_returns_the_cases_the_task_builds(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:arithmetic", case_count=2, case_digest="0" * 64)
    prepared = replayed_cases(spec)
    assert [item["case"]["input"] for item in prepared] == ["What is 6 times 7?", "What is 2 plus 2?"]
    assert [item["grading_material"] for item in prepared] == [{"target": "42"}, {"target": "4"}]


def test_replay_passes_task_args_and_is_deterministic(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic", task_args={"extra": True}, case_count=3, case_digest="0" * 64
    )
    first = replayed_cases(spec)
    assert len(first) == 3
    assert case_digest(first) == case_digest(replayed_cases(spec))


def test_a_task_that_raises_is_a_named_replay_failure(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest="0" * 64)
    with pytest.raises(TaskReplayError, match="upstream URL returned 404"):
        replayed_cases(spec)


def test_a_stalled_fetch_ends_after_the_timeout(fake_eval: str) -> None:
    """Review Focus 2: a hung download must never hang the image build."""
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:stalled", case_count=0, case_digest="0" * 64)
    with pytest.raises(TaskReplayError, match="timed out"):
        replayed_cases(spec, timeout=2)


def test_the_child_always_gets_its_own_empty_caches(tmp_path: Path) -> None:
    """Review Focus 4: a builder's stale cache must not hide a dead URL."""
    base = {"INSPECT_EVALS_CACHE_DIR": "/home/dev/.cache/inspect_evals", "HF_TOKEN": "hf_x", "PATH": "/bin"}
    env = replay_environment(tmp_path, base)
    assert env["INSPECT_EVALS_CACHE_DIR"] == str(tmp_path / "inspect_evals")
    assert env["HF_DATASETS_CACHE"] == str(tmp_path / "hf_datasets")
    assert env["HF_HUB_CACHE"] == str(tmp_path / "hf_hub")
    # WHY HF_TOKEN survives: gated datasets still need it; only caches are replaced.
    assert env["HF_TOKEN"] == "hf_x" and env["PATH"] == "/bin"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_task_replay.py -q`
Expected: FAIL with `ImportError: cannot import name 'TaskReplayCasesSpec'`.

- [ ] **Step 3: Implement.** Add `TaskReplayCasesSpec` and `TASK_REPLAY_CASES` to `prepare.py` exactly as in **Interfaces**, placed after `BENCHMARK_CASES`. Widen `case_records(samples, spec: CasesSpec | TaskReplayCasesSpec)` and `_resolved_system_text(spec: CasesSpec | TaskReplayCasesSpec)`. Add both new names to `__all__`. Create `task_replay.py`:

```python
# pyright: reportMissingImports=false
# WHY file-level: the child half imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Task replay: fetch an Imported Benchmark's Cases by calling the eval's own task function (OME-1273).

Think of it as asking the eval to print its question booklet in a clean room, not to run the
test: the eval's task function is called in a fresh child process with empty caches, which
makes it load its dataset exactly as inspect would, and the prepared Cases come back through
a file. It never calls inspect's ``eval()``: no solver, scorer, model or Judge runs. Stages, in execution order:

    Stage 1 — parent: write the declaration to a temp file; build the child's environment
              with its own empty inspect_evals and Hugging Face caches (a cache hit would
              skip the fetch, and a stale cache would hide a dead URL).
    Stage 2 — child: call the task with its args, take the Task's dataset (after the
              eval's own filtering, shuffling and conversion), and render each Sample
              with the shared Case writer.
    Stage 3 — child: write the prepared Cases as JSON to the result file. WHY a file and
              not stdout: evals print while they load.
    Stage 4 — parent: a non-zero exit, a timeout or a missing result is a TaskReplayError
              carrying the child's last stderr lines, so the SKIPPED reason names the cause.
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

from screamingface_engine_inspect.prepare import (
    PreparedCase,
    PrepareError,
    TaskReplayCasesSpec,
    _resolve,
    case_records,
)

#: Upper bound on one replay. The largest of the 14 packages downloads in minutes; this
#: only stops a stalled fetch from hanging the image build forever.
TASK_REPLAY_TIMEOUT_SECONDS: int = 1800

#: How much of the child's stderr the SKIPPED reason carries.
_STDERR_TAIL_LINES: int = 20


class TaskReplayError(PrepareError):
    """The replay produced no Cases. The message says why, in the child's own words."""


def replay_environment(cache_root: Path, base: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: the builder's, with every Case Source cache pointed at an empty directory."""

    env: dict[str, str] = dict(base)
    env["INSPECT_EVALS_CACHE_DIR"] = str(cache_root / "inspect_evals")
    env["HF_DATASETS_CACHE"] = str(cache_root / "hf_datasets")
    env["HF_HUB_CACHE"] = str(cache_root / "hf_hub")
    return env


def replayed_cases(
    spec: TaskReplayCasesSpec, *, timeout: float = TASK_REPLAY_TIMEOUT_SECONDS
) -> list[PreparedCase]:
    """Run the eval's own task in a fresh child process and return its prepared Cases.

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
            completed = subprocess.run(  # noqa: S603 — argv is ours; no shell
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
            raise TaskReplayError(f"{spec.task}: replay failed (exit {completed.returncode}): {tail}")
        loaded: list[PreparedCase] = json.loads(result_path.read_text(encoding="utf-8"))
        return loaded


def _replay_in_this_process(spec_path: Path, result_path: Path) -> None:
    """Stages 2 and 3 — the child's half: run the task, render its Samples, write the result."""

    fields: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
    spec: TaskReplayCasesSpec = TaskReplayCasesSpec(**fields)
    task: Any = _resolve(spec.task)(**(spec.task_args or {}))
    prepared: list[PreparedCase] = case_records(list(task.dataset), spec)
    result_path.write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - child-process entrypoint, exercised via replayed_cases
    _replay_in_this_process(Path(sys.argv[1]), Path(sys.argv[2]))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/inspect/test_task_replay.py -q`
Expected: 5 PASS (the timeout test takes about 2 s).

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/prepare.py src/screamingface_engine_inspect/task_replay.py tests/unit/inspect/test_task_replay.py
git commit -m "feat(screamingface-engine): replay an eval's own task in a clean child process"
```

---

### Task 3: Task-replay Case Preparation with the Case Digest check

**Files:**
- Modify: `src/screamingface_engine_inspect/task_replay.py` (add `prepare_replayed_cases`)
- Modify: `src/screamingface_engine/benchmarks/deployment.py` (add `CHANGED_CASES_KEY`)
- Test: `tests/unit/inspect/test_task_replay.py` (extend)

**Interfaces:**
- Consumes: `replayed_cases`, `TaskReplayError` (Task 2); `case_digest`, `_write_cases`, `SKIPPED_MARKER` (Task 1 / existing).
- Produces: `CHANGED_CASES_KEY: str = "changed_cases"` in `screamingface_engine.benchmarks.deployment`, the summary key a preparer sets when it skipped a bundle because its Cases changed or could not be fetched.
- Produces: `prepare_replayed_cases(spec: TaskReplayCasesSpec, out: Path) -> dict[str, Any]`. On success: `{"cases": n, "case_digest": digest, "out": str(out)}`. On mismatch or failure: writes `out/SKIPPED`, returns `{"cases": 0, "skipped": reason, CHANGED_CASES_KEY: reason, "out": str(out)}`.

- [ ] **Step 1: Write the failing tests** (append to `test_task_replay.py`; add `prepare_replayed_cases` to its import and `from screamingface_engine_inspect.prepare import SKIPPED_MARKER`, `from screamingface_engine.benchmarks.deployment import CHANGED_CASES_KEY`)

```python
def _pinned(fake_eval: str) -> TaskReplayCasesSpec:
    """A declaration whose count and digest are what the stand-in task really produces."""
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:arithmetic", case_count=2, case_digest="0" * 64)
    return TaskReplayCasesSpec(task=spec.task, case_count=2, case_digest=case_digest(replayed_cases(spec)))


def test_matching_digest_writes_the_cases(fake_eval: str, tmp_path: Path) -> None:
    spec = _pinned(fake_eval)
    out = tmp_path / "out"
    summary = prepare_replayed_cases(spec, out)
    assert summary["cases"] == 2 and summary["case_digest"] == spec.case_digest
    assert (out / "cases.json").is_file() and not (out / SKIPPED_MARKER).exists()


def test_a_changed_digest_serves_nothing_and_names_the_reason(fake_eval: str, tmp_path: Path) -> None:
    """Spec R10: different Cases are never served; the marker says why."""
    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(task=pinned.task, case_count=2, case_digest="f" * 64)
    out = tmp_path / "out"
    summary = prepare_replayed_cases(spec, out)
    reason = (out / SKIPPED_MARKER).read_text(encoding="utf-8")
    assert not (out / "cases.json").exists()
    assert "f" * 64 in reason and pinned.case_digest in reason
    assert summary["cases"] == 0 and summary[CHANGED_CASES_KEY] == reason.strip()


def test_a_changed_case_count_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(task=pinned.task, task_args={"extra": True}, case_count=2, case_digest=pinned.case_digest)
    summary = prepare_replayed_cases(spec, tmp_path / "out")
    assert "3 Cases, pinned case count is 2" in summary[CHANGED_CASES_KEY]


def test_a_failed_fetch_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest="0" * 64)
    summary = prepare_replayed_cases(spec, tmp_path / "out")
    assert "upstream URL returned 404" in summary[CHANGED_CASES_KEY]
    assert not (tmp_path / "out" / "cases.json").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_task_replay.py -q`
Expected: FAIL with `ImportError: cannot import name 'prepare_replayed_cases'`.

- [ ] **Step 3: Implement.** In `deployment.py`, next to `BenchmarkAssetSummary`:

```python
#: Summary key a preparer sets when it skipped its bundle because the Cases changed or
#: could not be fetched. Its value is the reason. The prepare CLI's strict mode fails on it.
CHANGED_CASES_KEY = "changed_cases"
```

Add it to that module's `__all__` if it has one. In `task_replay.py`, import `sys`, `CHANGED_CASES_KEY`, `SKIPPED_MARKER`, `_write_cases`, `case_digest` and add:

```python
def prepare_replayed_cases(spec: TaskReplayCasesSpec, out: Path) -> dict[str, Any]:
    """Case Preparation for a Task-replay Benchmark: replay, check the seal, then write.

    Stages: replay the task (:func:`replayed_cases`); refuse a different Case count, then a
    different Case Digest; write the Cases only when both match. Any refusal or replay
    failure writes the SKIPPED marker instead, so one broken Case Source never takes the
    other Benchmarks in the image down with it (spec R10).

    Example: pinned ``case_count=2``, ``case_digest=765b…``; the task now yields 3 Cases →
    SKIPPED, reason "… 3 Cases, pinned case count is 2".
    """

    try:
        prepared: list[PreparedCase] = replayed_cases(spec)
        if len(prepared) != spec.case_count:
            raise TaskReplayError(
                f"{spec.task}: the task yielded {len(prepared)} Cases, pinned case count is {spec.case_count}"
            )
        digest: str = case_digest(prepared)
        if digest != spec.case_digest:
            raise TaskReplayError(
                f"{spec.task}: Case Digest {digest} does not match the pinned {spec.case_digest}"
            )
    except TaskReplayError as exc:
        reason: str = str(exc)
        print(f"WARNING: skipping {reason}", file=sys.stderr, flush=True)
        out.mkdir(parents=True, exist_ok=True)
        (out / SKIPPED_MARKER).write_text(reason + "\n", encoding="utf-8")
        return {"cases": 0, "skipped": reason, CHANGED_CASES_KEY: reason, "out": str(out)}
    _write_cases(prepared, out)
    return {"cases": len(prepared), "case_digest": digest, "out": str(out)}
```

Note `PrepareError` from `_validated_answer_key` inside the child surfaces as a non-zero exit, so it also arrives as `TaskReplayError`: upstream content that breaks our checks is a changed Case Source.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/inspect/test_task_replay.py tests/unit/test_benchmark_deployment.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine/benchmarks/deployment.py src/screamingface_engine_inspect/task_replay.py tests/unit/inspect/test_task_replay.py
git commit -m "feat(screamingface-engine): serve Task-replay Cases only when their Case Digest matches"
```

---

### Task 4: Assemble Task-replay Benchmarks and pin their revision

**Files:**
- Modify: `src/screamingface_engine_inspect/benchmarks.py` (`_assemble`, `_check_answer_key_opt_in` annotation, add `_cases_declaration`, `_task_replay_pins`)
- Test: `tests/unit/inspect/test_task_replay_assembly.py` (new)

**Interfaces:**
- Consumes: `TASK_REPLAY_CASES`, `TaskReplayCasesSpec` (Task 2), `prepare_replayed_cases` (Task 3).
- Produces: `_cases_declaration(key: str) -> CasesSpec | TaskReplayCasesSpec`, refusing a key in both registries; `_task_replay_pins(spec: TaskReplayCasesSpec) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/inspect/test_task_replay_assembly.py
# pyright: reportMissingImports=false
"""Assembling a Task-replay Benchmark: its revision is pinned by task, args and Case Digest (spec R12)."""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    BENCHMARK_CASES,
    TASK_REPLAY_CASES,
    TaskReplayCasesSpec,
)

_SPEC = TaskReplayCasesSpec(
    task="inspect_evals.mgsm.mgsm:mgsm", case_count=250, case_digest="a" * 64, task_args={"languages": ["en"]}
)


def test_task_replay_pins_carry_task_args_and_digest() -> None:
    """WHY the digest is a pin: two Task-replay Benchmarks serving different Cases must
    never share a Benchmark Revision."""
    assert benchmarks._task_replay_pins(_SPEC) == (
        "task=inspect_evals.mgsm.mgsm:mgsm",
        'task_args={"languages": ["en"]}',
        f"case_digest={'a' * 64}",
    )


def test_a_different_digest_is_a_different_revision_pin() -> None:
    other = TaskReplayCasesSpec(task=_SPEC.task, case_count=250, case_digest="b" * 64, task_args={"languages": ["en"]})
    assert benchmarks._task_replay_pins(other) != benchmarks._task_replay_pins(_SPEC)


def test_a_key_in_both_registries_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 5: assembly never silently picks one of two declarations."""
    monkeypatch.setitem(TASK_REPLAY_CASES, "gsm8k", _SPEC)
    with pytest.raises(ValueError, match="gsm8k.*both"):
        benchmarks._cases_declaration("gsm8k")


def test_hugging_face_declarations_still_resolve() -> None:
    assert benchmarks._cases_declaration("gsm8k") is BENCHMARK_CASES["gsm8k"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/inspect/test_task_replay_assembly.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute '_task_replay_pins'`.

- [ ] **Step 3: Implement** in `benchmarks.py` (import `TASK_REPLAY_CASES`, `TaskReplayCasesSpec` from `prepare`, `prepare_replayed_cases` from `task_replay`):

```python
def _cases_declaration(key: str) -> CasesSpec | TaskReplayCasesSpec:
    """The one Case Preparation declaration for a Benchmark key, from whichever registry holds it."""

    if key in BENCHMARK_CASES and key in TASK_REPLAY_CASES:
        raise ValueError(f"{key}: declared in both BENCHMARK_CASES and TASK_REPLAY_CASES")
    if key in TASK_REPLAY_CASES:
        return TASK_REPLAY_CASES[key]
    return BENCHMARK_CASES[key]


def _task_replay_pins(cases_spec: TaskReplayCasesSpec) -> tuple[str, ...]:
    """Benchmark-identity pins for a Task-replay Benchmark.

    WHY these three and nothing else: the Case Digest already seals every written byte
    (inputs, templates, system text, Grading Material), so the task reference and its args
    name WHERE the Cases come from and the digest pins WHAT they are.
    """

    task_args: str = json.dumps(cases_spec.task_args or {}, sort_keys=True)
    return (f"task={cases_spec.task}", f"task_args={task_args}", f"case_digest={cases_spec.case_digest}")
```

In `_assemble`, replace the declaration lookup and the two lines that use it:

```python
    cases_spec: CasesSpec | TaskReplayCasesSpec = _cases_declaration(spec.key)
    _check_answer_key_opt_in(spec, cases_spec)
    identity_pins: tuple[str, ...]
    prepare: Callable[[Path], dict[str, Any]]
    if isinstance(cases_spec, TaskReplayCasesSpec):
        identity_pins = _task_replay_pins(cases_spec)
        prepare = partial(prepare_replayed_cases, cases_spec)
    else:
        identity_pins = _revision_pins(cases_spec)
        prepare = partial(prepare_cases, cases_spec)
    return single_shot_benchmark(
        ...,
        revision_pins=identity_pins + _judge_prompt_pins(spec),
        ...,
        prepare=prepare,
        ...
    )
```

(Keep every other keyword argument exactly as it is; import `Callable`, `Path`, `Any` if the module lacks them.) Widen `_check_answer_key_opt_in(spec: BenchmarkSpec, cases_spec: CasesSpec | TaskReplayCasesSpec)`; it only reads `has_answer_key`, which both types carry.

- [ ] **Step 4: Run the new tests and the revision guard**

Run: `uv run pytest tests/unit/inspect/test_task_replay_assembly.py tests/unit/inspect/test_published_revisions.py tests/unit/inspect/test_inspect_imported_benchmarks.py tests/unit/inspect/test_judged_benchmark_assembly.py -q`
Expected: all PASS; `test_published_benchmark_revision_is_byte_identical` unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine_inspect/benchmarks.py tests/unit/inspect/test_task_replay_assembly.py
git commit -m "feat(screamingface-engine): assemble Task-replay Benchmarks, pinned by their Case Digest"
```

---

### Task 5: Strict mode for the PR image job

**Files:**
- Modify: `src/screamingface_engine/benchmarks/prepare.py` (`_prepare`, add `FAIL_ON_CHANGED_CASES_ENV`)
- Modify: `Dockerfile.benchmark` (one `ARG`, forwarded into the prepare `RUN`)
- Modify: `.github/workflows/screamingface-engine-tests.yml` (one build-arg line in the `image` job; owner-approved 2026-09-30)
- Test: `tests/unit/test_benchmark_deployment.py` (extend)

**Interfaces:**
- Consumes: `CHANGED_CASES_KEY` (Task 3).
- Produces: `FAIL_ON_CHANGED_CASES_ENV = "SCREAMINGFACE_FAIL_ON_CHANGED_CASES"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_benchmark_deployment.py`; import `CHANGED_CASES_KEY` from `deployment`)

```python
def _prepare_with_changed_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two bundles skipped for changed Cases, one prepared normally."""
    summaries = {
        "inspect-agieval": {"cases": 0, CHANGED_CASES_KEY: "agieval: Case Digest aaa does not match bbb"},
        "inspect-gsm8k": {"cases": 1319},
        "inspect-mgsm": {"cases": 0, CHANGED_CASES_KEY: "mgsm: replay timed out after 1800s"},
    }

    def prepare(_root: Path, on_prepared: object = None, **_only: object) -> dict[str, object]:
        for bundle, summary in summaries.items():
            if on_prepared is not None:
                on_prepared(bundle, summary)  # type: ignore[operator]
        return summaries

    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", prepare)


def test_strict_mode_fails_after_preparing_everything_and_names_every_changed_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec R11: the PR that changed Cases can't merge, and its log lists all of them at once."""
    _prepare_with_changed_cases(monkeypatch)
    monkeypatch.setenv(prepare_module.FAIL_ON_CHANGED_CASES_ENV, "1")
    assert prepare_module.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 3  # every audit record still printed
    assert "inspect-agieval: agieval: Case Digest aaa does not match bbb" in captured.err
    assert "inspect-mgsm: mgsm: replay timed out after 1800s" in captured.err


def test_without_strict_mode_changed_cases_only_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deployed images keep every other Benchmark when one Case Source breaks."""
    _prepare_with_changed_cases(monkeypatch)
    monkeypatch.delenv(prepare_module.FAIL_ON_CHANGED_CASES_ENV, raising=False)
    assert prepare_module.main(["--root", str(tmp_path)]) == 0


def test_only_the_pr_image_job_runs_strict() -> None:
    workflows = REPOSITORY_ROOT / ".github" / "workflows"
    if not workflows.is_dir():
        pytest.skip("engine checked out apart from the monorepo; the workflows are absent")
    assert "SCREAMINGFACE_FAIL_ON_CHANGED_CASES=1" in (workflows / "screamingface-engine-tests.yml").read_text(
        encoding="utf-8"
    )
    for deployed in ("dev-build-screamingface-engine.yml", "release-screamingface-engine.yml"):
        assert "SCREAMINGFACE_FAIL_ON_CHANGED_CASES" not in (workflows / deployed).read_text(encoding="utf-8")


def test_benchmark_image_forwards_strict_mode_into_case_preparation() -> None:
    body = (Path(__file__).parents[2] / "Dockerfile.benchmark").read_text(encoding="utf-8")
    assert "ARG SCREAMINGFACE_FAIL_ON_CHANGED_CASES=" in body
    assert 'SCREAMINGFACE_FAIL_ON_CHANGED_CASES="$SCREAMINGFACE_FAIL_ON_CHANGED_CASES"' in body
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_benchmark_deployment.py -q -k "strict or changed_cases"`
Expected: FAIL with `AttributeError: ... has no attribute 'FAIL_ON_CHANGED_CASES_ENV'`.

- [ ] **Step 3: Implement.** In `src/screamingface_engine/benchmarks/prepare.py` (import `os`, and `CHANGED_CASES_KEY` from `.deployment`):

```python
#: Set to "1" only by the PR image job: after every bundle is prepared, fail if any was
#: skipped because its Cases changed, so the PR that changed them can't merge (OME-1273).
FAIL_ON_CHANGED_CASES_ENV = "SCREAMINGFACE_FAIL_ON_CHANGED_CASES"
```

and replace the tail of `_prepare`:

```python
    try:
        prepared = prepare_builtin_assets(root, emit, only=only)
    except BenchmarkAssetPreparationError as exc:
        print(f"benchmark asset preparation failed: {exc}", file=sys.stderr)
        return 1
    if os.environ.get(FAIL_ON_CHANGED_CASES_ENV) == "1":
        # WHY after the loop, not in the preparer: one run lists every changed bundle.
        changed: dict[str, str] = {
            bundle: str(summary[CHANGED_CASES_KEY])
            for bundle, summary in prepared.items()
            if CHANGED_CASES_KEY in summary
        }
        for bundle, reason in changed.items():
            print(f"{bundle}: {reason}", file=sys.stderr)
        if changed:
            print(
                f"benchmark asset preparation failed: {len(changed)} bundle(s) have changed Cases "
                f"({FAIL_ON_CHANGED_CASES_ENV}=1)",
                file=sys.stderr,
            )
            return 1
    return 0
```

In `Dockerfile.benchmark`, after `ARG SCREAMINGFACE_HF_TOKEN_PRESENT=`:

```dockerfile
# The PR image job sets this so a PR that changes any Task-replay Benchmark's Cases fails
# (OME-1273). Deployed builds leave it empty: a changed Benchmark goes SKIPPED, the rest ship.
ARG SCREAMINGFACE_FAIL_ON_CHANGED_CASES=
```

and in the prepare `RUN`, add the line after the existing `SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=…` line:

```dockerfile
    SCREAMINGFACE_FAIL_ON_CHANGED_CASES="$SCREAMINGFACE_FAIL_ON_CHANGED_CASES" \
```

In `.github/workflows/screamingface-engine-tests.yml`, job `image`, step "Build the benchmark image", add under `build-args:`:

```yaml
            SCREAMINGFACE_FAIL_ON_CHANGED_CASES=1
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_benchmark_deployment.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screamingface_engine/benchmarks/prepare.py Dockerfile.benchmark ../../.github/workflows/screamingface-engine-tests.yml tests/unit/test_benchmark_deployment.py
git commit -m "feat(screamingface-engine): fail the PR image job when Task-replay Cases change"
```

---

### Task 6: Gates, ledger, PR

**Files:**
- Create: `docs/work/2026-09-30-ome-1273-task-replay-image.md` (from `docs/work/TEMPLATE.md`, at the START of Task 1, `ticket: OME-1273`)

- [ ] **Step 1:** Run the gates from Global Constraints. Expected: ruff, format, pyright clean; `tests/unit` green, with `test_published_benchmark_revision_is_byte_identical` unchanged.
- [ ] **Step 2:** Diff size check: `git diff --stat upstream/main` under ~500 lines excluding tests; if over, say so in the PR body.
- [ ] **Step 3:** Fill the ledger outcome (files, commits, gate counts, deviations), commit it, push `OME-1273-task-replay-image` to `upstream`, open a draft PR titled `feat(screamingface-engine): prepare Task-replay Benchmarks and check their Case Digest`, body on the altitude ladder with `Refs: [OME-1273](https://linear.app/openmined/issue/OME-1273/import-the-single-turn-benchmarks-the-importer-still-refuses)`, and attach the PR link to OME-1273. OME-1273 stays In Progress: its mirror closes with PR 6.
