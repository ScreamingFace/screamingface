# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Assembling a Task-replay Benchmark: its revision is pinned by task, args and Case Digest
(spec R12).

INVARIANT: two Task-replay Benchmarks that serve different Cases never share a Benchmark
Revision, and a Benchmark key resolves to exactly one Case Preparation declaration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.deployment import CHANGED_CASES_KEY  # noqa: E402
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    BENCHMARK_CASES,
    TASK_REPLAY_CASES,
    PreparedCase,
    TaskReplayCasesSpec,
)
from screamingface_engine_inspect.task_replay import TaskReplayError  # noqa: E402

_SPEC: TaskReplayCasesSpec = TaskReplayCasesSpec(
    task="inspect_evals.mgsm.mgsm:mgsm",
    case_count=250,
    case_digest="a" * 64,
    task_args={"languages": ["en"]},
)


def test_task_replay_pins_carry_task_args_and_digest() -> None:
    """WHY the digest is a pin: the digest seals every written byte, so the task and its
    args name where the Cases come from and the digest pins what they are."""

    assert benchmarks._task_replay_pins(_SPEC) == (
        "task=inspect_evals.mgsm.mgsm:mgsm",
        'task_args={"languages": ["en"]}',
        f"case_digest={'a' * 64}",
    )


def test_a_different_digest_is_a_different_revision_pin() -> None:
    other = TaskReplayCasesSpec(
        task=_SPEC.task, case_count=250, case_digest="b" * 64, task_args={"languages": ["en"]}
    )

    assert benchmarks._task_replay_pins(other) != benchmarks._task_replay_pins(_SPEC)


def test_a_key_in_both_registries_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 5: assembly never silently picks one of two declarations."""

    monkeypatch.setitem(TASK_REPLAY_CASES, "gsm8k", _SPEC)

    with pytest.raises(ValueError, match="gsm8k.*both"):
        benchmarks._cases_declaration("gsm8k")


def test_hugging_face_declarations_still_resolve() -> None:
    assert benchmarks._cases_declaration("gsm8k") is BENCHMARK_CASES["gsm8k"]


def test_a_task_replay_key_resolves_to_its_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(TASK_REPLAY_CASES, "mgsm_en", _SPEC)

    assert benchmarks._cases_declaration("mgsm_en") is _SPEC


def test_an_assembled_task_replay_benchmark_names_itself_in_a_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec R10: assembly hands Case Preparation the Benchmark key, so the SKIPPED reason
    a board visitor reads names the board, not the inspect task path."""

    def failed_fetch(spec: TaskReplayCasesSpec) -> list[PreparedCase]:
        raise TaskReplayError(f"{spec.task}: replay failed (exit 1): HTTP 404")

    row = next(spec for spec in benchmarks.BENCHMARKS if spec.key == "gsm8k")
    # WHY an empty registry: the real gsm8k is assembled elsewhere with another revision,
    # and this replay copy must not leak into later tests.
    monkeypatch.setattr("screamingface_engine_inspect.single_shot._BENCHMARKS_BY_ID", {})
    monkeypatch.delitem(BENCHMARK_CASES, "gsm8k")
    monkeypatch.setitem(TASK_REPLAY_CASES, "gsm8k", _SPEC)
    monkeypatch.setattr("screamingface_engine_inspect.task_replay.replayed_cases", failed_fetch)

    bundle = benchmarks._assemble(row).registration.asset_bundle
    assert bundle is not None
    summary = bundle.prepare(tmp_path / "out")

    assert summary[CHANGED_CASES_KEY].startswith("gsm8k: inspect_evals.mgsm.mgsm:mgsm")
