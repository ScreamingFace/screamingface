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

from screamingface_engine.benchmarks.deployment import UNCONFIRMED_CASES_KEY  # noqa: E402
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
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
    monkeypatch.setitem(TASK_REPLAY_CASES, "gsm8k", _SPEC)
    monkeypatch.setattr("screamingface_engine_inspect.task_replay.replayed_cases", failed_fetch)

    bundle = benchmarks._assemble(row).registration.asset_bundle
    assert bundle is not None
    summary = bundle.prepare(tmp_path / "out")

    assert summary[UNCONFIRMED_CASES_KEY].startswith("gsm8k: inspect_evals.mgsm.mgsm:mgsm")


def test_excluded_sample_ids_are_a_revision_pin() -> None:
    """Spec R18: the Named Deviation removes questions from the Benchmark, so it is
    Benchmark identity, written in sorted order so the row's own order never matters."""

    excluded = TaskReplayCasesSpec(
        task=_SPEC.task,
        case_count=248,
        case_digest=_SPEC.case_digest,
        task_args=_SPEC.task_args,
        excluded_sample_ids=("mgsm:9", "mgsm:10"),
    )

    assert benchmarks._task_replay_pins(excluded) == (
        *benchmarks._task_replay_pins(_SPEC),
        "excluded_sample_ids=mgsm:10,mgsm:9",
    )


def test_every_task_replay_row_without_an_exclusion_keeps_its_three_pins() -> None:
    """No published revision moves: a row that excludes nothing pins exactly what it pinned
    before R18, so the 19 Task-replay Benchmarks already on main keep their revisions."""

    for key, spec in TASK_REPLAY_CASES.items():
        # WHY `not spec.source_pins` (OME-1460, owner-approved): the five rows that read the
        # Hub gain a Hub pin on purpose (spec D4); test_published_revisions.py freezes the rest.
        if spec.excluded_sample_ids is None and not spec.source_pins:
            assert len(benchmarks._task_replay_pins(spec)) == 3, key


# --- OME-1460: the source pins join identity (spec R7) -------------------------------------

_MEDQA_SHA: str = "ddef95d268cdad413693d634279a9a679d468469"


def test_source_pins_join_identity_as_a_fourth_pin() -> None:
    """Two declarations with the same task and digest but different Hub commits are two
    Benchmarks, so the commit rides the revision (spec R7)."""

    pinned = TaskReplayCasesSpec(
        task=_SPEC.task,
        case_count=250,
        case_digest="a" * 64,
        task_args={"languages": ["en"]},
        source_pins={"bigbio/med_qa": _MEDQA_SHA},
    )

    assert benchmarks._task_replay_pins(pinned) == (
        *benchmarks._task_replay_pins(_SPEC),
        f'source_pins={{"bigbio/med_qa": "{_MEDQA_SHA}"}}',
    )


def test_source_pins_are_written_sorted_so_dict_order_never_moves_a_revision() -> None:
    first = TaskReplayCasesSpec(
        task=_SPEC.task,
        case_count=1,
        case_digest="a" * 64,
        source_pins={"b/b": "1" * 40, "a/a": "2" * 40},
    )
    second = TaskReplayCasesSpec(
        task=_SPEC.task,
        case_count=1,
        case_digest="a" * 64,
        source_pins={"a/a": "2" * 40, "b/b": "1" * 40},
    )

    assert benchmarks._task_replay_pins(first) == benchmarks._task_replay_pins(second)


def test_seeds_and_the_gate_add_no_identity_pin() -> None:
    """INVARIANT: no published revision moves for a field the digest already seals (the
    seeds fix the order, which the digest seals) or that is access, not identity (the gate)."""

    seeded = TaskReplayCasesSpec(
        task=_SPEC.task,
        case_count=250,
        case_digest="a" * 64,
        task_args={"languages": ["en"]},
        shuffle_seed=1234,
        choice_shuffle_seed=7,
        needs_hf_token=True,
    )

    assert benchmarks._task_replay_pins(seeded) == benchmarks._task_replay_pins(_SPEC)
