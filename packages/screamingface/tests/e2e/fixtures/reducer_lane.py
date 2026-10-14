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
    times). It runs TWO candidates on the same Cases: first the cost-weighted vote
    (``Vote(..., weights=sf.signal("cost_usd"))``, SG#15), then the plain vote. Their member
    requests are byte-identical, so the first takes the live misses and the second is served from
    the live cache: the spend is the plain lane's. It writes seven files into ``<out>``:

        report.json, signals-report.json     the SDK reports of the plain and the signal vote
        trace.json, signals-trace.json       their live ``report-trace.v1`` documents (RT#16)
        candidate.json                       the ``ReducerCandidateSpec`` (the plain vote)
        recording.json                       the requested ``limit`` and the signal key
        cache.sql.gz                         every cache row the runs wrote

    The cache rows have 13 columns, the gateway's own layout (``CANONICAL_COLUMNS``): the board
    slices stop at 12, and this lane adds ``metadata_json``. WHY: on a hit the gateway reads the
    price and the latency of the original call from that column. Without it a replay would give
    ``cost_usd`` and ``latency_ms`` None, and the signal replay could not hold. ``record`` prints
    how many rows carry it. The key is read from the environment, handed to the gateway through the
    connect route, and never written to disk. Needs ``OPENROUTER_API_KEY``,
    ``SCREAMINGFACE_RECORD_PAID=1`` and a docker daemon. Cost: about ``limit * samples`` short
    calls (20 * 5 = 100), well under $0.10, 5 to 15 minutes.

``bless`` (free, docker, keyless)
    Replays the recording with NO key: the sliced cache goes into a keyless gateway and both
    candidates run on the Engine. It refuses unless the replay reproduces the saved reports (same
    board, url4 expression, case statuses, score, coverage, failure codes and combine evidence),
    the cached replay of the signal vote repeats the live signals and tally (SG-D1), the replayed
    traces differ from the live ones only in model-call accounting (RT-4), and the evidence lock
    holds. A refusal on SG-D1 or RT-4 is a product defect, not a bad recording. Then it writes the
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

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
    SignalReplayLock,
    assert_evidence_lock,
    assert_signal_replay,
    combines_drift,
    has_priced_signal,
    replayed_combines,
)
from harness.replay_trace import trace_drift  # noqa: E402

BOARD = "inspect-gsm8k"
LANE = "inspect-gsm8k-vote"
_OPERATION_ID = "op_synthesis_1"

_RECORD_PAID_ENV = "SCREAMINGFACE_RECORD_PAID"
_KEY_ENV = "OPENROUTER_API_KEY"
#: Fixed manifest date: committed fixtures carry no wall-clock traces.
_BLESSED_AT = "2026-10-01"
#: The signal the cost-weighted vote reads (SG#15). KNOWN GAP: this lane proves SG-D1 end to end for
#: ``cost_usd`` only. The cache entry metadata also carries latency and tokens, but no candidate of
#: this lane reads ``latency_ms`` or the token signals, so a replay that lost them would pass.
_SIGNAL = "cost_usd"
_MAX_DRIFT_PATHS = 5
_RECORDING_FILES = (
    "report.json",
    "signals-report.json",
    "trace.json",
    "signals-trace.json",
    "candidate.json",
    "recording.json",
    "cache.sql.gz",
)

#: The gateway's own 13-column layout (``CANONICAL_COLUMNS``): the board slices stop at 12, and this
#: lane adds ``metadata_json`` last. WHY: on a cache hit the gateway builds ``cache.reference`` (the
#: price, latency and tokens of the original call) from that column first. Without it OpenRouter's
#: fallback reports the tokens only, with no price and no latency, so a replay would give
#: ``cost_usd`` None and the cost-weighted vote could not be proven end to end (SG-D1). Only
#: ``cost_usd`` is proven (see ``_SIGNAL``); latency and tokens are a known gap.
_COPY_COLUMNS = f"{ss._COPY_COLUMNS}, metadata_json"

#: Every cache row the recording run wrote, normalized like the board slice (fixed row timestamps,
#: no expiry, counters zeroed). It is ``_SLICE_SQL`` without the baseline join, because a recording
#: starts from an empty cache and every row in it is the run's.
#: ONE EXCEPTION to "no wall-clock traces": ``metadata_json`` is copied verbatim, so its
#: ``observed_at`` keeps the time of the live call. It is TEXT (compact JSON), and normalizing it
#: needs a jsonb round trip that rewrites the stored bytes (spacing, key order) and cannot be tried
#: before a recording exists. Nothing in bless compares it: the evidence and the trace rule do not
#: read ``cache.observed_at``.
_RECORD_SQL = f"""COPY (
  SELECT r.id, r.key_hash, r.prompt_hash, r.provider, r.model, r.response_json,
         r.response_size_bytes,
         '{ss._ROW_TIMESTAMP}'::timestamptz, '{ss._ROW_TIMESTAMP}'::timestamptz,
         NULL::timestamptz, NULL::timestamptz, 0,
         r.metadata_json
  FROM public.request_cache_entries r
  ORDER BY r.key_hash
) TO STDOUT"""

#: ``slice_snapshot._SLICE_SQL`` plus ``metadata_json``: the rows the verified replay touched.
_SLICE_SQL = f"""COPY (
  SELECT r.id, r.key_hash, r.prompt_hash, r.provider, r.model, r.response_json,
         r.response_size_bytes,
         '{ss._ROW_TIMESTAMP}'::timestamptz, '{ss._ROW_TIMESTAMP}'::timestamptz,
         NULL::timestamptz, NULL::timestamptz, 0,
         r.metadata_json
  FROM public.request_cache_entries r
  LEFT JOIN public.bless_baseline b USING (key_hash)
  WHERE r.hit_count > COALESCE(b.hit_count, 0)
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
            f"COPY public.request_cache_entries ({_COPY_COLUMNS}) FROM stdin;",
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


def _record_run(engine_url: str, spec: ReducerCandidateSpec, limit: int) -> tuple[Any, Any]:
    """The cost-weighted vote, then the plain vote: ``(signal_report, report)``.

    WHY this order: both candidates send byte-identical member requests (the weights are read after
    the calls), so the first run takes the live misses and the second is served from the live cache.
    The spend is the plain lane's. The signal run is the one whose prices are real.
    """
    import screamingface as sf

    signal_spec = spec.model_copy(update={"weights": _SIGNAL})
    with sf.Client(engine_url=engine_url) as client:
        client.connect("openrouter", api_key=os.environ[_KEY_ENV])
        _require_seed_support(client, spec.model)
        print(f"[record] {spec.samples} samples x {limit} cases of {BOARD}, LIVE", flush=True)
        signal_report = client.evaluate(
            signal_spec.build(), benchmark=BOARD, limit=limit, progress=False
        )
        report = client.evaluate(spec.build(), benchmark=BOARD, limit=limit, progress=False)
        return signal_report, report


def _record_stack[T](
    assets_root: Path, work_dir: Path, run: Callable[[str], T]
) -> tuple[T, list[str]]:
    """Postgres, live gateway, inspect engine; ``run(engine_url)``; the cache rows it wrote.

    Both record lanes share this boot: they differ only in what ``run`` evaluates.
    """
    backend = CacheSeededGateway(snapshot=Path("unused"), manifest=None, work_dir=work_dir)
    gateway: ManagedProcess | None = None
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_root)
    try:
        database_url = backend._start_postgres()
        backend._migrate(database_url)
        gateway, gateway_url = _start_live_gateway(database_url, work_dir)
        result = run(engine.start(gateway_url))
        rows = _rows(ss._psql(backend._container, _RECORD_SQL))
    finally:
        engine.stop()
        if gateway is not None:
            gateway.stop()
        backend.stop_sync()
    return result, rows


def _write_trace(path: Path, report: Any) -> None:
    path.write_text(json.dumps(report.trace_dict(), ensure_ascii=False, indent=2) + "\n")


def _write_recording(
    out: Path, spec: ReducerCandidateSpec, limit: int, reports: tuple[Any, Any], rows: list[str]
) -> None:
    """The seven recording files (``_RECORDING_FILES``)."""
    signal_report, report = reports
    report.export(out / "report.json")
    signal_report.export(out / "signals-report.json")
    # The live traces: `Report` has no loader, so RT#16 needs them saved, not rebuilt.
    _write_trace(out / "trace.json", report)
    _write_trace(out / "signals-trace.json", signal_report)
    (out / "candidate.json").write_text(spec.model_dump_json(indent=2) + "\n")
    # The requested limit: `bless` replays the same selection and cross-checks it with the report.
    (out / "recording.json").write_text(json.dumps({"limit": limit, "signal": _SIGNAL}) + "\n")
    header = [
        "--",
        f"-- Raw cache rows recorded for lane '{LANE}' (reducer_lane.py record).",
        "--",
        "",
    ]
    (out / "cache.sql.gz").write_bytes(ss.snapshot_gzip(_snapshot_text(header, rows)))


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
    reports, rows = _record_stack(
        assets_root, work_dir, lambda url: _record_run(url, spec, args.limit)
    )
    _write_recording(args.out, spec, args.limit, reports, rows)
    with_metadata = sum(1 for row in rows if not row.endswith("\\N"))
    print(f"[metadata] rows with metadata_json: {with_metadata}/{len(rows)}", flush=True)
    outcome = reports[1].candidates.only
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
    signal_facts: Any
    signal_combines: dict[str, dict[str, Any]]
    live_traces: dict[str, dict[str, Any]]


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


def _read_json(recording: Path, name: str) -> Any:
    return json.loads((recording / name).read_text("utf-8"))


def _read_report(recording: Path, name: str, limit: int) -> tuple[Any, list[dict[str, Any]]]:
    """One saved report: its facts and Cases, once it is shown to describe one run of this lane."""
    raw = _read_json(recording, name)
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
    return facts, raw["candidates"][0]["cases"]


def _read_recording(recording: Path) -> _Recording:
    missing = [name for name in _RECORDING_FILES if not (recording / name).is_file()]
    if missing:
        raise SystemExit(
            f"the recording {recording} lacks {', '.join(missing)}: run `record` first"
        )
    limit = _read_json(recording, "recording.json")["limit"]
    facts, cases = _read_report(recording, "report.json", limit)
    signal_facts, signal_cases = _read_report(recording, "signals-report.json", limit)
    return _Recording(
        facts=facts,
        spec=ReducerCandidateSpec.model_validate_json(
            (recording / "candidate.json").read_text("utf-8")
        ),
        cache=recording / "cache.sql.gz",
        limit=limit,
        failures=_recorded_failures(cases),
        combines=_recorded_combines(cases),
        signal_facts=signal_facts,
        signal_combines=_recorded_combines(signal_cases),
        live_traces={
            "vote": _read_json(recording, "trace.json"),
            "signal_vote": _read_json(recording, "signals-trace.json"),
        },
    )


def _refuse(mismatch: bool, message: str) -> None:
    if mismatch:
        raise SystemExit(f"BLESS REFUSED: {message}")


def _refuse_unless_board_reproduced(
    report: Any, facts: Any, failures: dict[str, tuple[GoldenFailure, ...]]
) -> dict[str, str]:
    """The replay must reproduce the saved report on the board's own locks (the fusion lane too).

    The order is the order of ``compare_outcome``: board, expression, statuses, score, coverage,
    failure codes. Returns the replayed case statuses.
    """
    outcome = report.candidates.only
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
        failure_map(outcome.cases) != failures,
        "the replay's failure codes differ from the saved report's",
    )
    return statuses


def _refuse_unless_reproduced(report: Any, recording: _Recording) -> dict[str, str]:
    """The replay must reproduce the saved report, or the recording does not describe this lane.

    The board's locks (``_refuse_unless_board_reproduced``), then the combine evidence.
    """
    statuses = _refuse_unless_board_reproduced(report, recording.facts, recording.failures)
    _refuse(
        replayed_combines(report.candidates.only.cases) != recording.combines,
        "the replay's combine evidence differs from the saved report's",
    )
    return statuses


def _refuse_unless_signals_reproduced(signal_report: Any, recording: _Recording) -> None:
    """SG-D1: the cached replay of the cost-weighted vote repeats the live run's evidence.

    The rules: the url4 is the recorded one, every Case's evidence (signals, weights, tally,
    result) equals the recorded one, and the live run priced at least one call. A refusal here is a
    product defect report, not a recording mistake (the hit accounting lost a price).
    """
    outcome, facts = signal_report.candidates.only, recording.signal_facts
    _refuse(
        str(outcome.url4) != facts.rendered_url4,
        "the signal replay rendered a different url4 expression than signals-report.json "
        "recorded; candidate.json does not rebuild the recorded run",
    )
    drift = combines_drift(recording.signal_combines, replayed_combines(outcome.cases))
    _refuse(
        drift is not None,
        f"the cached replay's signals or tally differ from the live run's (SG-D1): {drift}",
    )
    _refuse(
        not has_priced_signal(recording.signal_combines),
        "the recording priced no call (SG#15 would prove nothing)",
    )


def _refuse_unless_traces_match(recording: _Recording, replayed: dict[str, Any]) -> None:
    """RT-4: each replayed trace differs from its live trace only in model-call accounting."""
    drift = [
        f"{name}:{path}"
        for name in ("vote", "signal_vote")
        for path in trace_drift(recording.live_traces[name], replayed[name])
    ]
    shown = ", ".join(drift[:_MAX_DRIFT_PATHS])
    _refuse(
        bool(drift),
        f"the replay trace drifted outside model-call accounting (RT-4): {len(drift)} "
        f"{'path' if len(drift) == 1 else 'paths'}, the first {_MAX_DRIFT_PATHS} at most: {shown}",
    )


def _evaluate_both(engine_url: str, recording: _Recording) -> tuple[Any, Any]:
    """The cost-weighted vote, then the plain one, as ``record`` ran them: ``(signal, plain)``."""
    signal_spec = recording.spec.model_copy(update={"weights": _SIGNAL})
    signal_report = ss._evaluate(engine_url, signal_spec.build(), BOARD, recording.limit)
    report = ss._evaluate(engine_url, recording.spec.build(), BOARD, recording.limit)
    return signal_report, report


def _replay_and_slice(
    recording: _Recording, assets_root: Path, work_dir: Path
) -> tuple[Any, Any, dict[str, str], list[str]]:
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
        signal_report, report = _evaluate_both(engine_url, recording)
        statuses = _refuse_unless_reproduced(report, recording)
        _refuse_unless_signals_reproduced(signal_report, recording)
        traces = {"vote": report.trace_dict(), "signal_vote": signal_report.trace_dict()}
        _refuse_unless_traces_match(recording, traces)
        rows = _rows(ss._psql(backend._container, _SLICE_SQL))
    finally:
        engine.stop()
        backend.stop_sync()
    return report, signal_report, statuses, rows


def _evidence(cases: Any) -> EvidenceLock:
    """The first case (report order) whose ``op_synthesis_1`` combine step answered.

    WHY answered only: with abstain, a Case that nobody voted for is ``scored`` with evidence whose
    result is an abstain and whose ``chosen`` is empty, and the evidence lock has no text to check.
    """
    for case in cases:
        for operation in case.operations or ():
            if _is_answered(operation):
                return EvidenceLock(
                    case_id=str(case.case_id),
                    operation_id=_OPERATION_ID,
                    combine=json.loads(json.dumps(operation.combine.to_dict())),
                )
    raise SystemExit(f"BLESS REFUSED: no case answered on {_OPERATION_ID}")


def _is_answered(operation: Any) -> bool:
    return (
        operation.operation_id == _OPERATION_ID
        and operation.combine is not None
        and operation.combine.result.status == "answered"
    )


def _author_golden(
    report: Any, signal_report: Any, recording: _Recording, statuses: dict[str, str]
) -> ReducerGolden:
    spec, limit = recording.spec, recording.limit
    outcome, signal = report.candidates.only, signal_report.candidates.only
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
            "signal_replay": SignalReplayLock(
                expression_sha=expression_sha(str(signal.url4)),
                combines=recording.signal_combines,
            ),
            "live_traces": recording.live_traces,
        }
    )
    # The golden must pass its own locks on the very run it was authored from.
    assert_evidence_lock(golden, outcome.cases)
    assert_signal_replay(golden, str(signal.url4), signal.cases)
    return golden


def _write_fixtures(
    golden: BaseModel,
    rows: list[str],
    header: list[str],
    max_snapshot_mb: float,
    work_dir: Path,
    *,
    lane: str = LANE,
    golden_kind: str = "reducer-golden",
) -> None:
    """The snapshot, its manifest and the golden of ``lane`` (the fusion lane has its own)."""
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
    (out_dir / "snapshots" / f"{lane}.snapshot.gz").write_bytes(snapshot)
    (out_dir / "snapshots" / f"{lane}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "goldens" / f"{lane}.{golden_kind}.json").write_text(
        json.dumps(golden.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    )
    print(f"[write] {lane}: snapshot {size_mb:.2f} MB ({len(rows)} rows) -> {out_dir}", flush=True)
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
    report, signal_report, statuses, rows = _replay_and_slice(recording, assets_root, work_dir)
    golden = _author_golden(report, signal_report, recording, statuses)
    report_sha = hashlib.sha256((args.recording / "report.json").read_bytes()).hexdigest()
    signals_sha = hashlib.sha256((args.recording / "signals-report.json").read_bytes()).hexdigest()
    # Provenance rule: sources are described generically plus content shas, never local paths.
    header = [
        "--",
        f"-- Sliced replay fixture for lane '{LANE}' (OME-1289 E4a; see reducer_lane.py).",
        "-- Every row VERBATIM from a recording made through this checkout's gateway",
        f"-- (cache content sha256 {ss._dump_content_sha(recording.cache)}), so the keys are",
        "-- already this protocol's. The bless proved the replay reproduces the saved SDK reports",
        f"-- (content sha256 {report_sha} and {signals_sha}): expression, statuses, score,",
        "-- coverage, failures, combine evidence, the cost-weighted signals and the traces.",
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
