"""The GSM8K vote replay lane, from recorded responses (OME-1289 E4a, EV-12).

End-to-end tests of the whole reducer path, driven exactly like a notebook:
``client.evaluate(sf.Fusion(sf.samples(model, 5), synthesizer=sf.Vote(...)), benchmark=...)``
against the real engine and the real gateway whose only answers come from the lane's recorded cache
snapshot. Free and keyless. The run is compared to the lane's golden with the five locks of
``test_boards`` (expression sha, case statuses, failure codes, coverage, score) plus an evidence
lock: what the combine step read and decided for one case.

Two more claims ride on the same recording. SG#15: the cost-weighted vote (``weights=
sf.signal("cost_usd")``) gives the same signals, weights and tally from the cached replay as it gave
live (SG-D1). RT#16: each replayed ``report-trace.v1`` differs from the live one only in model-call
accounting (RT-4). One stack boot serves all three tests (a module-scoped fixture).

SKIP DISCIPLINE (like ``test_boards``): a lane with no fixtures SKIPS LOUDLY, naming exactly what is
missing. It never fake-passes. Three prerequisites:

- ``fixtures/snapshots/inspect-gsm8k-vote.snapshot.gz`` (and its manifest): the sliced cache,
- ``fixtures/goldens/inspect-gsm8k-vote.reducer-golden.json``: the blessed expected outcome,
- prepared assets of the imported board at ``<assets>/inspect-gsm8k``.

The first two come from a PAID recording that only the user can run (an OpenRouter key and a
seed-capable model). ``fixtures/reducer_lane.py`` has the commands (``record``, then ``bless``). The
engine of this lane is synced WITH the ``benchmarks`` extra (``harness.inspect_stack``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest
from harness._gating import GOLDENS_DIR, SNAPSHOTS_DIR, require_e2e_stack
from harness.benchmark_assets import ASSETS_ENV, assets_root
from harness.cache_seeded import CacheSeededGateway
from harness.goldens import ActualOutcome, compare_outcome, failure_map
from harness.inspect_stack import inspect_replay_stack
from harness.reducer_golden import (
    ReducerGolden,
    assert_evidence_lock,
    assert_signal_replay,
    load_reducer_golden,
)
from harness.replay_trace import trace_drift

pytestmark = pytest.mark.e2e

LANE = "inspect-gsm8k-vote"
BOARD = "inspect-gsm8k"


def _require_lane_fixtures() -> tuple[Path, Path | None, ReducerGolden]:
    """The lane's snapshot + optional manifest + golden, or a LOUD skip naming the gap."""
    snapshot = SNAPSHOTS_DIR / f"{LANE}.snapshot.gz"
    golden_path = GOLDENS_DIR / f"{LANE}.reducer-golden.json"
    missing = [str(path) for path in (snapshot, golden_path) if not path.exists()]
    if missing:
        pytest.skip(
            f"lane '{LANE}' has no recorded fixtures yet: missing {', '.join(missing)}. "
            f"They come from a paid OpenRouter recording the user runs "
            f"(tests/e2e/fixtures/reducer_lane.py: `record`, then `bless`); "
            f"this skip is the honest state, never a pass."
        )
    assets = assets_root() / BOARD
    if not assets.is_dir():
        pytest.skip(
            f"lane '{LANE}' needs prepared assets of '{BOARD}' at {assets} (run "
            f"`uv run python -m screamingface_engine.benchmarks.prepare --root <assets-root> "
            f"--bundle {BOARD}` in apps/screamingface-engine with `uv sync --extra benchmarks`, "
            f"or point {ASSETS_ENV} at them)"
        )
    manifest = SNAPSHOTS_DIR / f"{LANE}.manifest.json"
    return snapshot, (manifest if manifest.exists() else None), load_reducer_golden(golden_path)


@pytest.fixture(scope="module")
def _replayed(tmp_path_factory: pytest.TempPathFactory) -> tuple[ReducerGolden, Any, Any]:
    """One replay stack, both candidates: ``(golden, plain_report, signal_report)``."""
    # Fixture presence is checked FIRST so "no fixtures yet" is visible even on a machine that
    # could not run the stack anyway; then the stack gate.
    snapshot, manifest, golden = _require_lane_fixtures()
    require_e2e_stack()

    import screamingface as sf

    work_dir = tmp_path_factory.mktemp("reducer-replay")
    backend = CacheSeededGateway(snapshot=snapshot, manifest=manifest, work_dir=work_dir)
    signal_spec = golden.candidate.model_copy(update={"weights": golden.signal_replay.weights})
    with inspect_replay_stack(backend, work_dir=work_dir, assets_dir=assets_root()) as stack:
        with sf.Client(engine_url=stack.engine_url) as client:
            # The signal vote first, as `record` ran it.
            signal_report = client.evaluate(
                signal_spec.build(), benchmark=BOARD, limit=golden.limit, progress=False
            )
            report = client.evaluate(
                golden.candidate.build(), benchmark=BOARD, limit=golden.limit, progress=False
            )
    return golden, report, signal_report


def test_gsm8k_vote_run_reports_evidence_end_to_end(
    _replayed: tuple[ReducerGolden, Any, Any],
) -> None:
    golden, report, _ = _replayed

    assert report.benchmark.id == BOARD
    assert report.benchmark.revision == golden.revision, (
        f"benchmark revision drifted (golden {golden.revision}, engine "
        f"{report.benchmark.revision}): the recorded fixtures describe an older board"
    )
    candidate = report.candidates.only
    # The five locks: expression sha, statuses, failure codes, coverage, score (in that order).
    compare_outcome(
        golden.outcome(),
        ActualOutcome(
            rendered_url4=str(candidate.url4),
            final_score=candidate.score,
            case_statuses={str(case.case_id): str(case.status) for case in candidate.cases},
            coverage=candidate.coverage,
            case_failures=failure_map(candidate.cases),
        ),
    )
    # The sixth lock: the combine evidence of the pinned case.
    assert_evidence_lock(golden, candidate.cases)


def test_cached_replay_gives_same_signals_and_tally(
    _replayed: tuple[ReducerGolden, Any, Any],
) -> None:
    golden, _, signal_report = _replayed
    candidate = signal_report.candidates.only

    assert_signal_replay(golden, str(candidate.url4), candidate.cases)


def test_cached_replay_trace_differs_only_in_cache_and_accounting(
    _replayed: tuple[ReducerGolden, Any, Any],
) -> None:
    golden, report, signal_report = _replayed
    replayed: dict[Literal["vote", "signal_vote"], dict[str, Any]] = {
        "vote": report.trace_dict(),
        "signal_vote": signal_report.trace_dict(),
    }

    for name, trace in replayed.items():
        assert trace_drift(golden.live_traces[name], trace) == (), name
