"""Generate Studio's run-stream fixtures from url4's own protocol models.

`src/lib/engine/run.test.ts` drives the run client with these frames. They are built with the
same pydantic models and codec the Engine's WebSocket bridge uses
(`packages/url4/src/url4/streaming/protocol`, `codec.encode`/`decode`), so every field name,
alias (`gen_ai.*`) and the string-typed `sequence` + `sequencetype: "Integer"` are exactly what
the wire carries. The order and attributes follow the live IFEval 1-case run checked on
2026-10-05 (plan, "Checked against the live runtime"): started, span, case/answer/model-call
activity logs, a `sf.progress.*` log, a subtree `cost.usage`, the result, then `terminated`.

Regenerate (from the monorepo root), then commit the JSON:

    cd packages/screamingface
    uv run --frozen python \
      ../../apps/screamingface-studio/frontend/scripts/gen-run-frames.py \
      > ../../apps/screamingface-studio/frontend/src/lib/engine/__fixtures__/frames.json

`--frozen` keeps `uv.lock` untouched; revert it if a run changes it anyway.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal

from url4.streaming.codec import decode, encode
from url4.streaming.protocol import (
    CostBreakdown,
    CostUsageEvent,
    CostUsageData,
    ErrorData,
    ErrorEvent,
    ErrorInfo,
    HeartbeatEvent,
    LogData,
    LogEvent,
    ResultData,
    ResultEvent,
    SpanData,
    SpanEvent,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
    TokenUsage,
    source_for,
)
from url4.streaming.protocol.signals import ResultArtifact

TOPIC = "3f1c2a9e8b7d4c6f9a0b1c2d3e4f5a6b"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
NODE = "n0"
WHEN = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

CANDIDATE_RESULT = {
    "schema": "screamingface.candidate-result.v1",
    "benchmark_id": "ifeval",
    "benchmark_revision": "ifeval-2023-11.r1",
    "case_count": 1,
    "score": 1.0,
    "coverage": 1.0,
    "metrics": {"prompt_level_strict_accuracy": 1.0},
    "cases": [
        {
            "status": "scored",
            "case_id": 1000,
            "input": "Write a haiku about the sea. Do not use any commas.",
            "output": "Waves fold into foam\nsalt wind carries gull voices\nthe tide keeps its time",
            "finish_reason": "stop",
            "refusal": None,
            "grade": {
                "method": "ifeval",
                "score": 1.0,
                "metrics": {"prompt_level_strict": True},
                "checks": [
                    {
                        "type": "instruction",
                        "id": "punctuation:no_comma",
                        "label": "No commas",
                        "outcome": "MET",
                        "score": 1.0,
                        "evidence": [],
                        "metadata": {},
                    }
                ],
            },
            "failures": [],
            "metadata": {},
            "operations": [
                {
                    "operation_id": "op_model_1",
                    "output": "Waves fold into foam…",
                    "finish_reason": "stop",
                    "accounting": {
                        "provider": "openai",
                        "request_model": "openai/gpt-4o",
                        "response_model": "gpt-4o-2024-08-06",
                        "usage": {
                            "input_tokens": 31,
                            "output_tokens": 19,
                            "cache_read_tokens": 0,
                            "cache_creation_tokens": 0,
                            "reasoning_tokens": 0,
                            "cost_usd": "0.0002675",
                        },
                        "provider_latency_ms": 812,
                        "provider_attempts": 1,
                        "cache": {"hits": 0, "misses": 1, "bypasses": 0, "unknown": 0},
                    },
                }
            ],
        }
    ],
    "failures": [],
}


def _frame(event, sequence: int | None) -> dict:
    """One frame exactly as the bridge sends it: encoded, then sequence-stamped."""

    return json.loads(encode(decode(encode(event), sequence)))


def _envelope(n: int) -> dict:
    return {
        "id": f"evt-{n:04d}",
        "source": source_for(TOPIC, NODE),
        "subject": TRACE,
        "time": WHEN,
    }


def _activity(n: int, kind: str, state: str, label: str, **facts) -> LogEvent:
    attributes = {
        "sf.activity.schema": "screamingface.activity.v1",
        "sf.activity.kind": kind,
        "sf.activity.state": state,
        "sf.activity.id": f"{kind}-1",
        "sf.activity.revision": 1 if state == "started" else 2,
        "sf.activity.elapsed_ms": 0 if state == "started" else 840,
        "sf.activity.observed_at_ms": 1791201600000,
        **{f"sf.activity.{name}": value for name, value in facts.items()},
    }
    return LogEvent(
        **_envelope(n), data=LogData.at("INFO", f"{label} {state}", attributes)
    )


def happy_path() -> list[dict]:
    body = json.dumps(CANDIDATE_RESULT, separators=(",", ":"))
    events = [
        StartedEvent(
            **_envelope(1), data=StartedData(url4="(candidate:0.0:'…', …)!''")
        ),
        SpanEvent(
            **_envelope(2),
            data=SpanData(
                name="chat openai/gpt-4o",
                kind="client",
                operation="chat",
                provider="openai",
                request_model="openai/gpt-4o",
                input_tokens=31,
                output_tokens=19,
                start=WHEN,
                end=WHEN,
            ),
        ),
        _activity(3, "case_loading", "started", "Loading cases", benchmark_id="ifeval"),
        _activity(
            4,
            "case_loading",
            "completed",
            "Loading cases",
            benchmark_id="ifeval",
            loaded_count=541,
            selected_count=1,
        ),
        _activity(5, "answering", "started", "Answering", case_id=1000),
        _activity(
            6,
            "model_call",
            "started",
            "Model call",
            case_id=1000,
            model_id="openai/gpt-4o",
            provider="openai",
            attempt=1,
        ),
        _activity(
            7,
            "model_call",
            "completed",
            "Model call",
            case_id=1000,
            model_id="openai/gpt-4o",
            provider="openai",
            attempt=1,
            finish_reason="stop",
        ),
        _activity(8, "answering", "completed", "Answering", case_id=1000),
        LogEvent(
            **_envelope(9),
            data=LogData.at(
                "INFO",
                "Benchmark progress",
                {
                    "sf.progress.schema": "screamingface.benchmark-progress.v1",
                    "sf.progress.benchmark": "ifeval",
                    "sf.progress.benchmark_revision": "ifeval-2023-11.r1",
                    "sf.progress.revision": 1,
                    "sf.progress.completed": 1,
                    "sf.progress.graded": 1,
                    "sf.progress.score": 1.0,
                },
            ),
        ),
        CostUsageEvent(
            **_envelope(10),
            data=CostUsageData(
                scope="subtree",
                provider="openai",
                model="gpt-4o-2024-08-06",
                pricing_version="2026-10-01",
                usage=TokenUsage(input_tokens=31, output_tokens=19),
                cost=CostBreakdown(
                    input_usd=Decimal("0.0000775"),
                    output_usd=Decimal("0.00019"),
                    total_usd=Decimal("0.0002675"),
                ),
            ),
        ),
        ResultEvent(
            **_envelope(11), data=ResultData(body=body, media_type="application/json")
        ),
        TerminatedEvent(**_envelope(12), data=TerminatedData(status="succeeded")),
    ]
    return [_frame(event, index) for index, event in enumerate(events, 1)]


def main() -> None:
    body = json.dumps(CANDIDATE_RESULT, separators=(",", ":")).encode()
    digest = hashlib.sha256(body).hexdigest()
    fixtures = {
        "happyPath": happy_path(),
        "candidateResult": CANDIDATE_RESULT,
        "heartbeat": _frame(HeartbeatEvent(**_envelope(900)), None),
        "artifactResult": _frame(
            ResultEvent(
                **_envelope(11),
                data=ResultData(
                    artifact=ResultArtifact(
                        id=digest, size_bytes=len(body), sha256=digest
                    )
                ),
            ),
            11,
        ),
        "artifactBody": body.decode(),
        "terminatedBenchmarkUnavailable": _frame(
            TerminatedEvent(
                **_envelope(3),
                data=TerminatedData(
                    status="failed",
                    error=ErrorInfo(
                        code="benchmark_unavailable",
                        message="Benchmark 'ifeval' is not prepared on this Engine",
                        permanent=True,
                    ),
                ),
            ),
            3,
        ),
        "terminatedStopped": _frame(
            TerminatedEvent(**_envelope(4), data=TerminatedData(status="stopped")), 4
        ),
        "errorInvalidFrame": _frame(
            ErrorEvent(
                **_envelope(901),
                data=ErrorData(
                    code="invalid_frame", message="from_sequence must be >= 1"
                ),
            ),
            None,
        ),
    }
    json.dump(fixtures, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
