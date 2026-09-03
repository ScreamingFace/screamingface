"""A fixture-event generator for the screamingface-engine wire protocol: builds a
fixed, deterministic sequence of protocol events (`build_run`) for one fake run —
no url4 execution, no model calls.

Conforms to the taxonomy invariants of spec §8: monotonic sequence numbers, `CostBreakdown.total_usd
== Σ parts` (model-enforced), a per-node `CostUsage{scope=self}` frame plus a root
`CostUsage{scope=subtree}` frame whose total equals self-cost plus the sum of children's costs, a
well-formed span parent/child tree, and the subtree `CostUsage` frame emitted before the terminal
`Result`/`Terminated` frames.

Used two ways: `publish_mock_run` publishes the sequence onto any injected `EventPublisher` — the
in-memory test path uses a fake — and `main` is a real-NATS-publishing CLI entrypoint that reads the
run's topic/expression from the environment and publishes via `JetStreamPublisher`. Used for
local/dev fixtures and the compose e2e where a real Runner + model provider would be slow, flaky,
or unavailable."""

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal, TypedDict
from uuid import uuid4

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import JetStreamPublisher
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import (
    CostBreakdown,
    CostUsageData,
    CostUsageEvent,
    LogData,
    LogEvent,
    OutboundFrame,
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
from url4.streaming.trace import format_parent_tracestate, format_traceparent

# AIDEV-NOTE: this double plays the RUN mode's role, so it reads deploy-time variables the App
# never writes — in a real deployment the chart names and values them and the Job inherits them
# via `envFrom`. These used to be re-spelled string literals here, because the backend could not
# import the Runner's `job_env`; one distribution means it just reads the real names.

_ROOT_SPAN = "00000000000000a1"
_C0_SPAN = "00000000000000b2"
_C1_SPAN = "00000000000000c3"


class _Envelope(TypedDict):
    id: str
    source: str
    subject: str
    time: datetime
    sequence: str
    sequencetype: Literal["Integer"]


class _Emitter:
    """Builds the CloudEvents envelope and OTel trace context for one fixture run's frames: a
    monotonic per-emitter sequence, and a single trace id derived deterministically from the
    topic so every span/log/cost frame in the run shares it."""

    def __init__(self, topic: str) -> None:
        self._topic = topic
        self._trace = sha256(topic.encode("utf-8")).hexdigest()[:32]
        self._n = 0

    def next(self, node: str) -> _Envelope:
        """The next CloudEvents envelope for `node` (source path + incrementing sequence)."""
        self._n += 1
        return _Envelope(
            id=uuid4().hex,
            source=source_for(self._topic, node),
            subject=self._topic,
            time=datetime.now(UTC),
            sequence=str(self._n),
            sequencetype="Integer",
        )

    def span_event(self, node: str, span_id: str, parent: str | None, data: SpanData) -> SpanEvent:
        """A `SpanEvent` for `node`, with `traceparent` set to this run's shared trace id and,
        when `parent` is given, `tracestate` linking it as that span's child."""
        tracestate = None if parent is None else format_parent_tracestate(parent)
        return SpanEvent(
            **self.next(node),
            data=data,
            traceparent=format_traceparent(self._trace, span_id),
            tracestate=tracestate,
        )


def _log(body: str) -> LogData:
    return LogData.at("INFO", body)


def _span(operation: str, in_tokens: int, out_tokens: int) -> SpanData:
    now = datetime.now(UTC)
    return SpanData(
        name=operation,
        operation=operation,
        provider="anthropic",
        request_model="claude-opus-4-8",
        response_model="claude-opus-4-8",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        start=now,
        end=now,
    )


def _cost(
    scope: Literal["self", "subtree"], in_usd: str, out_usd: str, in_tok: int, out_tok: int
) -> CostUsageData:
    # INVARIANT: total_usd == input + output (the CostBreakdown validator enforces Σ parts).
    return CostUsageData(
        scope=scope,
        provider="anthropic",
        model="claude-opus-4-8",
        pricing_version="2026-07-01",
        usage=TokenUsage(input_tokens=in_tok, output_tokens=out_tok),
        cost=CostBreakdown(
            input_usd=Decimal(in_usd),
            output_usd=Decimal(out_usd),
            total_usd=Decimal(in_usd) + Decimal(out_usd),
        ),
    )


# Per-node self costs + the root subtree roll-up. INVARIANT (spec §8): subtree.total (0.0450) ==
# root.self (0.0300) + leaf0.self (0.0100) + leaf1.self (0.0050); tokens roll up identically
# (1400 in / 350 out). Kept as constants so the arithmetic is auditable here.
_ROOT_SELF = _cost("self", "0.0100", "0.0200", 800, 200)
_C0_SELF = _cost("self", "0.0050", "0.0050", 400, 100)
_C1_SELF = _cost("self", "0.0030", "0.0020", 200, 50)
_SUBTREE = _cost("subtree", "0.0180", "0.0270", 1400, 350)


def build_run(topic: str, url4: str) -> list[OutboundFrame]:
    """The full deterministic frame sequence for one fixture run: started, a log, a root span
    with two child spans (each with its own cost.usage), the root's own and subtree cost.usage,
    a result, and a terminated frame — no real url4 execution behind any of it."""
    em = _Emitter(topic)
    frames: list[OutboundFrame] = []
    frames.append(StartedEvent(**em.next("root"), data=StartedData(url4=url4)))
    frames.append(LogEvent(**em.next("root"), data=_log(f"executing {url4}")))
    frames.append(em.span_event("root", _ROOT_SPAN, None, _span("plan", 800, 200)))
    frames.append(em.span_event("leaf-0", _C0_SPAN, _ROOT_SPAN, _span("chat", 400, 100)))
    frames.append(CostUsageEvent(**em.next("leaf-0"), data=_C0_SELF))
    frames.append(em.span_event("leaf-1", _C1_SPAN, _ROOT_SPAN, _span("chat", 200, 50)))
    frames.append(CostUsageEvent(**em.next("leaf-1"), data=_C1_SELF))
    frames.append(CostUsageEvent(**em.next("root"), data=_ROOT_SELF))
    # INVARIANT: the subtree roll-up is emitted before the Result (spec §8).
    frames.append(CostUsageEvent(**em.next("root"), data=_SUBTREE))
    frames.append(
        ResultEvent(**em.next("root"), data=ResultData(body="[mock] done", media_type="text/plain"))
    )
    frames.append(TerminatedEvent(**em.next("root"), data=TerminatedData(status="succeeded")))
    return frames


async def publish_mock_run(stream: EventPublisher, topic: str, url4: str) -> None:
    await stream.ensure_stream(topic)
    for event in build_run(topic, url4):
        await stream.publish(topic, event)
    # A publisher may defer its acknowledgements, and this function's only caller exits the
    # process right after it returns — without the barrier the mock run's frames could still
    # be in flight when the connection closes.
    await stream.flush()


def main() -> None:  # pragma: no cover - real NATS + event loop (INFRA rule, spec §11)
    import asyncio
    import os

    topic = os.environ[job_env.TOPIC]
    url4 = os.environ.get(job_env.EXPRESSION, "(gpt,claude)!'demo'")
    nats_url: str = os.environ.get(job_env.NATS_URL, job_env.DEFAULT_NATS_URL)
    asyncio.run(publish_mock_run(JetStreamPublisher(nats_url), topic, url4))


if __name__ == "__main__":  # pragma: no cover
    main()
