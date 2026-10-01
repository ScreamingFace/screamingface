"""Record and bless the fixtures of the GSM8K vote replay lane (OME-1289 E4a, EV-12).

The lane: ``sf.Fusion(sf.samples(<model>, 5, temperature=0.7), synthesizer=sf.Vote(...))`` on the
imported board ``inspect-gsm8k``, replayed from a recorded cache (``test_reducer_replay.py``).
Three fixture files make the lane go green, and until they exist the lane SKIPS loudly:

    fixtures/snapshots/inspect-gsm8k-vote.snapshot.gz        the sliced response cache
    fixtures/snapshots/inspect-gsm8k-vote.manifest.json      its revision-guard sidecar
    fixtures/goldens/inspect-gsm8k-vote.reducer-golden.json  the blessed expected outcome

Two steps make them. The first one SPENDS MONEY and is run by the user, never by an agent.

``record`` (PAID, needs the user)
    One live run of the candidate against a real OpenRouter key: Postgres (testcontainer), the
    REAL gateway (``aigateway.main:app``, request cache ON), an Engine synced with the
    ``benchmarks`` extra, then ``client.connect("openrouter", ...)``, the same path a notebook user
    takes. It refuses before any spend unless the model's ``seed`` parameter is published, enabled
    and not ``unsupported`` by the provider (a vote over unseeded samples counts one cached answer N
    times). It writes ``<out>/report.json`` (the SDK report), ``<out>/candidate.json`` (the
    ``ReducerCandidateSpec``), ``<out>/recording.json`` (the requested ``limit``) and
    ``<out>/cache.sql.gz`` (every cache row the run wrote). The key is
    read from the environment, handed to the gateway through the connect route, and never written to
    disk. Needs ``OPENROUTER_API_KEY``, ``SCREAMINGFACE_RECORD_PAID=1`` and a docker daemon. Cost:
    about ``limit * samples`` short calls (20 * 5 = 100), well under $0.10, 5 to 15 minutes.

``bless`` (free, docker, keyless)
    Replays the recording with NO key: the sliced cache goes into a keyless gateway and the same
    candidate runs on the Engine. It refuses unless the replay reproduces the saved report (same
    board, url4 expression, case statuses, score, coverage, failure codes and combine evidence) and
    the evidence lock holds, then writes the
    three fixture files above. Run ``git add`` on them and commit them in a follow-up commit.

The commands, from ``packages/screamingface`` (the asset preparation downloads GSM8K from Hugging
Face, no token needed)::

    (cd ../../apps/screamingface-engine && uv sync --extra benchmarks && \\
      uv run python -m screamingface_engine.benchmarks.prepare \\
        --root ~/.screamingface/benchmark-assets --bundle inspect-gsm8k)
    export OPENROUTER_API_KEY=...  SCREAMINGFACE_RECORD_PAID=1
    uv run python tests/e2e/fixtures/reducer_lane.py record \\
        --model openrouter/<seed-capable-model> --samples 5 --temperature 0.7 --limit 20 \\
        --out ~/sf-recordings/gsm8k-vote
    uv run python tests/e2e/fixtures/reducer_lane.py bless --recording ~/sf-recordings/gsm8k-vote
    SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_E2E_ASSETS=~/.screamingface/benchmark-assets \\
        uv run pytest tests/e2e/test_reducer_replay.py -rs -v

The same two steps are the ``e2e-record-reducer-lane`` and ``e2e-bless-reducer-lane`` just recipes.

Every helper that already exists is imported from ``slice_snapshot`` (the board blesser); that file
is not edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent
_E2E_DIR = _FIXTURES_DIR.parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

# WHY the package path: the same module object the contract tests import.
from fixtures import slice_snapshot as ss  # noqa: E402
from harness._local_proc import (  # noqa: E402
    ManagedProcess,
    clean_env,
    free_port,
    repo_root,
    venv_bin,
)
from harness.cache_seeded import CacheSeededGateway  # noqa: E402
from harness.goldens import (  # noqa: E402
    GoldenFailure,
    canonical_score,
    expression_sha,
    failure_map,
)
from harness.inspect_stack import InspectEngineProcess  # noqa: E402
from harness.reducer_golden import (  # noqa: E402
    EvidenceLock,
    ReducerCandidateSpec,
    ReducerGolden,
    assert_evidence_lock,
)

BOARD = "inspect-gsm8k"
LANE = "inspect-gsm8k-vote"
_OPERATION_ID = "op_synthesis_1"

_RECORD_PAID_ENV = "SCREAMINGFACE_RECORD_PAID"
_KEY_ENV = "OPENROUTER_API_KEY"
#: Fixed manifest date: committed fixtures carry no wall-clock traces.
_BLESSED_AT = "2026-10-01"
_RECORDING_FILES = ("report.json", "candidate.json", "recording.json", "cache.sql.gz")

#: Every cache row the recording run wrote, normalized like the board slice (fixed timestamps, no
#: expiry, counters zeroed). It is ``slice_snapshot._SLICE_SQL`` without the baseline join, because
#: a recording starts from an empty cache and every row in it is the run's.
_RECORD_SQL = f"""COPY (
  SELECT r.id, r.key_hash, r.prompt_hash, r.provider, r.model, r.response_json,
         r.response_size_bytes,
         '{ss._ROW_TIMESTAMP}'::timestamptz, '{ss._ROW_TIMESTAMP}'::timestamptz,
         NULL::timestamptz, NULL::timestamptz, 0
  FROM public.request_cache_entries r
  ORDER BY r.key_hash
) TO STDOUT"""


# -- shared plumbing ------------------------------------------------------------------


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("docker CLI not on PATH (the Postgres testcontainer needs it)")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("docker daemon unreachable (the Postgres testcontainer needs it)")


def _require_assets() -> Path:
    """The assets root holding the prepared ``inspect-gsm8k`` bundle, or a refusal saying how."""
    configured = os.environ.get(ss._ASSETS_ENV)
    root = Path(configured) if configured else ss._default_assets_root()
    if not (root / BOARD).is_dir():
        raise SystemExit(
            f"prepared assets missing at {root / BOARD}: run, in apps/screamingface-engine, "
            f"`uv sync --extra benchmarks && uv run python -m "
            f"screamingface_engine.benchmarks.prepare --root {root} --bundle {BOARD}`"
        )
    return root


def _snapshot_text(header: list[str], rows: list[str]) -> str:
    return "\n".join(
        [
            *header,
            f"COPY public.request_cache_entries ({ss._COPY_COLUMNS}) FROM stdin;",
            *rows,
            "\\.",
            "",
        ]
    )


def _rows(copy_output: str) -> list[str]:
    return [line for line in copy_output.split("\n") if line and not line.isspace()]


# -- record (PAID) --------------------------------------------------------------------


def _require_paid_gate() -> None:
    """Spend is opt-in twice: the flag AND a key. Neither is ever read from a file."""
    if os.environ.get(_RECORD_PAID_ENV) != "1":
        raise SystemExit(f"{_RECORD_PAID_ENV}=1 not set: `record` spends real money and is opt-in")
    if not os.environ.get(_KEY_ENV):
        raise SystemExit(f"{_KEY_ENV} not set: `record` needs a real OpenRouter key")
    _require_docker()


def _start_live_gateway(database_url: str, work_dir: Path) -> tuple[ManagedProcess, str]:
    """The REAL gateway app with the request cache ON, as ``tests/paid/conftest.py`` boots it.

    The key is NOT in this environment: it enters through the product's connect route, encrypted at
    rest in the throwaway Postgres.
    """
    gateway_dir = repo_root() / "apps" / "aigateway"
    port = free_port()
    env = clean_env(
        {
            "AIGATEWAY_DATABASE_URL": database_url,
            # Loopback-only anonymous mode: the engine calls with no credential.
            "AIGW_AUTH_MODE": "disabled",
            "AIGATEWAY_ADMIN_EMAILS": "reducer-lane-record@localhost",
            "AIGW_OPENROUTER_ENABLED": "true",
            # Live datasheets and execution_access, the posture the model parameter preflight reads.
            "AIGW_DISCOVERY_ENABLED": "true",
            # The recording IS the cache: every answer is written under its replay key.
            "AIGW_REQUEST_CACHE_ENABLED": "true",
            "AIGW_REQUEST_CACHE_TTL_SECONDS": "3600",
        }
    )
    process = ManagedProcess(
        name="aigateway",
        command=[
            str(venv_bin(gateway_dir, "uvicorn")),
            "aigateway.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        env=env,
        cwd=gateway_dir,
        log_path=work_dir / "aigateway.log",
    )
    base_url = f"http://127.0.0.1:{port}"
    process.start(f"{base_url}/healthz")
    return process, base_url


def _require_seed_support(client: Any, model: str) -> None:
    """Refuse BEFORE any spend unless the provider takes a seed (a vote needs N real answers)."""
    seed = client.models.get(model).parameters.get("seed")
    if seed is None or not seed.enabled or seed.provider_support == "unsupported":
        raise SystemExit(
            f"RECORD REFUSED: model {model!r} has no usable `seed` parameter "
            f"(published={seed is not None}, enabled={getattr(seed, 'enabled', None)}, "
            f"provider_support={getattr(seed, 'provider_support', None)}). "
            f"Pick a seed-capable model."
        )
    print(f"[seed] {model}: enabled, provider_support={seed.provider_support}", flush=True)


def _record_run(engine_url: str, spec: ReducerCandidateSpec, limit: int) -> Any:
    import screamingface as sf

    with sf.Client(engine_url=engine_url) as client:
        client.connect("openrouter", api_key=os.environ[_KEY_ENV])
        _require_seed_support(client, spec.model)
        print(f"[record] {spec.samples} samples x {limit} cases of {BOARD}, LIVE", flush=True)
        return client.evaluate(spec.build(), benchmark=BOARD, limit=limit, progress=False)


def _record_stack(
    spec: ReducerCandidateSpec, limit: int, assets_root: Path, work_dir: Path
) -> tuple[Any, list[str]]:
    """Postgres, live gateway, inspect engine; one live run; the cache rows it wrote."""
    backend = CacheSeededGateway(snapshot=Path("unused"), manifest=None, work_dir=work_dir)
    gateway: ManagedProcess | None = None
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_root)
    try:
        database_url = backend._start_postgres()
        backend._migrate(database_url)
        gateway, gateway_url = _start_live_gateway(database_url, work_dir)
        report = _record_run(engine.start(gateway_url), spec, limit)
        rows = _rows(ss._psql(backend._container, _RECORD_SQL))
    finally:
        engine.stop()
        if gateway is not None:
            gateway.stop()
        backend.stop_sync()
    return report, rows


def record(args: argparse.Namespace) -> None:
    _require_paid_gate()
    assets_root = _require_assets()
    spec = ReducerCandidateSpec(
        model=args.model,
        samples=args.samples,
        temperature=args.temperature,
        extract=args.extract,
        normalize=args.normalize,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    work_dir = args.work_dir or args.out / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    report, rows = _record_stack(spec, args.limit, assets_root, work_dir)
    report.export(args.out / "report.json")
    (args.out / "candidate.json").write_text(spec.model_dump_json(indent=2) + "\n")
    # The requested limit: `bless` replays the same selection and cross-checks it with the report.
    (args.out / "recording.json").write_text(json.dumps({"limit": args.limit}) + "\n")
    header = [
        "--",
        f"-- Raw cache rows recorded for lane '{LANE}' (reducer_lane.py record).",
        "--",
        "",
    ]
    (args.out / "cache.sql.gz").write_bytes(ss.snapshot_gzip(_snapshot_text(header, rows)))
    outcome = report.candidates.only
    print(
        f"[done] score={outcome.score} coverage={outcome.coverage} cache rows={len(rows)}; "
        f"recording in {args.out}. Next: reducer_lane.py bless --recording {args.out}",
        flush=True,
    )


# -- bless (free, keyless) ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Recording:
    """What `record` left behind, as `bless` reads it: the saved report's facts and its extras."""

    facts: Any  # slice_snapshot.FreshReportFacts: url4, score, coverage, statuses
    spec: ReducerCandidateSpec
    cache: Path
    limit: int
    failures: dict[str, tuple[GoldenFailure, ...]]
    combines: dict[str, dict[str, Any]]


def _recorded_failures(cases: list[dict[str, Any]]) -> dict[str, tuple[GoldenFailure, ...]]:
    """The saved report's failure map, spelled like ``failure_map`` spells the replay's."""
    return {
        str(case["case_id"]): tuple(
            GoldenFailure(stage=failure["stage"], code=failure["code"])
            for failure in case["failures"]
        )
        for case in cases
        if case["failures"]
    }


def _recorded_combines(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """case id -> the saved report's ``op_synthesis_1`` combine evidence (absent when none)."""
    return {
        str(case["case_id"]): operation["combine"]
        for case in cases
        for operation in case.get("operations") or ()
        if operation["operation_id"] == _OPERATION_ID and operation.get("combine") is not None
    }


def _read_recording(recording: Path) -> _Recording:
    missing = [name for name in _RECORDING_FILES if not (recording / name).is_file()]
    if missing:
        raise SystemExit(
            f"the recording {recording} lacks {', '.join(missing)}: run `record` first"
        )
    raw = json.loads((recording / "report.json").read_text("utf-8"))
    facts = ss.parse_fresh_report(raw)
    if facts.board != BOARD:
        raise SystemExit(f"the report describes board {facts.board!r}, not {BOARD!r}")
    if facts.kind != "fusion":
        raise SystemExit(f"the report records a {facts.kind!r} run; this lane blesses a fusion")
    limit = json.loads((recording / "recording.json").read_text("utf-8"))["limit"]
    if limit != len(facts.case_statuses):
        raise SystemExit(
            f"the recording asked for limit {limit} but the report holds "
            f"{len(facts.case_statuses)} cases; it does not describe one run"
        )
    cases = raw["candidates"][0]["cases"]
    return _Recording(
        facts=facts,
        spec=ReducerCandidateSpec.model_validate_json(
            (recording / "candidate.json").read_text("utf-8")
        ),
        cache=recording / "cache.sql.gz",
        limit=limit,
        failures=_recorded_failures(cases),
        combines=_recorded_combines(cases),
    )


def _refuse(mismatch: bool, message: str) -> None:
    if mismatch:
        raise SystemExit(f"BLESS REFUSED: {message}")


def _replayed_combines(cases: Any) -> dict[str, dict[str, Any]]:
    return {
        str(case.case_id): json.loads(json.dumps(operation.combine.to_dict()))
        for case in cases
        for operation in case.operations or ()
        if operation.operation_id == _OPERATION_ID and operation.combine is not None
    }


def _refuse_unless_reproduced(report: Any, recording: _Recording) -> dict[str, str]:
    """The replay must reproduce the saved report, or the recording does not describe this lane.

    The order is the order of ``compare_outcome``, then the evidence: board, expression, statuses,
    score, coverage, failure codes, combine evidence.
    """
    outcome, facts = report.candidates.only, recording.facts
    _refuse(report.benchmark.id != BOARD, f"the engine ran {report.benchmark.id!r}, not {BOARD!r}")
    _refuse(
        str(outcome.url4) != facts.rendered_url4,
        "the replay rendered a different url4 expression than the saved report recorded; "
        "candidate.json does not rebuild the recorded run",
    )
    statuses = {str(case.case_id): str(case.status) for case in outcome.cases}
    ss._refuse_status_drift(facts.case_statuses, statuses)
    _refuse(
        canonical_score(outcome.score) != canonical_score(facts.expected_score),
        f"replay score {canonical_score(outcome.score)!r} contradicts the saved report's "
        f"{canonical_score(facts.expected_score)!r}; the recording does not reproduce",
    )
    _refuse(
        round(outcome.coverage, 4) != round(facts.expected_coverage, 4),
        f"replay coverage {round(outcome.coverage, 4)} contradicts the saved report's "
        f"{round(facts.expected_coverage, 4)}",
    )
    _refuse(
        failure_map(outcome.cases) != recording.failures,
        "the replay's failure codes differ from the saved report's",
    )
    _refuse(
        _replayed_combines(outcome.cases) != recording.combines,
        "the replay's combine evidence differs from the saved report's",
    )
    return statuses


def _replay_and_slice(
    recording: _Recording, assets_root: Path, work_dir: Path
) -> tuple[Any, dict[str, str], list[str]]:
    """Boot a KEYLESS gateway, seed the recording, replay, verify, and slice what the replay hit."""
    cache = recording.cache
    backend, gateway_url = ss._boot_gateway(argparse.Namespace(dump=cache, work_dir=work_dir))
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_root)
    try:
        job = ss._upload_snapshot(gateway_url, cache.name, cache.read_bytes())
        print(f"[seed] recording loaded: rows={job.get('live_after')}", flush=True)
        engine_url = engine.start(gateway_url)
        # Baseline BEFORE the verified replay, so the slice can observe movement.
        ss._psql(backend._container, ss._BASELINE_SQL)
        report = ss._evaluate(engine_url, recording.spec.build(), BOARD, recording.limit)
        statuses = _refuse_unless_reproduced(report, recording)
        rows = _rows(ss._psql(backend._container, ss._SLICE_SQL))
    finally:
        engine.stop()
        backend.stop_sync()
    return report, statuses, rows


def _evidence(cases: Any) -> EvidenceLock:
    """The first case (report order) whose ``op_synthesis_1`` carries combine evidence."""
    for case in cases:
        for operation in case.operations or ():
            if operation.operation_id == _OPERATION_ID and operation.combine is not None:
                return EvidenceLock(
                    case_id=str(case.case_id),
                    operation_id=_OPERATION_ID,
                    combine=json.loads(json.dumps(operation.combine.to_dict())),
                )
    raise SystemExit(f"BLESS REFUSED: no case carries combine evidence on {_OPERATION_ID}")


def _author_golden(
    report: Any, spec: ReducerCandidateSpec, statuses: dict[str, str], limit: int
) -> ReducerGolden:
    outcome = report.candidates.only
    golden = ReducerGolden.model_validate(
        {
            "lane": LANE,
            "board": BOARD,
            "revision": report.benchmark.revision,
            "limit": limit,
            "candidate": spec,
            "expression_sha": expression_sha(str(outcome.url4)),
            "final_score": canonical_score(outcome.score),
            "case_count": len(statuses),
            "gradeable_count": sum(1 for status in statuses.values() if status == "scored"),
            "case_statuses": statuses,
            "case_failures": failure_map(outcome.cases),
            "evidence": _evidence(outcome.cases),
        }
    )
    # The golden must pass its own lock on the very run it was authored from.
    assert_evidence_lock(golden, outcome.cases)
    return golden


def _write_fixtures(
    golden: ReducerGolden,
    rows: list[str],
    header: list[str],
    max_snapshot_mb: float,
    work_dir: Path,
) -> None:
    snapshot = ss.snapshot_gzip(_snapshot_text(header, rows))
    manifest = {
        "schema": ss._MANIFEST_SCHEMA,
        "generated_at": _BLESSED_AT,
        "row_count": len(rows),
        "sha256": hashlib.sha256(snapshot).hexdigest(),
        "revisions": json.loads(ss._run_helper("revisions")),
    }
    size_mb = len(snapshot) / (1024 * 1024)
    oversized = size_mb > max_snapshot_mb
    out_dir = work_dir if oversized else _FIXTURES_DIR
    (out_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    (out_dir / "goldens").mkdir(parents=True, exist_ok=True)
    (out_dir / "snapshots" / f"{LANE}.snapshot.gz").write_bytes(snapshot)
    (out_dir / "snapshots" / f"{LANE}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "goldens" / f"{LANE}.reducer-golden.json").write_text(
        json.dumps(golden.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    )
    print(f"[write] {LANE}: snapshot {size_mb:.2f} MB ({len(rows)} rows) -> {out_dir}", flush=True)
    if oversized:
        raise SystemExit(
            f"BLESS NOT COMMITTED: the slice is {size_mb:.2f} MB (> {max_snapshot_mb} MB); output "
            f"left in {out_dir}. Record with a smaller --limit or --samples."
        )


def bless(args: argparse.Namespace) -> None:
    _require_docker()
    recording = _read_recording(args.recording)
    assets_root = _require_assets()
    work_dir = args.work_dir or args.recording / "bless-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    report, statuses, rows = _replay_and_slice(recording, assets_root, work_dir)
    golden = _author_golden(report, recording.spec, statuses, recording.limit)
    report_sha = hashlib.sha256((args.recording / "report.json").read_bytes()).hexdigest()
    # Provenance rule: sources are described generically plus content shas, never local paths.
    header = [
        "--",
        f"-- Sliced replay fixture for lane '{LANE}' (OME-1289 E4a; see reducer_lane.py).",
        "-- Every row VERBATIM from a recording made through this checkout's gateway",
        f"-- (cache content sha256 {ss._dump_content_sha(recording.cache)}), so the keys are",
        "-- already this protocol's. The bless proved the replay reproduces the saved SDK report",
        f"-- (content sha256 {report_sha}): expression, statuses, score, coverage, failures and",
        "-- combine evidence.",
        "--",
        "",
    ]
    _write_fixtures(golden, rows, header, args.max_snapshot_mb, work_dir)


# -- command line ---------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record and bless the GSM8K vote replay lane.")
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record", help="PAID, needs the user: one live run, one recording")
    rec.add_argument(
        "--model", required=True, help="seed-capable route, e.g. openrouter/<vendor>/<m>"
    )
    rec.add_argument("--samples", type=int, default=5, help="members of the Fusion (default 5)")
    rec.add_argument("--temperature", type=float, default=0.7, help="sampling temperature")
    rec.add_argument("--limit", type=int, default=20, help="GSM8K cases to run (default 20)")
    rec.add_argument("--extract", default="last_number", help="Vote extract operator name")
    rec.add_argument("--normalize", default="numeric", help="Vote normalize operator name")
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
