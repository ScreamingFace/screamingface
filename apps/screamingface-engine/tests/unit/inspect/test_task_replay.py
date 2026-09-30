# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Task replay: the eval's own task function runs in a child process and yields prepared
Cases (spec R2, R9, R10).

INVARIANT: the child always starts with empty caches and reports through a file, never
stdout, so what it returns is what a fresh fetch produces and nothing an eval prints can
corrupt it. INVARIANT: Cases whose count or Case Digest differ from the pinned values are
never written; the Benchmark goes SKIPPED with the reason instead.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.deployment import CHANGED_CASES_KEY  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    SKIPPED_MARKER,
    TaskReplayCasesSpec,
    case_digest,
)
from screamingface_engine_inspect.task_replay import (  # noqa: E402
    TaskReplayError,
    prepare_replayed_cases,
    replay_environment,
    replayed_cases,
)

#: A stand-in eval: its task functions build Samples the way an inspect_evals loader would.
FAKE_EVAL: str = textwrap.dedent(
    """
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
    """
)

_UNPINNED: str = "0" * 64


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the child process can import it."""

    (tmp_path / "fake_replay_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return "fake_replay_eval"


def _pinned(fake_eval: str) -> TaskReplayCasesSpec:
    """A declaration whose count and digest are what the stand-in task really produces."""

    probe: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic", case_count=2, case_digest=_UNPINNED
    )
    return TaskReplayCasesSpec(
        task=probe.task, case_count=2, case_digest=case_digest(replayed_cases(probe))
    )


# ── the replay itself (Task 2) ───────────────────────────────────────────────


def test_replay_returns_the_cases_the_task_builds(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:arithmetic", case_count=2, case_digest=_UNPINNED)

    prepared = replayed_cases(spec)

    assert [item["case"]["input"] for item in prepared] == [
        "What is 6 times 7?",
        "What is 2 plus 2?",
    ]
    assert [item["grading_material"] for item in prepared] == [{"target": "42"}, {"target": "4"}]


def test_replay_passes_task_args_and_is_deterministic(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(
        task=f"{fake_eval}:arithmetic",
        task_args={"extra": True},
        case_count=3,
        case_digest=_UNPINNED,
    )

    first = replayed_cases(spec)

    assert len(first) == 3
    assert case_digest(first) == case_digest(replayed_cases(spec))


def test_a_task_that_raises_is_a_named_replay_failure(fake_eval: str) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    with pytest.raises(TaskReplayError, match="upstream URL returned 404"):
        replayed_cases(spec)


def test_a_stalled_fetch_ends_after_the_timeout(fake_eval: str) -> None:
    """Review Focus 2: a hung download must never hang the image build."""

    spec = TaskReplayCasesSpec(task=f"{fake_eval}:stalled", case_count=0, case_digest=_UNPINNED)

    with pytest.raises(TaskReplayError, match="timed out"):
        replayed_cases(spec, timeout=2)


def test_the_child_always_gets_its_own_empty_caches(tmp_path: Path) -> None:
    """Review Focus 4: a builder's stale cache must not hide a dead URL."""

    base = {
        "INSPECT_EVALS_CACHE_DIR": "/home/dev/.cache/inspect_evals",
        "HF_TOKEN": "hf_x",
        "PATH": "/bin",
    }

    env = replay_environment(tmp_path, base)

    assert env["INSPECT_EVALS_CACHE_DIR"] == str(tmp_path / "inspect_evals")
    assert env["HF_DATASETS_CACHE"] == str(tmp_path / "hf_datasets")
    assert env["HF_HUB_CACHE"] == str(tmp_path / "hf_hub")
    # WHY HF_TOKEN survives: gated datasets still need it; only caches are replaced.
    assert env["HF_TOKEN"] == "hf_x"
    assert env["PATH"] == "/bin"


# ── Case Preparation with the Case Digest check (Task 3) ─────────────────────


def test_matching_digest_writes_the_cases(fake_eval: str, tmp_path: Path) -> None:
    spec = _pinned(fake_eval)
    out = tmp_path / "out"

    summary = prepare_replayed_cases(spec, out)

    assert summary["cases"] == 2
    assert summary["case_digest"] == spec.case_digest
    assert (out / "cases.json").is_file()
    assert not (out / SKIPPED_MARKER).exists()


def test_a_changed_digest_serves_nothing_and_names_the_reason(
    fake_eval: str, tmp_path: Path
) -> None:
    """Spec R10: different Cases are never served; the marker says why."""

    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(task=pinned.task, case_count=2, case_digest="f" * 64)
    out = tmp_path / "out"

    summary = prepare_replayed_cases(spec, out)

    reason = (out / SKIPPED_MARKER).read_text(encoding="utf-8")
    assert not (out / "cases.json").exists()
    assert "f" * 64 in reason
    assert pinned.case_digest in reason
    assert summary["cases"] == 0
    assert summary[CHANGED_CASES_KEY] == reason.strip()


def test_a_changed_case_count_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    pinned = _pinned(fake_eval)
    spec = TaskReplayCasesSpec(
        task=pinned.task,
        task_args={"extra": True},
        case_count=2,
        case_digest=pinned.case_digest,
    )

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert "3 Cases, pinned case count is 2" in summary[CHANGED_CASES_KEY]
    assert not (tmp_path / "out" / "cases.json").exists()


def test_a_failed_fetch_serves_nothing(fake_eval: str, tmp_path: Path) -> None:
    spec = TaskReplayCasesSpec(task=f"{fake_eval}:broken", case_count=2, case_digest=_UNPINNED)

    summary = prepare_replayed_cases(spec, tmp_path / "out")

    assert "upstream URL returned 404" in summary[CHANGED_CASES_KEY]
    assert not (tmp_path / "out" / "cases.json").exists()
