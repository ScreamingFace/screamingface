"""The correlation-chain ladder — one rung per change in the tracing roadmap (OME-1105).

Mental model: this file is the acceptance test for `OME-935`, runnable on a laptop. The
live-k8s notebook (`e2e/failor/notebooks/`) validates the same chain against the deployed
stack, but it needs cluster credentials; this needs only Docker. k8s adds deployment realism
— the Runner Job indirection, the mesh edge — and adds nothing to the question each rung
asks, which is whether a trace id survives one hop.

**`xfail(strict=True)` is the mechanism, not decoration.** A strict xfail that starts passing
FAILS the suite, so the change that implements a rung is forced to delete its marker in the
same PR. Without `strict`, an implemented rung would sit here quietly marked "expected
failure" forever, and a later regression would look identical to the status quo.

Which backend, and why it is not a free choice:

- **Rungs 1–2 use `FakeGateway`** — an in-process ``BaseHTTPRequestHandler``, so the headers
  the engine sent are directly observable. This is the only way to see the engine→gateway
  wire from the test process.
- **Rungs 3–4 use `CacheSeededGateway`** — the REAL aigateway as a subprocess. Nothing
  in-process can see its request handling, so its only channel is ``aigateway.log``, which is
  exactly what those two rungs assert on.

INVARIANT (OME-1105): the header recorder lives on `FakeGateway`, never on
``ports.ReplayBackend``. That protocol is exactly ``start()``/``stop()`` and its own docstring
forbids growing it with introspection — a hook there would couple the engine boot to one
backend's internals.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness._gating import FIXTURES_DIR, SNAPSHOTS_DIR, require_e2e_stack
from harness.cache_seeded import CacheSeededGateway
from harness.fake_gateway import FakeGateway
from harness.stack import EngineProcess, replay_stack
from harness.tape import load_tape

BOARD = "draco"
CANDIDATE_MODEL = "openrouter/openai/gpt-5.5"
"""A model the synthetic tape actually carries.

WHY this matters more than it looks (OME-1121): the first version named a model absent from
the tape's catalog projection, so `evaluate` raised `PlanningError` at the availability probe
(`runner.py`'s `_missing_required_models`) — BEFORE the transport ran. No transport means no
trace context, so every rung read an empty id set and rung 1 could never pass. The failure
looked like a missing feature and was a wrong fixture.
"""
_ASSETS_ENV = "SCREAMINGFACE_E2E_ASSETS"

TRACEPARENT = re.compile(r"^00-(?!0{32}$)([0-9a-f]{32})-(?!0{16}$)([0-9a-f]{16})-[0-9a-f]{2}$")
"""The shape url4's own ``_TRACEPARENT_RE`` accepts, plus its two all-zero rejections.

WHY restated rather than imported: `packages/screamingface` does not depend on `url4`, and
`OME-967` mints locally rather than adding a distribution dependency for four lines of string
formatting. This regex IS the contract between the two packages, so it is written where it is
asserted.
"""


def _assets_root() -> Path:
    override = os.environ.get(_ASSETS_ENV)
    return Path(override) if override else FIXTURES_DIR / "assets"


def _require_draco_assets() -> Path:
    assets = _assets_root()
    if not (assets / BOARD).is_dir():
        pytest.skip(
            f"the correlation ladder drives the {BOARD} board and needs prepared assets at "
            f"{assets / BOARD} (run `screamingface prepare {BOARD}`, or point {_ASSETS_ENV} "
            f"at them)"
        )
    return assets


def _trace_ids(values: Iterator[str] | list[str]) -> set[str]:
    """The distinct trace ids inside a collection of raw ``traceparent`` values."""
    found = set()
    for value in values:
        match = TRACEPARENT.match(value or "")
        if match:
            found.add(match.group(1))
    return found


# --- rungs 1-2: the wire, observed at an in-process gateway --------------------------------


def _one_run(engine_url: str) -> tuple[set[str], list[str]]:
    """Drive one real run and return (trace ids the PUBLIC surface gave us, frame values).

    Both outcomes are evidence. A completed run yields ids through
    `CandidateResult.trace_id` (OME-1121) — the path that matters, because a board run
    collects case errors into rows rather than raising, so the user with bad results reaches
    here. A run that fails outright yields the id on the error (OME-967), which covers the
    pre-first-frame classes.
    """
    import screamingface as sf

    seen: list[str] = []
    ids: set[str] = set()
    with sf.Client(engine_url=engine_url) as client:
        try:
            report = client.evaluate(
                sf.Model(CANDIDATE_MODEL),
                benchmark=BOARD,
                limit=1,
                progress=False,
                on_event=lambda event: seen.append(getattr(event, "traceparent", "") or ""),
            )
            ids |= {c.trace_id for c in report.candidates if c.trace_id}
        except sf.ScreamingFaceError as exc:
            if exc.trace_id:
                ids.add(exc.trace_id)
    return ids | _trace_ids([v for v in seen if v]), [v for v in seen if v]


@pytest.fixture(scope="module")
def wire_run(tmp_path_factory: pytest.TempPathFactory):
    """One real run against `FakeGateway`, keeping the frames and the inbound headers.

    Booted once: the engine subprocess is the slow part, and both wire rungs read the same
    single run rather than paying for it twice.
    """
    require_e2e_stack()
    assets = _require_draco_assets()

    work_dir = tmp_path_factory.mktemp("correlation-wire")
    fake = FakeGateway(load_tape(SNAPSHOTS_DIR / "synthetic.tape.json"))
    engine = EngineProcess(work_dir=work_dir, assets_dir=assets)

    base_url = fake.start_sync()
    try:
        client_ids, frames = _one_run(engine.start(base_url))
        yield {
            "client_ids": client_ids,
            "frames": frames,
            "gateway": fake,
            "engine_log": work_dir / "engine.log",
        }
    finally:
        engine.stop()
        fake.stop_sync()


@pytest.mark.e2e
def test_rung1_one_coherent_trace_id_spans_the_run(wire_run) -> None:
    """RUNG 1 (`OME-967` + `OME-1121` — must PASS).

    The run surfaces exactly one well-formed trace id through the PUBLIC surface.

    This was a strict xfail until `OME-1121`. The reason is worth keeping: `OME-967` put the
    id only on the error hierarchy, and a board run does not raise — DRACO *collects* case
    errors into rows (`on_error="collect"`), so a run whose every model call failed still
    returned a Report carrying no id anywhere. The user most needing to quote an id could not
    obtain one. `CandidateResult.trace_id` closed that.

    Scope note: this asserts COHERENCE and REACHABILITY, not origination. Origination is
    pinned where it is observable — `tests/test_client_protocol.py`, against the wire.
    """
    client_ids = wire_run["client_ids"]
    assert client_ids, "the run surfaced no trace id — neither on an error nor on any frame"
    assert len(client_ids) == 1, f"the run split across {len(client_ids)} trace ids"
    (trace_id,) = client_ids
    assert TRACEPARENT.match(f"00-{trace_id}-0000000000000001-01"), trace_id


@pytest.mark.e2e
@pytest.mark.xfail(strict=True, reason="rung 2: the engine sends no traceparent to aigateway")
def test_rung2_the_engine_propagates_the_trace_id_to_the_gateway(wire_run) -> None:
    """RUNG 2 (not built — strict xfail).

    The gateway must receive the run's OWN trace id, not merely some traceparent. The audit
    captured the engine's outbound header set as `Host, Accept, Accept-Encoding, Connection,
    User-Agent, X-User-Email, X-Profile, Content-Length, Content-Type` — no traceparent at
    all, on any of its three client paths.
    """
    gateway: FakeGateway = wire_run["gateway"]
    assert gateway.inbound_headers, "the engine made no call to the gateway"
    seen_ids = gateway.trace_ids_seen()
    # WHY the non-empty assertion comes FIRST: without it this rung passes vacuously the
    # moment both sides are empty, because `set() == set()`. That is exactly what happened
    # on the first run of this file — a strict xfail reported XPASS while nothing propagated.
    assert seen_ids, "the gateway received no traceparent on any inbound request"
    assert seen_ids == wire_run["client_ids"]


@pytest.mark.e2e
@pytest.mark.xfail(strict=True, reason="rung 4a: the engine does not log its trace id")
def test_rung4a_the_engine_logs_the_run_trace_id(wire_run) -> None:
    """RUNG 4, engine half (not built — strict xfail; `OME-940`).

    A trace id that never reaches a log line cannot be grepped, which is the whole payoff.
    Split from the gateway half below because the two land in different changes.
    """
    log_text = Path(wire_run["engine_log"]).read_text(errors="replace")
    client_ids = wire_run["client_ids"]
    assert client_ids, "no trace id to look for"
    assert any(t in log_text for t in client_ids)


# --- rungs 3-4b: the logs, from the real aigateway -----------------------------------------


@pytest.fixture(scope="module")
def gateway_log(tmp_path_factory: pytest.TempPathFactory):
    """One real run against the REAL aigateway, yielding its log text AND the run's trace id.

    WHY a second stack rather than reusing the one above: `FakeGateway` writes no log, and
    these two rungs assert on aigateway's own log lines. Nothing in-process can observe a
    subprocess's request handling, so the log IS the interface.
    """
    require_e2e_stack()
    assets = _require_draco_assets()
    snapshot = SNAPSHOTS_DIR / "draco-3pass.snapshot.gz"
    manifest = SNAPSHOTS_DIR / "draco-3pass.manifest.json"
    if not snapshot.is_file():
        pytest.skip(f"missing cache snapshot {snapshot}")

    import screamingface as sf

    work_dir = tmp_path_factory.mktemp("correlation-logs")
    backend = CacheSeededGateway(snapshot=snapshot, manifest=manifest, work_dir=work_dir)
    seen: list[str] = []
    with replay_stack(backend, work_dir=work_dir, assets_dir=assets) as stack:
        with sf.Client(engine_url=stack.engine_url) as client:
            try:
                client.evaluate(
                    sf.Model(CANDIDATE_MODEL),
                    benchmark=BOARD,
                    limit=1,
                    progress=False,
                    on_event=lambda event: seen.append(getattr(event, "traceparent", "") or ""),
                )
            except sf.ScreamingFaceError:
                pass  # the log is the evidence either way — see the wire fixture's note
    yield {
        "text": (work_dir / "aigateway.log").read_text(errors="replace"),
        "trace_ids": _trace_ids([v for v in seen if v]),
    }


@pytest.mark.e2e
@pytest.mark.xfail(strict=True, reason="rung 3: OME-938 gateway_call_id is not on log lines")
def test_rung3_every_gateway_log_line_carries_a_call_id(gateway_log) -> None:
    """RUNG 3 (`OME-938`, not built — strict xfail).

    EVERY line, not a sample. The injector wraps a log-record factory, and a wrapper that
    misses a code path is precisely the defect this rung exists to catch — a spot check on
    the chat path would pass while startup and error paths stayed anonymous.
    """
    lines = [ln for ln in gateway_log["text"].splitlines() if ln.strip()]
    assert lines, "the gateway wrote no log lines"
    assert [ln for ln in lines if "gateway_call_id" in ln] == lines


@pytest.mark.e2e
@pytest.mark.xfail(strict=True, reason="rung 4b: aigateway does not join the inbound trace")
def test_rung4b_the_gateway_logs_this_runs_trace_id(gateway_log) -> None:
    """RUNG 4, gateway half (not built — strict xfail).

    The payoff rung: once this and its engine twin pass, one id is greppable across both
    services and a bug report's `trace_id` finally points at something.

    It asserts THIS run's id, not merely that some 32-hex token appears — a log full of
    unrelated hex would satisfy the weaker check while joining nothing.
    """
    trace_ids = gateway_log["trace_ids"]
    assert trace_ids, "the run emitted no trace id to look for"
    assert any(t in gateway_log["text"] for t in trace_ids)
