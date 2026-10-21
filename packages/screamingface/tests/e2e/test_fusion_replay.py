"""The GSM8K Fusion regression lane, from recorded responses (OME-1289 E4a, FR#13).

The claim: the rewritten ``sf.Fusion`` (a Fan-out, a context Reduce, then a Model) sends the same
requests and gives the same answers as the recording. Two Fusion shapes are replayed
(``model_synthesizer`` and ``recipe_synthesizer``, see ``harness.fusion_golden``), each as the named
``sf.Fusion`` and as its block form ``sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce(
"context")), S])`` (FR-2). Every run goes through the real engine and the real gateway whose only
answers come from the lane's cache snapshot, with a capture proxy between them so that every
``/chat/completions`` request body is pinned too. Free and keyless.

Each run is held to the golden of its shape: the five locks of ``test_boards`` (expression sha,
case statuses, failure codes, coverage, score), the Case outputs, and the sorted canonical JSON
digests of every request body. A block form must also render the url4 of its named form.

SKIP DISCIPLINE (like ``test_boards``): a lane with no fixtures SKIPS LOUDLY, naming exactly what is
missing. It never fake-passes. Three prerequisites:

- ``fixtures/snapshots/inspect-gsm8k-fusion.snapshot.gz`` (and its manifest): the sliced cache,
- ``fixtures/goldens/inspect-gsm8k-fusion.fusion-golden.json``: the blessed expected outcome,
- prepared assets of the imported board at ``<assets>/inspect-gsm8k``.

The first two come from a PAID recording that only the user can run (``fixtures/fusion_lane.py``:
``record``, then ``bless``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from harness._gating import GOLDENS_DIR, SNAPSHOTS_DIR, require_e2e_stack
from harness.benchmark_assets import ASSETS_ENV, assets_root
from harness.cache_seeded import CacheSeededGateway
from harness.fusion_golden import (
    RECIPES,
    FusionGolden,
    FusionRecipe,
    assert_fusion_replay,
    body_digests,
    load_fusion_golden,
)
from harness.goldens import ActualOutcome, compare_outcome, failure_map
from harness.inspect_stack import inspect_capture_stack

pytestmark = pytest.mark.e2e

LANE = "inspect-gsm8k-fusion"
BOARD = "inspect-gsm8k"
# group F (7f): the "block" form is the context block of FusionLaneSpec.build_block (D7-8)
FORMS: tuple[Literal["named", "block"], ...] = ("named", "block")


@dataclass(frozen=True, slots=True)
class _Run:
    """One replay: its report and the digests of the request bodies it sent."""

    report: Any
    digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Lane:
    golden: FusionGolden
    runs: dict[tuple[str, str], _Run]


def _require_lane_fixtures() -> tuple[Path, Path | None, FusionGolden]:
    """The lane's snapshot + optional manifest + golden, or a LOUD skip naming the gap."""
    snapshot = SNAPSHOTS_DIR / f"{LANE}.snapshot.gz"
    golden_path = GOLDENS_DIR / f"{LANE}.fusion-golden.json"
    missing = [str(path) for path in (snapshot, golden_path) if not path.exists()]
    if missing:
        pytest.skip(
            f"lane '{LANE}' has no recorded fixtures yet: missing {', '.join(missing)}. "
            f"They come from a paid OpenRouter recording the user runs "
            f"(tests/e2e/fixtures/fusion_lane.py: `record`, then `bless`); "
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
    return snapshot, (manifest if manifest.exists() else None), load_fusion_golden(golden_path)


@pytest.fixture(scope="module")
def _lane(tmp_path_factory: pytest.TempPathFactory) -> _Lane:
    """One capture stack; every shape in both forms, each with its own request bodies."""
    # Fixture presence is checked FIRST so "no fixtures yet" is visible even on a machine that
    # could not run the stack anyway; then the stack gate.
    snapshot, manifest, golden = _require_lane_fixtures()
    require_e2e_stack()

    import screamingface as sf

    work_dir = tmp_path_factory.mktemp("fusion-replay")
    backend = CacheSeededGateway(snapshot=snapshot, manifest=manifest, work_dir=work_dir)
    runs: dict[tuple[str, str], _Run] = {}
    with inspect_capture_stack(backend, work_dir=work_dir, assets_dir=assets_root()) as (
        stack,
        proxy,
    ):
        with sf.Client(engine_url=stack.engine_url) as client:
            for recipe in RECIPES:
                for form in FORMS:
                    candidate = (
                        golden.candidate.build(recipe)
                        if form == "named"
                        else golden.candidate.build_block(recipe)
                    )
                    start = len(proxy.records)
                    report = client.evaluate(
                        candidate, benchmark=BOARD, limit=golden.limit, progress=False
                    )
                    runs[(recipe, form)] = _Run(report, body_digests(proxy.records[start:]))
    return _Lane(golden, runs)


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("recipe", RECIPES)
def test_fusion_regression_replay_is_byte_identical(
    _lane: _Lane, recipe: FusionRecipe, form: Literal["named", "block"]
) -> None:
    golden, run = _lane.golden, _lane.runs[(recipe, form)]

    assert run.report.benchmark.id == BOARD
    assert run.report.benchmark.revision == golden.revision, (
        f"benchmark revision drifted (golden {golden.revision}, engine "
        f"{run.report.benchmark.revision}): the recorded fixtures describe an older board"
    )
    candidate = run.report.candidates.only
    # The five locks: expression sha, statuses, failure codes, coverage, score (in that order).
    compare_outcome(
        golden.outcome(recipe),
        ActualOutcome(
            rendered_url4=str(candidate.url4),
            final_score=candidate.score,
            case_statuses={str(case.case_id): str(case.status) for case in candidate.cases},
            coverage=candidate.coverage,
            case_failures=failure_map(candidate.cases),
        ),
    )
    # The lane's own locks: every Case output, and the canonical JSON digest of every request body.
    assert_fusion_replay(golden.recipes[recipe], candidate.cases, run.digests)
    # FR-2: the block form is the named form, down to the url4.
    named = _lane.runs[(recipe, "named")].report.candidates.only
    assert str(candidate.url4) == str(named.url4)
