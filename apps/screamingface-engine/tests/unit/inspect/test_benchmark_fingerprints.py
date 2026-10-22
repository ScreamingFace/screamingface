# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The Benchmarks' computed fingerprints — frozen as literals beside their published ids.

A Benchmark's fingerprint is the hash of everything that defines it: its Cases, its
scorer's source, its judge and the pinned packages. It is an alarm, never published when
the row sets ``published_revision``: the Engine then publishes that id, and nothing
compares the two at run time (owner decision, 2026-10-15). ``test_published_revisions.py``
pins the id a row publishes; this file pins what its inputs compute. A held row
(OME-1701; owner decision, 2026-10-22: revisions are frozen) publishes its old id while a
grading fix moves its fingerprint, so without these literals a later change to its
scorer, Cases or pins would move nothing a reviewer sees.

When a literal here changes, updating it IS the review act: if the exam is unchanged,
update the literal; if the exam changed, the published id moves too, and only with the
owner's sign-off.

OME-1610 extends this file to every Benchmark row and retires the allow-list in
``test_published_revision.py``; today it pins the rows OME-1701 holds.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inverted_grade import _assembled  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402

#: key → the fingerprint the row's inputs compute (what it would publish with no hold).
_FINGERPRINTS: dict[str, str] = {
    # OME-1701 PR 1: paws and boolq grade on a bare Yes or No (inspect_evals PR #2334 adopted).
    "paws": "992540ea3309d384",
    "boolq": "588977e58b380d7f",
    # OME-1701 PR 2: chembench grades its letters as a set (inspect_evals PR #2591 adopted);
    # infinite_bench_math_find grades by the first number (inspect_evals PR #2346 adopted).
    "chembench": "b86658ea78c51962",
    "infinite_bench_math_find": "1ed274442ad5dba1",
}


@pytest.mark.parametrize("key", sorted(_FINGERPRINTS))
def test_the_fingerprint_follows_the_exam_even_under_a_held_id(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: a hold changes what a row publishes, never what its inputs compute, so a
    change to a held row's scorer, Cases or pins still fails a test (the scorer source joins
    the fingerprint)."""

    spec: BenchmarkSpec = next(row for row in BENCHMARKS if row.key == key)

    computed: str = str(
        _assembled(replace(spec, published_revision=None), monkeypatch).benchmark.revision
    )

    assert computed == _FINGERPRINTS[key], (
        f"{key}: the fingerprint moved ({_FINGERPRINTS[key]} -> {computed}). If the exam is "
        "unchanged, update this literal; if the exam changed, the published id moves too, and "
        "only with the owner's sign-off (test_published_revisions.py)."
    )
