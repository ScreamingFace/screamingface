"""ONE parametrized end-to-end test per board, from recorded responses (OME-961).

The real user path, driven exactly like a notebook: ``sf.Client(engine_url=...)`` →
``client.evaluate(sf.Model(...), benchmark=<board>, limit=...)`` → grade → aggregate →
``Report`` — against the real engine and the real gateway whose only answers come from
that board's recorded cache snapshot. Deterministic, free (zero provider keys), and
compared against the board's golden with the R11 ladder: expression SHA first, then
case statuses, then per-case failure codes, then coverage counters, then the score as
a decimal string.

SKIP DISCIPLINE — a board with no fixtures SKIPS LOUDLY, naming exactly what is
missing; it never fake-passes. Three prerequisites per board:

- ``fixtures/snapshots/<board>.snapshot.gz`` — sliced cache dump (the owner records
  these from a seeded deployment; draco is the tracer board),
- ``fixtures/goldens/<board>.golden.json`` — the blessed expected outcome,
- prepared benchmark assets: ``screamingface prepare --all`` fills the default
  location (``<data-dir>/benchmark-assets``); ``$SCREAMINGFACE_E2E_ASSETS``
  overrides it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from harness._gating import GOLDENS_DIR, SNAPSHOTS_DIR, require_e2e_stack
from harness.cache_seeded import CacheSeededGateway
from harness.goldens import (
    ActualOutcome,
    GoldenReport,
    build_candidate,
    compare_outcome,
    failure_map,
    load_golden,
)
from harness.stack import replay_stack

pytestmark = pytest.mark.e2e

#: Every board the engine registers today (screamingface_engine.benchmarks.builtins).
BOARDS = (
    "draco",
    "draco-3pass",
    "ifeval",
    "healthbench-worst30",
    "healthbench-professional",
)

_ASSETS_ENV = "SCREAMINGFACE_E2E_ASSETS"

#: Which prepared-asset bundle each board reads (bundles are shared across variants).
_ASSET_BUNDLE = {
    "draco": "draco",
    "draco-3pass": "draco",
    "ifeval": "ifeval",
    "healthbench-worst30": "healthbench",
    "healthbench-professional": "healthbench",
}


def _assets_root() -> Path:
    # WHY this default: it is where `screamingface prepare` writes, so the assets a
    # dev prepares for the stack are the assets these tests find (OME-1001).
    from screamingface._runtime.config import default_data_dir

    configured = os.environ.get(_ASSETS_ENV)
    if configured:
        return Path(configured)
    return default_data_dir() / "benchmark-assets"


def _require_board_fixtures(board: str) -> tuple[Path, Path | None, GoldenReport]:
    """The board's snapshot + optional manifest + golden — or a LOUD skip naming the gap."""
    snapshot = SNAPSHOTS_DIR / f"{board}.snapshot.gz"
    golden_path = GOLDENS_DIR / f"{board}.golden.json"
    missing = [str(path) for path in (snapshot, golden_path) if not path.exists()]
    if missing:
        pytest.skip(
            f"board '{board}' has no recorded fixtures yet — missing: {', '.join(missing)}. "
            f"Record a sliced cache snapshot + blessed golden (draco is the tracer board); "
            f"this skip is the honest state, never a pass."
        )
    assets = _assets_root() / _ASSET_BUNDLE[board]
    if not assets.is_dir():
        pytest.skip(
            f"board '{board}' needs prepared benchmark assets at {assets} "
            f"(run `screamingface prepare --all`, or point {_ASSETS_ENV} at them)"
        )
    manifest = SNAPSHOTS_DIR / f"{board}.manifest.json"
    return snapshot, (manifest if manifest.exists() else None), load_golden(golden_path)


@pytest.mark.parametrize("board", BOARDS)
def test_board_replays_end_to_end_and_matches_its_golden(board: str, tmp_path) -> None:
    # Fixture presence is checked FIRST so "no fixtures yet" is visible even on a
    # machine that could not run the stack anyway; then the stack gate.
    snapshot, manifest, golden = _require_board_fixtures(board)
    require_e2e_stack()

    import screamingface as sf

    # The golden carries its own replay input: sf.Model for `kind: model` goldens,
    # the recorded Fusion lineup for `kind: fusion` (OME-978).
    candidate = build_candidate(golden)
    backend = CacheSeededGateway(snapshot=snapshot, manifest=manifest, work_dir=tmp_path)
    with replay_stack(backend, work_dir=tmp_path, assets_dir=_assets_root()) as stack:
        with sf.Client(engine_url=stack.engine_url) as client:
            report = client.evaluate(
                candidate,
                benchmark=board,
                limit=golden.limit,
                progress=False,
            )

    assert report.benchmark.id == board
    assert report.benchmark.revision == golden.revision, (
        f"benchmark revision drifted (golden {golden.revision}, engine "
        f"{report.benchmark.revision}) — the recorded fixtures describe an older board"
    )
    candidate = report.candidates.only
    compare_outcome(
        golden,
        ActualOutcome(
            rendered_url4=str(candidate.url4),
            final_score=candidate.score,
            case_statuses={str(case.case_id): str(case.status) for case in candidate.cases},
            coverage=candidate.coverage,
            # OME-1094: WHY a case failed, not just that it did — the codes rung.
            case_failures=failure_map(candidate.cases),
        ),
    )
