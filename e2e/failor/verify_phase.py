#!/usr/bin/env python3
"""Perform an observability phase's acceptance against the DEPLOYED stack (OME-1182).

    packages/screamingface/.venv/bin/python e2e/failor/verify_phase.py --phase 1

`OME-1118`'s acceptance was a SigNoz query executed by hand. This is that procedure, made
repeatable and made to fail honestly.

    1. trigger   drive one run against the deployed engine (the client handles
                 mint -> WebSocket attach -> GET, and mints the W3C traceparent)
    2. collect   read `trace_id` off `CandidateResult`, or off the error for a failed run
    3. wait      poll SigNoz until the lines are ingested — they are not instant
    4. assert    the phase's required signals, per namespace
    5. report    a per-signal table; exit 0 on PASS, non-zero otherwise

INVARIANT — three outcomes, not two. PASS, FAIL, and BLOCKED are different things.
"No SigNoz token", "no Access session" and "no trace id" are failures to CHECK, not failures of
the phase; reporting them as FAIL sends someone hunting a regression that does not exist.
`OME-1106`'s review found the opposite mistake twice — a validator that printed READY for a lane
it could not evaluate — and that is the failure mode this tool exists to avoid in itself.

WHY it triggers its own run rather than accepting an id: during `OME-940` a real diagnosis went
wrong because a marker was absent from the deployed logs. The conclusion drawn was "not
deployed"; the truth was "no run has happened since the merge". Driving the run removes that
ambiguity by construction — if this tool caused the run, absence is a real absence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNOZ_BASE = os.environ.get(
    "SIGNOZ_BASE_URL", "https://signoz.pulse.dev.openmined.org"
)
ENGINE_URL = os.environ.get("SF_ENGINE_URL", "https://fusion.dev.screamingface.ai")
DEFAULT_MODEL = os.environ.get("SF_MODEL", "openrouter/openai/gpt-5.5")
DEFAULT_BOARD = os.environ.get("SF_BOARD", "draco")

NS_ENGINE = "sf-fusion"
NS_GATEWAY = "sf-aigw"

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class Signal:
    """One thing a phase claims is true of the deployed stack.

    `contains` is a tuple of substrings that must ALL appear on the SAME line, each rendered
    with the run's trace id. Every signal therefore asserts something about THIS run.

    INVARIANT: a signal that does not mention `{trace}` at all is almost certainly wrong. The
    first version asserted `gateway_call_id=` on its own and PASSED for a fabricated trace id,
    because some line somewhere always carries a call id — the exact weakness rung 4b's
    docstring warns about: "a log full of unrelated hex would satisfy the weaker check while
    joining nothing." Pairing it with the trace id is what makes it mean "this run's call".

    `namespace` of None means "anywhere", which is how the phase's actual end-to-end claim is
    expressed: one unfiltered query returning lines from more than one service.
    """

    label: str
    contains: tuple[str, ...]
    namespace: str | None
    owner: str
    min_namespaces: int = 1


PHASES: dict[int, tuple[Signal, ...]] = {
    1: (
        Signal("engine logs the run's trace id", ("{trace}",), NS_ENGINE, "OME-940"),
        Signal("gateway logs the run's trace id", ("{trace}",), NS_GATEWAY, "OME-1120"),
        Signal(
            "gateway call id on the SAME line",
            ("{trace}", "gateway_call_id="),
            NS_GATEWAY,
            "OME-938",
        ),
        Signal(
            "ONE id spans both services",
            ("{trace}",),
            None,
            "OME-1118 acceptance",
            min_namespaces=2,
        ),
    ),
}
"""Phase -> the signals its acceptance requires.

DATA, not control flow (D5): a later phase adds rows here. Phase 2 asserts spans rather than log
lines and will need a `kind` discriminator on `Signal`; that is a deliberate extension point,
not an oversight.
"""


@dataclass
class Result:
    outcome: str
    detail: str
    namespaces: dict[str, int] = field(default_factory=dict)


# --- SigNoz ------------------------------------------------------------------------------


class SigNozError(RuntimeError):
    """The backend could not be consulted — BLOCKED, never FAIL."""


def _signoz_logs(
    token: str, needles: Sequence[str], namespace: str | None, window_s: int
) -> list[dict]:
    """Log rows whose BODY contains EVERY needle, optionally within one namespace.

    Multiple `contains` filter items are ANDed by SigNoz, and they apply to the same row — which
    is what lets a signal require two tokens on ONE line rather than merely somewhere in the
    stream.

    WHY `body CONTAINS` and not an attribute filter: the k8s collector does not parse our
    plain-text lines, so `trace_id` and `gateway_call_id` live inside the message rather than as
    attributes. That is Phase 1's stated ceiling — grep, not filter — and this query is the
    honest expression of it.
    """
    end = int(time.time() * 1000)
    start = end - window_s * 1000
    items: list[dict] = [
        {
            "key": {"key": "body", "dataType": "string", "type": "", "isColumn": True},
            "op": "contains",
            "value": needle,
        }
        for needle in needles
    ]
    if namespace is not None:
        items.append(
            {
                "key": {
                    "key": "k8s.namespace.name",
                    "dataType": "string",
                    "type": "resource",
                    "isColumn": False,
                },
                "op": "=",
                "value": namespace,
            }
        )
    payload = {
        "start": start,
        "end": end,
        "step": 60,
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "list",
            "builderQueries": {
                "A": {
                    "dataSource": "logs",
                    "queryName": "A",
                    "aggregateOperator": "noop",
                    "aggregateAttribute": {},
                    "filters": {"op": "AND", "items": items},
                    "expression": "A",
                    "disabled": False,
                    "having": [],
                    "limit": 200,
                    "stepInterval": 60,
                    "orderBy": [{"columnName": "timestamp", "order": "asc"}],
                    "offset": 0,
                    "pageSize": 200,
                }
            },
        },
    }
    request = urllib.request.Request(
        f"{SIGNOZ_BASE}/api/v3/query_range",
        data=json.dumps(payload).encode(),
        headers={"SIGNOZ-API-KEY": token, "Content-Type": "application/json"},
    )
    try:
        body = json.load(urllib.request.urlopen(request, timeout=90))
    except urllib.error.HTTPError as exc:
        raise SigNozError(f"SigNoz returned HTTP {exc.code}") from exc
    except OSError as exc:
        raise SigNozError(f"SigNoz unreachable: {exc}") from exc
    if body.get("status") != "success":
        # An invalid key answers `unauthenticated` here, which is BLOCKED and not FAIL: the
        # phase may well be fine and we simply could not look.
        raise SigNozError(f"SigNoz refused the query: {json.dumps(body)[:200]}")
    rows: list[dict] = []
    for series in body.get("data", {}).get("result") or []:
        rows += series.get("list") or []
    return rows


def _namespaces_of(rows: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        resources = row.get("data", {}).get("resources_string") or {}
        name = resources.get("k8s.namespace.name", "?")
        counts[name] = counts.get(name, 0) + 1
    return counts


# --- the run -----------------------------------------------------------------------------


def trigger_run() -> tuple[str | None, str]:
    """Drive one run against the deployed engine; return (trace_id, detail).

    A FAILED run still yields an id (`OME-967` puts it on the error hierarchy) and is still a
    useful outcome — a failed deployed run is precisely what `OME-940`'s evidence lines exist
    for. So a raising run is not treated as a blocker unless it produced no id at all.
    """
    try:
        import screamingface as sf
    except ModuleNotFoundError:
        return None, (
            "screamingface is not importable — run this with "
            "packages/screamingface/.venv/bin/python"
        )

    try:
        with sf.Client(engine_url=ENGINE_URL) as client:
            report = client.evaluate(
                sf.Model(DEFAULT_MODEL),
                benchmark=DEFAULT_BOARD,
                limit=1,
                progress=False,
            )
        ids = {c.trace_id for c in report.candidates if c.trace_id}
        if ids:
            # `min` not `sorted()[0]`: one candidate is the normal case, and picking
            # deterministically matters only so a re-run quotes the same id.
            return min(ids), f"run completed ({len(ids)} candidate trace id(s))"
        return None, "the run completed but surfaced no trace id"
    except Exception as exc:  # noqa: BLE001 - any client failure is reported, never swallowed
        trace_id = getattr(exc, "trace_id", None)
        if trace_id:
            return (
                trace_id,
                f"run failed ({type(exc).__name__}) but carried its trace id",
            )
        return None, f"{type(exc).__name__}: {exc}"


# --- assertions ---------------------------------------------------------------------------


def evaluate_signal(token: str, signal: Signal, trace_id: str, window_s: int) -> Result:
    needles = tuple(part.format(trace=trace_id) for part in signal.contains)
    try:
        rows = _signoz_logs(token, needles, signal.namespace, window_s)
    except SigNozError as exc:
        return Result(BLOCKED, str(exc))

    # INVARIANT (D3): non-empty FIRST. A comparison over an empty result is the vacuous pass
    # that made ladder rung 2 report XPASS while nothing propagated.
    if not rows:
        where = signal.namespace or "any namespace"
        joined = " AND ".join(repr(n) for n in needles)
        return Result(FAIL, f"no line containing {joined} in {where}")

    namespaces = _namespaces_of(rows)
    if len(namespaces) < signal.min_namespaces:
        return Result(
            FAIL,
            f"{len(rows)} line(s) but only {len(namespaces)} namespace(s) "
            f"({', '.join(sorted(namespaces)) or 'none'}); needs {signal.min_namespaces}",
            namespaces,
        )
    return Result(PASS, f"{len(rows)} line(s)", namespaces)


def render(results: list[tuple[Signal, Result]]) -> None:
    width = max(len(s.label) for s, _ in results)
    for signal, result in results:
        where = signal.namespace or "any"
        print(
            f"  {result.outcome:<8} {signal.label:<{width}}  [{where:<10}] {result.detail}"
        )
        if result.namespaces:
            spread = ", ".join(f"{k}={v}" for k, v in sorted(result.namespaces.items()))
            print(f"           {'':<{width}}  {'':<12} {spread}")
        print(f"           {'':<{width}}  {'':<12} owner: {signal.owner}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--phase", type=int, default=1, help="which phase's acceptance to run"
    )
    parser.add_argument(
        "--trace-id",
        help="verify an EXISTING run instead of triggering one; see the note in the module "
        "docstring about why triggering is the default",
    )
    parser.add_argument(
        "--window-s", type=int, default=3600, help="how far back to search"
    )
    parser.add_argument(
        "--wait-s", type=int, default=120, help="how long to poll for log ingestion"
    )
    args = parser.parse_args(argv)

    signals = PHASES.get(args.phase)
    if signals is None:
        print(f"BLOCKED: no signal set defined for phase {args.phase}", file=sys.stderr)
        print(f"         defined phases: {sorted(PHASES)}", file=sys.stderr)
        return 2

    token = os.environ.get("SIGNOZ_TOKEN", "").strip()
    if not token:
        print(
            "BLOCKED: SIGNOZ_TOKEN is unset — the phase was NOT evaluated.",
            file=sys.stderr,
        )
        print("         Create one in SigNoz -> Settings -> API Keys.", file=sys.stderr)
        return 2

    print(f"phase   : {args.phase}")
    print(f"engine  : {ENGINE_URL}")
    print(f"signoz  : {SIGNOZ_BASE}\n")

    if args.trace_id:
        trace_id, detail = args.trace_id, "supplied by --trace-id (no run triggered)"
    else:
        trace_id, detail = trigger_run()
    print(f"run     : {detail}")

    if not trace_id:
        # INVARIANT: print the REASON THAT HAPPENED, not a menu of reasons. An earlier version
        # always suggested `cloudflared access login` — and printed it after a login that had
        # just SUCCEEDED, while the real failure was an unreachable catalog. A remedy that does
        # not match the cause sends the reader to fix something that is not broken, which is the
        # same class of defect as a validator that passes when it should not.
        print(
            f"\nBLOCKED: no trace id, so nothing can be asserted — {detail}",
            file=sys.stderr,
        )
        lowered = detail.lower()
        if "302" in detail or "access" in lowered or "html" in lowered:
            print(
                f"         Try: cloudflared access login {ENGINE_URL}", file=sys.stderr
            )
        elif "unavailable" in lowered or "reach" in lowered:
            print(
                "         The engine answered but a dependency did not — check that the "
                "gateway is up\n         and that a rollout is not in progress.",
                file=sys.stderr,
            )
        return 2
    if not TRACE_ID_RE.match(trace_id):
        print(f"\nBLOCKED: {trace_id!r} is not a 32-hex trace id.", file=sys.stderr)
        return 2
    print(f"trace   : {trace_id}\n")

    # D6: ingestion is not instant; a single immediate query would flake to FAIL.
    deadline = time.time() + args.wait_s
    results: list[tuple[Signal, Result]] = []
    while True:
        results = [
            (s, evaluate_signal(token, s, trace_id, args.window_s)) for s in signals
        ]
        if all(r.outcome == PASS for _, r in results) or time.time() >= deadline:
            break
        waited = int(args.wait_s - (deadline - time.time()))
        print(f"  ... not all signals present after {waited}s, waiting for ingestion")
        time.sleep(10)

    render(results)
    outcomes = {r.outcome for _, r in results}
    print()
    if BLOCKED in outcomes:
        print(
            "BLOCKED — the phase was not evaluated. Fix the reasons above and re-run."
        )
        return 2
    if FAIL in outcomes:
        failed = sum(1 for _, r in results if r.outcome == FAIL)
        print(
            f"FAIL — {failed} of {len(results)} signal(s) absent for trace {trace_id}."
        )
        print(
            "       A signal can be absent because the change is not DEPLOYED, not because"
        )
        print(
            "       it did not run: this tool drove the run itself, so absence is real."
        )
        return 1
    print(f"PASS — phase {args.phase} acceptance holds for trace {trace_id}.")
    print(
        f"       SigNoz: {SIGNOZ_BASE}/logs-explorer"
        f"?query=body%20CONTAINS%20%22{trace_id}%22"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
