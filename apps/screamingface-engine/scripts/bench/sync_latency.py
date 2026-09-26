"""Sync-path latency harness (uniform executor test-plan §6). REPORT ONLY — the numbers gate
nothing (ans:Q3).

Runs one case against a port-forwarded App: 300 sequential requests, then 300 at concurrency 8,
and writes `docs/plans/uniform-executor/measurements/<date>-<case>.md` plus the raw JSON beside
it. The kind environment's stub gateway answers after `STUB_LATENCY_MS` (200 by default).

Cases:
    B1  a mount call through the node tier (the baseline; `values-kind-node.yaml`)
    B2  `GET /?q=` sync single-model, cold spawn (`runnerPool.warmChildren=0`)
    B3  `GET /?q=` sync single-model, warm children
    B4  a mount call as a direct run, warm children

    uv run python scripts/bench/sync_latency.py --case B3 --base-url http://127.0.0.1:18108 \\
        --expression "('hi')!'answer'"
    uv run python scripts/bench/sync_latency.py --case B4 --base-url http://127.0.0.1:18108 \\
        --mount "/anthropic/claude-haiku-4-5?q=('hi')!'answer'"

`--metrics-url` (a port-forwarded runner-pod /metrics) adds the worker's
`worker_handoff_latency_s` / `worker_child_boot_s` summaries to the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

_MEASUREMENTS = Path(__file__).resolve().parents[2] / "docs/plans/uniform-executor/measurements"
_IDENTITY = {"X-User-Email": "bench@example.com"}


@dataclass
class Phase:
    concurrency: int
    latencies_ms: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, float | int]:
        values = sorted(self.latencies_ms)
        if not values:
            return {"n": 0, "errors": sum(self.errors.values())}

        def pct(p: float) -> float:
            return round(values[min(len(values) - 1, int(p * len(values)))], 1)

        return {
            "n": len(values),
            "p50_ms": round(statistics.median(values), 1),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "max_ms": round(values[-1], 1),
            "errors": sum(self.errors.values()),
        }


async def _one(client: httpx.AsyncClient, args: argparse.Namespace) -> tuple[float, str | None]:
    started = time.perf_counter()
    try:
        if args.mount:
            response = await client.get(args.mount, headers=_IDENTITY)
        else:
            token = (await client.post("/token")).json()["token"]
            response = await client.get(
                "/", params={"q": args.expression}, headers={"URL4-Capability": token, **_IDENTITY}
            )
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, None if response.status_code == 200 else f"http_{response.status_code}"
    except httpx.HTTPError as exc:
        return (time.perf_counter() - started) * 1000, type(exc).__name__


async def _phase(client: httpx.AsyncClient, args: argparse.Namespace, concurrency: int) -> Phase:
    phase = Phase(concurrency)
    gate = asyncio.Semaphore(concurrency)

    async def _run() -> None:
        async with gate:
            elapsed, error = await _one(client, args)
        if error is None:
            phase.latencies_ms.append(elapsed)
        else:
            phase.errors[error] = phase.errors.get(error, 0) + 1

    await asyncio.gather(*(_run() for _ in range(args.requests)))
    return phase


def _histogram(metrics_text: str, name: str) -> dict[str, float]:
    """`_sum` / `_count` (and the mean) of one Prometheus histogram from a scrape."""
    out: dict[str, float] = {}
    for line in metrics_text.splitlines():
        for suffix in ("_sum", "_count"):
            if line.startswith(f"{name}{suffix} "):
                out[suffix[1:]] = float(line.split()[-1])
    if out.get("count"):
        out["mean_s"] = round(out["sum"] / out["count"], 4)
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", required=True, choices=["B1", "B2", "B3", "B4"])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expression", default="('hi')!'answer'")
    parser.add_argument("--mount", help="a mount target, e.g. /corpus/papers (B1, B4)")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--metrics-url", help="a runner pod's /metrics, port-forwarded")
    parser.add_argument("--note", default="", help="free text recorded in the report")
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        sequential = await _phase(client, args, 1)
        concurrent = await _phase(client, args, 8)
    worker: dict[str, dict[str, float]] = {}
    if args.metrics_url:
        async with httpx.AsyncClient(timeout=10.0) as scrape:
            text = (await scrape.get(args.metrics_url)).text
        for name in (
            "screamingface_engine_worker_handoff_latency_s",
            "screamingface_engine_worker_child_boot_s",
        ):
            worker[name] = _histogram(text, name)

    stamp = datetime.now(UTC)
    report = {
        "case": args.case,
        "time": stamp.isoformat(),
        "target": args.mount or f"GET /?q={args.expression}",
        "note": args.note,
        "sequential": sequential.summary(),
        "concurrency_8": concurrent.summary(),
        "errors": {"sequential": sequential.errors, "concurrency_8": concurrent.errors},
        "worker": worker,
    }
    _MEASUREMENTS.mkdir(parents=True, exist_ok=True)
    base = _MEASUREMENTS / f"{stamp:%Y-%m-%d}-{args.case}"
    base.with_suffix(".json").write_text(
        json.dumps({**report, "raw": {"sequential": asdict(sequential), "c8": asdict(concurrent)}})
    )
    rows = "\n".join(
        f"| {label} | {s.get('n')} | {s.get('p50_ms')} | {s.get('p95_ms')} | {s.get('p99_ms')} "
        f"| {s.get('max_ms')} | {s.get('errors')} |"
        for label, s in (
            ("sequential", report["sequential"]),
            ("concurrency 8", report["concurrency_8"]),
        )
    )
    worker_rows = "\n".join(f"- `{k}`: {v}" for k, v in worker.items()) or "- (not scraped)"
    base.with_suffix(".md").write_text(
        f"# {args.case} — {report['target']}\n\n"
        f"Measured {report['time']} on the kind environment (report only, ans:Q3).\n"
        f"{args.note}\n\n"
        "| Phase | n | p50 ms | p95 ms | p99 ms | max ms | errors |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{rows}\n\n"
        f"Errors by kind: `{json.dumps(report['errors'])}`\n\n"
        f"Worker histograms:\n{worker_rows}\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
