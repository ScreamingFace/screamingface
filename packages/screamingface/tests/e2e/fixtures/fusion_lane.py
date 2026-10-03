"""Record and bless the fixtures of the GSM8K Fusion regression lane (OME-1289 E4a, FR#13).

The lane: two ``sf.Fusion`` shapes over the same three seeded samples of one model, run on the
imported board ``inspect-gsm8k`` and replayed from a recorded cache (``test_fusion_replay.py``):

    model_synthesizer     sf.Fusion(members, synthesizer=sf.Model(m))
    recipe_synthesizer    sf.Fusion(members, synthesizer=<a named two-stage Pipeline>)

The replay must repeat the recording BYTE FOR BYTE: the same url4, the same Case outputs, and the
same request body for every call the Engine sends to the gateway. It also runs the BLOCK form of
each shape (``sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce("context")), S])``) against the
same cache and demands the same url4, outputs and bodies (FR-2). Two fixture files make the lane
go green, and until they exist the lane SKIPS loudly:

    fixtures/snapshots/inspect-gsm8k-fusion.snapshot.gz         the sliced response cache
    fixtures/snapshots/inspect-gsm8k-fusion.manifest.json       its revision-guard sidecar
    fixtures/goldens/inspect-gsm8k-fusion.fusion-golden.json    the blessed expected outcome

(The golden is not named ``*.golden.json``, so ``test_boards`` does not collect it.) Two steps make
them, in the pattern of ``reducer_lane.py``, whose plumbing this file imports. The first one SPENDS
MONEY and is run by the user, never by an agent.

``record`` (PAID, needs the user)
    One live run of each shape against a real OpenRouter key, with the REAL gateway (request cache
    ON) behind a Postgres testcontainer. It refuses before any spend unless the model takes a
    ``seed``. It writes ``report-<recipe>.json`` for each shape, ``candidate.json`` (the
    ``FusionLaneSpec``), ``recording.json`` (the requested ``limit``) and ``cache.sql.gz`` (every
    cache row, 13 columns: see ``reducer_lane._COPY_COLUMNS``). Both shapes send the same member
    requests and the same first synthesis request, so the second shape is mostly served from the
    live cache. Cost: at most 35 short calls (5 cases x (3 members + 1 synthesis + 1 check) = 25
    for the first run), well under $0.10. No request body is captured here: the paid step gains no
    proxy that no test has seen.

``bless`` (free, docker, keyless)
    Replays the recording with NO key, with a capture proxy between the Engine and the gateway. For
    each shape it runs the named form and refuses unless the replay reproduces the saved report
    (board, url4, statuses, score, coverage, failure codes, Case outputs), then runs the block form
    and refuses unless it gives the same url4, outputs and request bodies (FR-2). WHY capture only
    on replay: the replay gateway is keyless, so a body whose cache key drifted is a miss and fails
    the Case. The golden pins the digest of every body anyway, a superset of the synthesizer bodies.

The commands, from ``packages/screamingface`` (the preparation of the assets is in
``reducer_lane.py``)::

    export OPENROUTER_API_KEY=...  SCREAMINGFACE_RECORD_PAID=1
    uv run python tests/e2e/fixtures/fusion_lane.py record \\
        --model openrouter/<seed-capable-model> --samples 3 --temperature 0.7 --limit 5 \\
        --out ~/sf-recordings/gsm8k-fusion
    uv run python tests/e2e/fixtures/fusion_lane.py bless --recording ~/sf-recordings/gsm8k-fusion
    SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_E2E_ASSETS=~/.screamingface/benchmark-assets \\
        uv run pytest tests/e2e/test_fusion_replay.py -rs -v

The same two steps are the ``e2e-record-fusion-lane`` and ``e2e-bless-fusion-lane`` just recipes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent
_E2E_DIR = _FIXTURES_DIR.parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

# WHY the package path: the same module objects the contract tests import.
from fixtures import reducer_lane as rl  # noqa: E402
from fixtures import slice_snapshot as ss  # noqa: E402
from harness._local_proc import ManagedProcess  # noqa: E402
from harness.cache_seeded import CacheSeededGateway  # noqa: E402
from harness.fusion_golden import (  # noqa: E402
    RECIPES,
    FusionGolden,
    FusionLaneSpec,
    FusionRecipe,
    FusionRecipeLock,
    assert_fusion_replay,
    body_digests,
    case_outputs,
)
from harness.goldens import (  # noqa: E402
    GoldenFailure,
    canonical_score,
    expression_sha,
    failure_map,
)
from harness.inspect_stack import InspectEngineProcess  # noqa: E402

BOARD = "inspect-gsm8k"
LANE = "inspect-gsm8k-fusion"
_RECORDING_FILES = (
    "report-model_synthesizer.json",
    "report-recipe_synthesizer.json",
    "candidate.json",
    "recording.json",
    "cache.sql.gz",
)


# -- record (PAID) --------------------------------------------------------------------


def _record_runs(engine_url: str, spec: FusionLaneSpec, limit: int) -> dict[FusionRecipe, Any]:
    """One live run of each shape, the named form, with no proxy (F7)."""
    import screamingface as sf

    with sf.Client(engine_url=engine_url) as client:
        client.connect("openrouter", api_key=os.environ[rl._KEY_ENV])
        rl._require_seed_support(client, spec.model)
        print(f"[record] {spec.samples} samples x {limit} cases of {BOARD}, LIVE", flush=True)
        return {
            recipe: client.evaluate(
                spec.build(recipe), benchmark=BOARD, limit=limit, progress=False
            )
            for recipe in RECIPES
        }


def _record_stack(
    spec: FusionLaneSpec, limit: int, assets_root: Path, work_dir: Path
) -> tuple[dict[FusionRecipe, Any], list[str]]:
    """Postgres, live gateway, inspect engine; the live runs; the cache rows they wrote."""
    backend = CacheSeededGateway(snapshot=Path("unused"), manifest=None, work_dir=work_dir)
    gateway: ManagedProcess | None = None
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_root)
    try:
        database_url = backend._start_postgres()
        backend._migrate(database_url)
        gateway, gateway_url = rl._start_live_gateway(database_url, work_dir)
        reports = _record_runs(engine.start(gateway_url), spec, limit)
        rows = rl._rows(ss._psql(backend._container, rl._RECORD_SQL))
    finally:
        engine.stop()
        if gateway is not None:
            gateway.stop()
        backend.stop_sync()
    return reports, rows


def _write_recording(
    out: Path, spec: FusionLaneSpec, limit: int, reports: dict[FusionRecipe, Any], rows: list[str]
) -> None:
    """The five recording files (``_RECORDING_FILES``)."""
    for recipe, report in reports.items():
        report.export(out / f"report-{recipe}.json")
    (out / "candidate.json").write_text(spec.model_dump_json(indent=2) + "\n")
    (out / "recording.json").write_text(json.dumps({"limit": limit}) + "\n")
    header = [
        "--",
        f"-- Raw cache rows recorded for lane '{LANE}' (fusion_lane.py record).",
        "--",
        "",
    ]
    (out / "cache.sql.gz").write_bytes(ss.snapshot_gzip(rl._snapshot_text(header, rows)))


def record(args: argparse.Namespace) -> None:
    rl._require_paid_gate()
    assets_root = rl._require_assets()
    spec = FusionLaneSpec(model=args.model, samples=args.samples, temperature=args.temperature)
    args.out.mkdir(parents=True, exist_ok=True)
    work_dir = args.work_dir or args.out / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    reports, rows = _record_stack(spec, args.limit, assets_root, work_dir)
    _write_recording(args.out, spec, args.limit, reports, rows)
    scores = ", ".join(f"{recipe}={reports[recipe].candidates.only.score}" for recipe in RECIPES)
    print(
        f"[done] {scores} cache rows={len(rows)}; recording in {args.out}. "
        f"Next: fusion_lane.py bless --recording {args.out}",
        flush=True,
    )


# -- bless (free, keyless) ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RecordedReport:
    """One saved report, as `bless` reads it: its facts, failures and Case outputs."""

    facts: Any  # slice_snapshot.FreshReportFacts
    failures: dict[str, tuple[GoldenFailure, ...]]
    outputs: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class _Recording:
    spec: FusionLaneSpec
    cache: Path
    limit: int
    reports: dict[FusionRecipe, _RecordedReport]


def _read_report(recording: Path, recipe: FusionRecipe, limit: int) -> _RecordedReport:
    name = f"report-{recipe}.json"
    raw = json.loads((recording / name).read_text("utf-8"))
    facts = ss.parse_fresh_report(raw)
    if facts.board != BOARD:
        raise SystemExit(f"{name} describes board {facts.board!r}, not {BOARD!r}")
    if facts.kind != "fusion":
        raise SystemExit(f"{name} records a {facts.kind!r} run; this lane blesses a fusion")
    if limit != len(facts.case_statuses):
        raise SystemExit(
            f"the recording asked for limit {limit} but the report holds "
            f"{len(facts.case_statuses)} cases ({name}); it does not describe one run"
        )
    cases = raw["candidates"][0]["cases"]
    return _RecordedReport(
        facts=facts,
        failures=rl._recorded_failures(cases),
        outputs={str(case["case_id"]): case["output"] for case in cases},
    )


def _read_recording(recording: Path) -> _Recording:
    missing = [name for name in _RECORDING_FILES if not (recording / name).is_file()]
    if missing:
        raise SystemExit(
            f"the recording {recording} lacks {', '.join(missing)}: run `record` first"
        )
    limit = json.loads((recording / "recording.json").read_text("utf-8"))["limit"]
    return _Recording(
        spec=FusionLaneSpec.model_validate_json((recording / "candidate.json").read_text("utf-8")),
        cache=recording / "cache.sql.gz",
        limit=limit,
        reports={recipe: _read_report(recording, recipe, limit) for recipe in RECIPES},
    )


def _first_output_drift(
    recorded: dict[str, str | None], replayed: dict[str, str | None]
) -> str | None:
    """The first Case (saved order, then the replay's extras) whose output is not the saved one."""
    for case_id in (*recorded, *(key for key in replayed if key not in recorded)):
        if (
            case_id not in recorded
            or case_id not in replayed
            or recorded[case_id] != replayed[case_id]
        ):
            return case_id
    return None


def _refuse_unless_reproduced(
    report: Any,
    facts: Any,
    recorded_outputs: dict[str, str | None],
    recorded_failures: dict[str, tuple[GoldenFailure, ...]],
) -> dict[str, str]:
    """The named-form replay must reproduce the saved report, or the recording is not this lane's.

    The order: the board's locks (board, url4, statuses, score, coverage, failure codes), then the
    Case outputs. A Fusion's outputs are the lane's own claim: a vote hides a changed answer behind
    an unchanged status, and a Fusion does not.
    """
    statuses = rl._refuse_unless_board_reproduced(report, facts, recorded_failures)
    replayed = case_outputs(report.candidates.only.cases)
    drifted = _first_output_drift(recorded_outputs, replayed)
    rl._refuse(
        drifted is not None,
        f"case {drifted!r} output differs from the saved report's (saved, replay): "
        f"{recorded_outputs.get(drifted or '')!r} != {replayed.get(drifted or '')!r}",
    )
    return statuses


def _refuse_unless_block_matches(
    named: Any, block: Any, named_digests: tuple[str, ...], block_digests: tuple[str, ...]
) -> None:
    """FR-2 at the request level: the block form is the named Fusion, byte for byte."""
    left, right = named.candidates.only, block.candidates.only
    rl._refuse(
        str(left.url4) != str(right.url4),
        "the block form compiled a different url4 than sf.Fusion (FR-2)",
    )
    rl._refuse(
        case_outputs(left.cases) != case_outputs(right.cases),
        "the block form answered differently than sf.Fusion (FR-2)",
    )
    rl._refuse(
        named_digests != block_digests,
        "the block form sent other request bodies than sf.Fusion (FR-2)",
    )


@dataclass(frozen=True, slots=True)
class _Replay:
    """One shape's named-form replay: its report and the digests of the bodies it sent."""

    report: Any
    digests: tuple[str, ...]


def _replay_recipe(
    engine_url: str, proxy: Any, recording: _Recording, recipe: FusionRecipe
) -> _Replay:
    """The named form, then the block form, against the same cache; both must hold."""
    saved = recording.reports[recipe]
    start = len(proxy.records)
    report = ss._evaluate(engine_url, recording.spec.build(recipe), BOARD, recording.limit)
    digests = body_digests(proxy.records[start:])
    _refuse_unless_reproduced(report, saved.facts, saved.outputs, saved.failures)
    start = len(proxy.records)
    block = ss._evaluate(engine_url, recording.spec.build_block(recipe), BOARD, recording.limit)
    _refuse_unless_block_matches(report, block, digests, body_digests(proxy.records[start:]))
    return _Replay(report=report, digests=digests)


def _replay_and_slice(
    recording: _Recording, assets_root: Path, work_dir: Path
) -> tuple[dict[FusionRecipe, _Replay], list[str]]:
    """Boot a KEYLESS gateway, seed the recording, replay every shape, and slice what it hit."""
    cache = recording.cache
    backend, gateway_url = ss._boot_gateway(argparse.Namespace(dump=cache, work_dir=work_dir))
    proxy: Any = None
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_root)
    try:
        job = ss._upload_snapshot(gateway_url, cache.name, cache.read_bytes())
        print(f"[seed] recording loaded: rows={job.get('live_after')}", flush=True)
        proxy = ss._CaptureProxy(gateway_url)
        engine_url = engine.start(proxy.url)
        # Baseline BEFORE the verified replay, so the slice can observe movement.
        ss._psql(backend._container, ss._BASELINE_SQL)
        replays: dict[FusionRecipe, _Replay] = {
            recipe: _replay_recipe(engine_url, proxy, recording, recipe) for recipe in RECIPES
        }
        rows = rl._rows(ss._psql(backend._container, rl._SLICE_SQL))
    finally:
        engine.stop()
        if proxy is not None:
            proxy.shutdown()
        backend.stop_sync()
    return replays, rows


def _lock(replay: _Replay) -> FusionRecipeLock:
    outcome = replay.report.candidates.only
    statuses = {str(case.case_id): str(case.status) for case in outcome.cases}
    return FusionRecipeLock.model_validate(
        {
            "expression_sha": expression_sha(str(outcome.url4)),
            "final_score": canonical_score(outcome.score),
            "case_count": len(statuses),
            "gradeable_count": sum(1 for status in statuses.values() if status == "scored"),
            "case_statuses": statuses,
            "case_failures": failure_map(outcome.cases),
            "case_outputs": case_outputs(outcome.cases),
            "request_bodies": replay.digests,
        }
    )


def _author_golden(replays: dict[FusionRecipe, _Replay], recording: _Recording) -> FusionGolden:
    revision = replays[RECIPES[0]].report.benchmark.revision
    golden = FusionGolden.model_validate(
        {
            "lane": LANE,
            "board": BOARD,
            "revision": revision,
            "limit": recording.limit,
            "candidate": recording.spec,
            "recipes": {recipe: _lock(replays[recipe]) for recipe in RECIPES},
        }
    )
    # The golden must pass its own byte-for-byte check on the very runs it was authored from.
    for recipe in RECIPES:
        replay = replays[recipe]
        assert_fusion_replay(
            golden.recipes[recipe], replay.report.candidates.only.cases, replay.digests
        )
    return golden


def bless(args: argparse.Namespace) -> None:
    rl._require_docker()
    recording = _read_recording(args.recording)
    assets_root = rl._require_assets()
    work_dir = args.work_dir or args.recording / "bless-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    replays, rows = _replay_and_slice(recording, assets_root, work_dir)
    golden = _author_golden(replays, recording)
    # Provenance rule: sources are described generically plus content shas, never local paths.
    report_shas = ", ".join(
        hashlib.sha256((args.recording / f"report-{recipe}.json").read_bytes()).hexdigest()
        for recipe in RECIPES
    )
    header = [
        "--",
        f"-- Sliced replay fixture for lane '{LANE}' (OME-1289 E4a; see fusion_lane.py).",
        "-- Every row VERBATIM from a recording made through this checkout's gateway",
        f"-- (cache content sha256 {ss._dump_content_sha(recording.cache)}), so the keys are",
        "-- already this protocol's. The bless proved the replay reproduces the saved SDK reports",
        f"-- (content sha256 {report_shas}): expression, statuses, score, coverage, failures and",
        "-- Case outputs, and that the block form of each shape sends the same requests.",
        "--",
        "",
    ]
    rl._write_fixtures(
        golden, rows, header, args.max_snapshot_mb, work_dir, lane=LANE, golden_kind="fusion-golden"
    )


# -- command line ---------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record and bless the GSM8K Fusion regression lane."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record", help="PAID, needs the user: live runs, one recording")
    rec.add_argument(
        "--model", required=True, help="seed-capable route, e.g. openrouter/<vendor>/<m>"
    )
    rec.add_argument("--samples", type=int, default=3, help="members of the Fusion (default 3)")
    rec.add_argument("--temperature", type=float, default=0.7, help="sampling temperature")
    rec.add_argument("--limit", type=int, default=5, help="GSM8K cases to run (default 5)")
    rec.add_argument("--out", type=Path, required=True, help="directory for the recording")
    rec.add_argument("--work-dir", type=Path, help="service logs (default <out>/work)")
    rec.set_defaults(run=record)
    blessing = commands.add_parser("bless", help="free, keyless: recording -> committed fixtures")
    blessing.add_argument(
        "--recording", type=Path, required=True, help="the `record --out` directory"
    )
    blessing.add_argument(
        "--work-dir", type=Path, help="service logs (default <recording>/bless-work)"
    )
    blessing.add_argument("--max-snapshot-mb", type=float, default=5.0)
    blessing.set_defaults(run=bless)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
