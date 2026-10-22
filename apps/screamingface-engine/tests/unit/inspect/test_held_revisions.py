# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The held Benchmarks' computed fingerprints — frozen as literals beside their published ids.

A held row publishes its old revision (``published_revision``) while a grading fix moves the
fingerprint its inputs compute (OME-1701; owner decision, 2026-10-22: revisions are frozen).
Nothing compares the two at run time (owner decision, 2026-10-15), and
``test_published_revisions.py`` sees only the held id, so without these literals a further
change to a held row's scorer, Cases or pins would move nothing a reviewer sees. Each literal
is the revision the row would publish with its hold removed.

When a literal here changes on purpose, updating it IS the review act: the row's grading
changed again under a held id, and the owner decides whether the published id moves too.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inverted_grade import _assembled  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec  # noqa: E402

#: key → (the published revision the row holds, the fingerprint its inputs compute).
_HELD: dict[str, tuple[str, str]] = {
    # OME-1701 PR 1: paws and boolq grade on a bare Yes or No (inspect_evals PR #2334 adopted).
    "paws": ("8f4e0e9c0864a6e7", "ab44cff9bea304ca"),
    "boolq": ("00d4443ca7e66d43", "b4a47768ef2ebf95"),
}


@pytest.mark.parametrize("key", sorted(_HELD))
def test_a_held_rows_computed_fingerprint_is_frozen(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the hold changes what a row publishes, never what its inputs compute, so a
    grading change under a held id still fails a test (the scorer source joins the revision)."""

    held, computed = _HELD[key]
    spec: BenchmarkSpec = next(row for row in BENCHMARKS if row.key == key)

    unheld: str = str(
        _assembled(replace(spec, published_revision=None), monkeypatch).benchmark.revision
    )

    assert spec.published_revision == held
    assert unheld == computed, (
        f"{key}: the computed fingerprint moved ({computed} -> {unheld}) under the held id "
        f"{held}. The row's grading, Cases or pins changed: update the literal only with the "
        "owner's decision on whether the published id moves too."
    )
    # The fix did move the fingerprint, so the hold is what keeps the published id.
    assert computed != held
