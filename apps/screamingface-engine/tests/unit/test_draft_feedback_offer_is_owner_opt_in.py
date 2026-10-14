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

from pathlib import Path

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS, BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine_inspect.benchmarks import BENCHMARKS
from screamingface_engine_inspect.single_shot import imported_benchmark_id
from url4.peer.server import Url4Node

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


#: Every hand-built Benchmark whose Draft Feedback offer is off (the imported rows get the same
#: gate from the inspect plugin's own installer).
_HAND_BUILT_WITHOUT_AN_OFFER: list[Benchmark] = [
    registration.benchmark
    for registration in BUILTIN_REGISTRATIONS
    if registration.benchmark.check_surface is None
]


@pytest.mark.parametrize("benchmark", _HAND_BUILT_WITHOUT_AN_OFFER, ids=lambda b: b.id)
def test_an_offer_that_is_off_is_not_reachable_by_url4_string(
    benchmark: Benchmark, tmp_path: Path
) -> None:
    """INVARIANT (OME-1527): a Benchmark with no Draft Feedback offer installs no check-surface
    route. The SDK refuses a Corrective Loop on such a Benchmark, but a raw url4 string sent to
    the Engine never passes through that refusal; an installed route would answer it with a
    paid Judge call (draco, gdpval and healthbench used to install theirs unconditionally).

    Installation is lazy, so an empty asset root is enough to read the installed routes."""

    node: Url4Node = Url4Node("offer-off")
    benchmark.install(node, tmp_path)

    check_routes: list[str] = [
        route for route in node.processor_routes() if "/check-surface" in route
    ]
    assert check_routes == []


def test_only_an_owner_allowed_benchmark_sends_its_scorers_own_words() -> None:
    """INVARIANT (OME-1527, R9): a row may send the Candidate its scorer's own Draft Feedback
    words only on a Benchmark this allow-list names. Those words cross into the Candidate's
    context, so the owner, having read that scorer, is the one who turns them on."""

    # WHY catalogue ids, not row keys: the allow-list names catalogue ids, and an inspect_evals
    # row keyed "ifeval" is served as "inspect-ifeval", a Benchmark the owner never allowed.
    asking: set[str] = {
        imported_benchmark_id(spec.key, spec.origin)
        for spec in BENCHMARKS
        if spec.scorer_draft_feedback
    }

    assert asking <= _OWNER_ALLOWED_OFFERS
