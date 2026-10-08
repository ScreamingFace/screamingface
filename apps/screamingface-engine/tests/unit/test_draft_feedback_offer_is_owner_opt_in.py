"""Draft Feedback (the Corrective Loop's mid-run check) is an owner decision per Benchmark.

WHY this file exists (owner rule, 2026-10-07, OME-1513): "never turn draft feedback /
with_check_surface=True / corrective loop on by auto / default — it needs my explicit allow to
turn it on for a benchmark". Per-Benchmark tests pin each declaration, but none of them would
notice a NEW hand-built Benchmark or imported row quietly declaring an offer. This one asserts
the whole catalogue: today the only Benchmark with the offer is IFEval, because the paper the
Corrective Loop implements worked on IFEval. Turning it on anywhere else is a one-line change
to this set — made by the owner, with the reason on the row or declaration.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine_inspect.benchmarks import BENCHMARKS

#: The Benchmarks the owner has allowed to advertise Draft Feedback.
_OWNER_ALLOWED_OFFERS: frozenset[str] = frozenset({"ifeval"})


def test_only_the_owner_allowed_benchmarks_advertise_draft_feedback() -> None:
    """INVARIANT: across every installed Benchmark, hand-built and imported alike, the set
    that carries a check-surface offer is exactly the owner's allow-list."""

    offering: set[str] = {b.id for b in BUILTIN_BENCHMARKS if b.check_surface is not None}

    assert offering == set(_OWNER_ALLOWED_OFFERS)


def test_no_imported_row_asks_for_draft_feedback() -> None:
    """The row level too, so the rule holds even where the extra is not installed and the
    imported Benchmarks are not assembled into the catalogue: no spec row sets the flag."""

    asking: list[str] = [spec.key for spec in BENCHMARKS if spec.with_check_surface]

    assert asking == []
