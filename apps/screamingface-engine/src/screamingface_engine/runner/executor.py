"""The run mode's `Executor` port implementation: drives one url4 run over the real engine
(`url4.dag.run`) and bridges its synchronous `url4.observe` callback events into the async
`url4.streaming.protocol` wire frames the run publishes over NATS.

This is the only module (besides `connector`) that may import the url4 ENGINE — the composition
root (`runner.main`) types its world factory against `World`/`WorldFactory` here without ever
importing the engine itself. `tests/unit/test_url4_executor.py` pins that pair over the whole
distribution, control plane included.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from screamingface_engine import job_env
from screamingface_engine.artifacts import ArtifactWriter
from screamingface_engine.runner.accounting import PRICING_VERSION, UNPRICED, accumulate
from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.summary import RunOutcome, RunSummary
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.io.layer import IOLayer
from url4.io.static import StaticIOLayer
from url4.observe import (
    Log,
    ModelResponse,
    NodeFinished,
    NodeStarted,
    ObservationEvent,
    RunStarted,
    Usage,
)
from url4.streaming.interfaces import Completed, ExecStep, Executor, SpanRef, TraceContext, Traced
from url4.streaming.protocol import (
    SEVERITY_NUMBER,
    CostUsageData,
    LogData,
    ResultData,
    Severity,
    SpanData,
    TokenUsage,
)
from url4.streaming.protocol.taxonomy import CostBreakdown

_logger = logging.getLogger(__name__)

BRIDGE_HIGH_WATER = "bridge.high_water"
BRIDGE_SOFT_CAP = "bridge.soft_cap"
"""Attribute keys for the bridge's closing diagnostic.

Named as one `bridge.*` family, exactly as `RunCacheCounters` names its `cache.*` keys, so a
reader finds the pair by prefix. The soft cap travels WITH the mark because the mark alone is
uninterpretable — 3000 is alarming against a cap of 1024 and impossible against 8192.
"""

EVENT_SIZE_ESTIMATE_BYTES = 512
"""The per-event cost the bridge's memory budget is divided by to get its hard cap.

Deliberately about DOUBLE the largest measured event (278 B, OME-906), so the real ceiling
stays under the budget rather than over it. `sys.getsizeof` per event on the hot path would
cost more than the bound is worth; the estimate only has to be the right order of magnitude.
"""


class BridgeOverflowError(RuntimeError):
    """Raised by `_Bridge.on_event` when the backlog still exceeds the cap derived from the
    bridge's memory budget after the eviction policy has run — eviction only removes a `Log`
    when one happens to be buffered, so a backlog of non-Log events grows unchecked to the
    budget cap.

    The message separates the two shapes a full buffer can take: a drain count above zero
    means ONE DAG burst outran the budget (the engine gathers over `deps` unbounded and emits
    each node's events before it awaits anything, so a wide fan-in lands in a single
    event-loop slice); a drain count of zero means the consumer never ran at all.
    """


class _Bridge:
    """A bounded async event queue between the engine's synchronous `url4.observe` callback
    and the async streaming loop draining it.

    Buffers up to `maxsize` events; beyond that, an incoming `Log` is dropped outright, while
    an incoming non-Log event instead evicts the oldest buffered `Log` to make room (or, if no
    `Log` is buffered, evicts nothing and the buffer grows toward the hard cap) — since a `Log`
    is the only event kind safe to lose without corrupting the run's span/cost accounting.
    Only past the hard cap does it give up and raise `BridgeOverflowError`.

    The HARD cap is not a count of events: it is `memory_budget // EVENT_SIZE_ESTIMATE_BYTES`,
    so an operator bounds what the backlog may COST in bytes, not how wide a DAG may be —
    the count-derived cap was a ceiling on DAG width (OME-906).
    """

    def __init__(
        self,
        maxsize: int,
        *,
        memory_budget: int = job_env.DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES,
    ) -> None:
        self._buf: deque[ObservationEvent] = deque()
        self._max = maxsize
        self._budget_bytes = memory_budget
        self._hard_cap = max(1, memory_budget // EVENT_SIZE_ESTIMATE_BYTES)
        self._dropped = 0
        self._high_water = 0
        self._drained = 0
        self._closed = False
        self._wake = asyncio.Event()

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def soft_cap(self) -> int:
        return self._max

    @property
    def high_water(self) -> int:
        """The deepest this backlog ever got.

        INVARIANT: a MARK, never a gauge — draining does not lower it. A figure that fell
        back with the queue would read as healthy on every run that recovered, which is
        every run an operator would still want to know about.
        """
        return self._high_water

    @property
    def drained(self) -> int:
        """How many events the consumer has taken off the buffer.

        INVARIANT: the honest signal for "is the consumer running at all?" — the overflow
        message keys on it to tell a wide-DAG burst (drained above zero) from a consumer
        that never ran (drained zero). A count that merely lagged would say "behind";
        only zero says "stuck".
        """
        return self._drained

    @property
    def backlogged(self) -> bool:
        """Whether the backlog ever passed the SOFT cap.

        The threshold worth reporting: below it the eviction policy never engaged, so there
        is nothing to say — and `_closing_logs` must stay silent when that is true.
        """
        return self._high_water > self._max

    def on_event(self, event: ObservationEvent) -> None:
        """Called synchronously by the engine for every observation event.

        Policy at the soft cap (`maxsize`): a `Log` is dropped outright (counted in
        `dropped`); anything else evicts the oldest buffered `Log` to make room, since a
        `Log` is the only event kind safe to lose without corrupting the run's span/cost
        accounting. Only once the backlog still exceeds the hard cap after that eviction does
        this raise `BridgeOverflowError`.
        """
        # INVARIANT: with the default budget the hard cap sits far above `_max`, giving the
        # buffer headroom past the soft cap before the budget binds — NOT a guarantee that a
        # Log is available to evict. A backlog with no buffered Log at all is exactly the
        # state that runs out that headroom and raises BridgeOverflowError. A budget below
        # `_max` events' worth makes the hard cap bind first; the policy stays correct, the
        # soft cap simply never gets to help.
        if len(self._buf) >= self._max:
            if isinstance(event, Log):
                self._dropped += 1
                return
            self._evict_oldest_log()
        if len(self._buf) >= self._hard_cap:
            # WHY keyed on `drained`: a consumer that HAS taken events is running, so a
            # full buffer is one producer burst wider than the budget — the DAG is the
            # driver. Zero drained events is the only shape where the consumer itself is
            # the suspect, and the message must say which of the two fired (OME-906).
            if self._drained:
                raise BridgeOverflowError(
                    f"event backlog exceeded the memory budget "
                    f"({self._budget_bytes:,} bytes ≈ {self._hard_cap:,} events; "
                    f"peak {self._high_water}, {self._dropped} Log(s) dropped, "
                    f"{self._drained:,} event(s) already drained) — one DAG burst wider "
                    f"than the budget: increase {job_env.BRIDGE_MEMORY_BUDGET_BYTES} "
                    "or narrow the DAG"
                )
            raise BridgeOverflowError(
                f"event backlog exceeded the memory budget "
                f"({self._budget_bytes:,} bytes ≈ {self._hard_cap:,} events; "
                f"peak {self._high_water}, {self._dropped} Log(s) dropped) and the "
                "consumer never drained one event — the consumer is stuck, not merely behind"
            )
        self._buf.append(event)
        if len(self._buf) > self._high_water:
            self._high_water = len(self._buf)
        self._wake.set()

    def _evict_oldest_log(self) -> None:
        for i, buffered in enumerate(self._buf):
            if isinstance(buffered, Log):
                del self._buf[i]
                self._dropped += 1
                return

    def close(self) -> None:
        self._closed = True
        self._wake.set()

    async def drain(self) -> AsyncIterator[ObservationEvent]:
        while True:
            if self._buf:
                self._drained += 1
                yield self._buf.popleft()
                continue
            if self._closed:
                return
            self._wake.clear()
            await self._wake.wait()


def _pricing_version(total: Decimal | None) -> str:
    """`PRICING_VERSION` when a total is known, `UNPRICED` otherwise.

    INVARIANT: the ONLY switch a consumer reads to decide dash-versus-figure. Degrade to `UNPRICED`,
    never to a zero that reads as "this was free".
    """
    return UNPRICED if total is None else PRICING_VERSION


def _token_usage(usage: _SpanUsage) -> TokenUsage:
    """The wire token counts for one span.

    AIDEV-NOTE: the wire's `TokenUsage` fields are non-optional ints, so a class the gateway did not
    report flattens to 0 here — "unknown" and "zero" are indistinguishable ON THE WIRE for tokens.
    That is tolerable because tokens do NOT enter the price under this pricing method: the amount is
    provider-authored, so an unknown cache class cannot make the cost wrong. If a rate-card method
    ever multiplies these counts, that stops being true and the wire type has to gain optionality
    first.
    """
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens or 0,
        cache_creation_tokens=usage.cache_creation_tokens or 0,
        reasoning_tokens=usage.reasoning_tokens or 0,
    )


@dataclass(frozen=True, slots=True)
class _SpanUsage:
    """One span's accumulated model accounting, folded from its `Usage` events.

    FEATURE: per-run cost reporting (OME-849). Replaced a positional 4-tuple: nine fields read as
    `usage[2]` is unreadable, and the tuple could not express "not reported".

    INVARIANT: an optional field is `None` when no call reported it — never zero. `cost_usd` `None`
    means this span is UNPRICED, which is a different claim from `Decimal("0")` ("the calls were
    genuinely free", e.g. every one served from cache).
    """

    provider: str
    model: str
    response_model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: Decimal | None


@dataclass
class _SpanState:
    """An in-flight span's accumulated fields, held between its `NodeStarted` and matching
    `NodeFinished` events so `_RunState._finish` can build the wire-protocol `SpanData`."""

    kind: str
    detail: str
    start: datetime
    parent_span_id: str | None
    usage: _SpanUsage | None = field(default=None)
    # INVARIANT: a LIST, accumulated — one span can make several model calls (the web-tools loop
    # is the normal case), and each round trip's reason is separately auditable.
    #
    # AIDEV-NOTE: empty here covers TWO cases that `_finish` deliberately collapses to one on the
    # wire — a node that called no model, and a call whose provider omitted `finish_reason`. They
    # are NOT distinguishable downstream. Nothing consumes the difference today; if something ever
    # needs it, count the folded events here rather than inferring it from this list.
    finish_reasons: list[str] = field(default_factory=list)
    refusal: str | None = field(default=None)
    # A span carries ONE cache outcome while a turn may be several gateway calls, so last-wins
    # (see `_fold_response`). Held as a pair and written as a pair: a status from one round trip
    # beside a reason from another would describe a call that never happened.
    cache_status: Literal["hit", "miss", "bypass"] | None = field(default=None)
    cache_reason: str | None = field(default=None)


class _RunState:
    """Accumulates one run's `url4.observe` events into wire-protocol span and cost frames.

    Tracks in-flight spans by `span_id` (opened on `NodeStarted`, closed on `NodeFinished`)
    and folds every `Usage` event into both the owning span's usage and the run-wide subtree
    totals returned by `build_subtree`.
    """

    def __init__(self) -> None:
        self.trace_id: str | None = None
        self.root_span_id: str | None = None
        self.spans: dict[str, _SpanState] = {}
        # Run-level, exactly like the subtree token sums beside it, and for the same reason: the
        # per-span outcome answers "what happened to this call", while the question an operator
        # asks is about the run. Published once at the end — see `Url4Executor.execute`.
        self.cache_counters = RunCacheCounters()
        self._sum_input = 0
        self._sum_output = 0
        # WHY these three are summed as plain ints while the SPAN-level equivalents poison through
        # `accumulate`: money and tokens have different escape hatches on the wire.
        #
        # A run whose price is unknowable says so — `pricing_version: "unpriced"` exists for it —
        # so poisoning the money total loses nothing. `TokenUsage`'s fields are non-optional ints
        # with no such spelling, so poisoning a token class cannot publish "unknown"; it publishes
        # ZERO, which is a false claim rather than an absent one, and it discards the real counts
        # the reporting calls did supply.
        #
        # INVARIANT (OME-869): at RUN level an unreported class contributes nothing and never
        # erases what its siblings reported. The mixed-provider case is the one that matters — one
        # model reports cache reads and no reasoning, another the reverse — where poisoning would
        # zero BOTH real figures to encode an uncertainty the frame cannot carry anyway.
        #
        # AIDEV-NOTE: do NOT "make this consistent" with the span-level `accumulate` calls in
        # `_fold_usage`. The asymmetry is the decision. A span is one model, so mixed reporting is
        # unlikely there; a run spans many, so it is the normal case. If `TokenUsage` ever gains
        # optional counts, revisit this — then poisoning could finally say what it means.
        self._sum_cache_read = 0
        self._sum_cache_creation = 0
        self._sum_reasoning = 0
        self._providers_models: set[tuple[str, str]] = set()
        # `None` until the first priced call: a run that made no model call at all stays unpriced,
        # which is the shape it published before cost reporting existed.
        self._subtree_cost: Decimal | None = None
        self._subtree_unpriced = False

    def map(self, event: ObservationEvent) -> list[Traced]:
        """Fold one observation event into run state, returning the wire frames it produces.

        Dispatches on event type: `RunStarted` records the trace/root ids (no frame);
        `NodeStarted` opens a span (no frame); `Log` maps straight to a `Traced` log frame;
        `Usage` folds token counts into the owning span and the run totals (no frame);
        `NodeFinished` closes the span and returns its `SpanData` frame, plus a `CostUsageData`
        frame when the span carried usage. Any other event type produces nothing.
        """
        if isinstance(event, RunStarted):
            self.trace_id = event.trace_id
            self.root_span_id = event.root_span_id
        elif isinstance(event, NodeStarted):
            self.spans[event.span_id] = _SpanState(
                event.node_kind, event.detail, datetime.now(UTC), event.parent_span_id
            )
        elif isinstance(event, Log):
            # The engine attributes each log line to the span that emitted it; carry that through
            # so a consumer can tell WHICH node logged. A span-less line (logged outside any
            # node) legitimately has none and falls back to the run root.
            return [Traced(payload=_log_frame(event), span=self._span_ref(event.span_id))]
        elif isinstance(event, Usage):
            self._fold_usage(event)
        elif isinstance(event, ModelResponse):
            self._fold_response(event)
        elif isinstance(event, NodeFinished):
            return self._finish(event)
        return []

    def _span_ref(self, span_id: str | None) -> SpanRef | None:
        """A `SpanRef` for a live span, or None when the frame belongs to the run itself.

        A span id the run has never seen (or has already finished) resolves to None rather than
        being fabricated: publishing under an id no span frame ever carried would be worse than
        falling back to the root, because a consumer cannot tell the two apart.
        """
        if span_id is None:
            return None
        span = self.spans.get(span_id)
        if span is None:
            return None
        return SpanRef(span_id, span.parent_span_id)

    def _fold_response(self, event: ModelResponse) -> None:
        """Accumulate one model round trip's outcome onto the span that made the call.

        Mirrors `_fold_usage`'s guard and its accumulate-don't-assign rule: an event for a span
        this run never opened is dropped rather than fabricating one, and several calls on the
        same span each keep their own entry.
        """
        # Counted BEFORE the span guard, and that difference is deliberate. A span frame must not
        # be fabricated for an id this run never opened — a consumer cannot tell an invented span
        # from a real one. A run TOTAL has no such problem: the round trip happened and it either
        # cost or saved money, so dropping it would under-report the run's own summary.
        self.cache_counters.record(event.cache_status, event.cache_reason)
        span = self.spans.get(event.span_id) if event.span_id is not None else None
        if span is None:
            return
        if event.finish_reason is not None:
            span.finish_reasons.append(event.finish_reason)
        if event.refusal is not None:
            # Last refusal wins: for a multi-call turn the final one is the turn's outcome.
            span.refusal = event.refusal
        if event.cache_status is not None:
            # Same rule, and guarded on the STATUS rather than on the event: a later round trip
            # that reported no outcome at all — an older gateway, a non-cache error path — must
            # leave the earlier one standing rather than blanking it, because "nothing reported"
            # is not "no cache involved".
            span.cache_status = event.cache_status
            span.cache_reason = event.cache_reason

    def _fold_usage(self, event: Usage) -> None:
        self._sum_input += event.input_tokens
        self._sum_output += event.output_tokens
        self._sum_cache_read += event.cache_read_tokens or 0
        self._sum_cache_creation += event.cache_creation_tokens or 0
        self._sum_reasoning += event.reasoning_tokens or 0
        self._providers_models.add((event.provider, event.model))
        # INVARIANT: the run total latches UNPRICED on the first call it cannot price, and never
        # unlatches. A grand total that silently omits a step while presenting itself as a total is
        # worse than no total — the consumer cannot tell a complete sum from a lossy one. Counted
        # here rather than in `_finish` for the same reason the token sums are: a round trip on a
        # span this run never opened still spent money.
        if event.cost_usd is None:
            self._subtree_unpriced = True
        elif self._subtree_cost is None:
            self._subtree_cost = event.cost_usd
        else:
            self._subtree_cost += event.cost_usd
        span = self.spans.get(event.span_id) if event.span_id is not None else None
        if span is None:
            return
        # INVARIANT: a span ACCUMULATES its usage, exactly as the subtree totals above do — one
        # node can emit several `Usage` events. The web-tools tool loop is the normal case: every
        # aigateway round trip reports its own usage against the SAME span, so assigning here
        # (as this once did) kept only the final round trip and silently dropped every earlier
        # one from both the span frame and its `scope="self"` cost frame, while `subtree` stayed
        # correct — per-node cost that under-reports against a run total that does not.
        prior = span.usage
        if prior is None:
            # Seeding rather than accumulating from zero is what lets a genuine `None` in the FIRST
            # round trip poison the class, instead of being mistaken for "nothing seen yet".
            span.usage = _SpanUsage(
                provider=event.provider,
                model=event.model,
                response_model=event.response_model,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cache_read_tokens=event.cache_read_tokens,
                cache_creation_tokens=event.cache_creation_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cost_usd=event.cost_usd,
            )
            return
        span.usage = _SpanUsage(
            provider=event.provider,
            model=event.model,
            # Last reported wins, and an unreported one leaves the earlier standing: a later round
            # trip that named no served model must not blank one an earlier trip did name.
            response_model=event.response_model or prior.response_model,
            input_tokens=prior.input_tokens + event.input_tokens,
            output_tokens=prior.output_tokens + event.output_tokens,
            cache_read_tokens=accumulate(prior.cache_read_tokens, event.cache_read_tokens),
            cache_creation_tokens=accumulate(
                prior.cache_creation_tokens, event.cache_creation_tokens
            ),
            reasoning_tokens=accumulate(prior.reasoning_tokens, event.reasoning_tokens),
            cost_usd=accumulate(prior.cost_usd, event.cost_usd),
        )

    def _finish(self, event: NodeFinished) -> list[Traced]:
        span = self.spans.pop(event.span_id, None)
        if span is None:
            span = _SpanState("", "", datetime.now(UTC), None)
        kind, detail, start, usage, parent_span_id = (
            span.kind,
            span.detail,
            span.start,
            span.usage,
            span.parent_span_id,
        )
        span_data = SpanData(
            name=detail or kind,
            operation=kind,
            provider=usage.provider if usage else None,
            request_model=usage.model if usage else None,
            # AIDEV-NOTE: this deliberately still ECHOES the requested model when the provider named
            # no served one, unlike `url4.observe.Usage.response_model`, whose invariant forbids
            # the echo. Changing `SpanData`'s long-standing behaviour is a wire change for every
            # existing run and belongs to its own unit of work, not to OME-849.
            response_model=(usage.response_model or usage.model) if usage else None,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            # Empty -> None so the attribute is simply ABSENT rather than an empty list, matching
            # how OTel treats `gen_ai.*` attributes. This collapses "no model call" and "a call
            # that reported no reason" into the same wire shape — intended, not an oversight.
            finish_reasons=span.finish_reasons or None,
            refusal=span.refusal,
            # Absent for the many nodes that call no gateway at all. A default of "bypass" would
            # read as "the cache refused this call" — a claim nobody made.
            cache_status=span.cache_status,
            cache_reason=span.cache_reason,
            start=start,
            end=datetime.now(UTC),
            status="ok" if event.status == "ok" else "error",
        )
        frames: list[Traced] = [
            Traced(payload=span_data, span=SpanRef(event.span_id, parent_span_id))
        ]
        if usage is not None:
            frames.append(
                Traced(
                    payload=CostUsageData(
                        scope="self",
                        provider=usage.provider,
                        model=usage.model,
                        pricing_version=_pricing_version(usage.cost_usd),
                        usage=_token_usage(usage),
                        # INVARIANT: an unpriced span publishes total 0 with the `unpriced` version,
                        # exactly as it did before cost reporting existed — the consumer reads the
                        # version, not the number, to decide whether to show a figure at all.
                        cost=CostBreakdown(total_usd=usage.cost_usd or Decimal("0")),
                    ),
                    # INVARIANT: the self-scoped cost carries the SAME span as the span frame it
                    # accompanies. Without it every `scope="self"` frame in a run is published
                    # under the run root and is therefore indistinguishable from every other —
                    # nobody can tell which node spent the tokens, and self cannot be reconciled
                    # against subtree per node, which is the whole point of emitting both.
                    span=SpanRef(event.span_id, parent_span_id),
                )
            )
        return frames

    def build_result(
        self,
        result_str: str,
        *,
        inline_cap: int,
        hard_cap: int,
        store: ArtifactWriter | None,
    ) -> ResultData:
        """Build the final `ResultData`: inline, spilled whole, or refused — never cut.

        FEATURE: deliver large results in full instead of cutting them off at 1 MiB
        (OME-892). Three-way fork by UTF-8 size, HARD CAP FIRST: (1) over `hard_cap` —
        or over `inline_cap` with no store to spill into — raise `result_too_large`
        naming both byte counts, which the lifecycle turns into a failed terminal event;
        (2) ≤ `inline_cap` → the body rides the result frame exactly as before OME-892;
        (3) otherwise the COMPLETE body is written to the content-addressed `store` and
        the frame carries only the claim ticket (`ResultArtifact`).

        WHY the hard cap is checked first: it is absolute. If the inline check ran first,
        inverted knobs (inline_cap > hard_cap) would let an over-hard-cap body sail into
        one WS frame — bypassing the ceiling and resurrecting the close-1009
        `websocket_disconnected` failure the client's frame bound exists to prevent.

        The body is encoded ONCE — the same bytes that are measured are the bytes written
        (`write_bytes`), so a gigabyte-scale result never pays a second encoding copy.
        Blocking work (hashing, disk write) is the CALLER's problem: `execute` runs this
        whole method in a worker thread so the event loop pumping heartbeats never stalls.

        INVARIANT: no branch emits a truncated body — the truncate-and-still-succeed
        path of GitHub #642 is unrepresentable here.
        """
        encoded = result_str.encode("utf-8")
        allowed = hard_cap if store is not None else min(inline_cap, hard_cap)
        if len(encoded) > allowed:
            raise ResolutionError(
                f"result is {len(encoded)} bytes, cap is {allowed} bytes",
                code="result_too_large",
                permanent=True,
            )
        if len(encoded) <= inline_cap:
            return ResultData(body=result_str, media_type=None)
        assert store is not None  # over inline yet allowed ⇒ a store existed above
        return ResultData(media_type=None, artifact=store.write_bytes(encoded))

    def build_subtree(self) -> CostUsageData:
        provider, model = self._subtree_provider_model()
        # INVARIANT: priced only when EVERY observed call was priced. `_subtree_unpriced` latches
        # on the first one that was not; a run with no model call at all has `_subtree_cost is
        # None` and stays unpriced — the shape it published before cost reporting existed.
        total = None if self._subtree_unpriced else self._subtree_cost
        return CostUsageData(
            scope="subtree",
            provider=provider,
            model=model,
            pricing_version=_pricing_version(total),
            usage=TokenUsage(
                input_tokens=self._sum_input,
                output_tokens=self._sum_output,
                cache_read_tokens=self._sum_cache_read,
                cache_creation_tokens=self._sum_cache_creation,
                reasoning_tokens=self._sum_reasoning,
            ),
            cost=CostBreakdown(total_usd=total or Decimal("0")),
        )

    def _subtree_provider_model(self) -> tuple[str, str]:
        if not self._providers_models:
            return "none", "none"
        if len(self._providers_models) == 1:
            return next(iter(self._providers_models))
        return "mixed", "mixed"


def _closing_logs(bridge: _Bridge, counters: RunCacheCounters) -> list[Traced]:
    """The log frames a run emits about ITSELF, after its last span and before `Completed`.

    All are statements about the whole run rather than about any node, so all carry
    ``span=None`` and none can be made until every event has been folded. Extracted from
    `Url4Executor.execute` so the generator stays a straight line — the run loop's shape is what
    a reader checks for correctness, and a growing tail of end-of-run bookkeeping obscures it.

    Args:
        bridge: The run's event bridge, for its dropped count and its high-water mark.
        counters: The run's cache tallies.

    Returns:
        Only the frames that have something to say. A run that dropped nothing, never
        backlogged, and touched no cache — the overwhelming majority, since most expressions
        call no gateway at all — produces none, rather than three lines reporting that
        nothing happened.
    """
    frames: list[Traced] = []
    if bridge.dropped:
        frames.append(
            Traced(
                payload=LogData.at(
                    "WARN", f"dropped {bridge.dropped} log event(s) (telemetry overflow)"
                ),
                span=None,
            )
        )
    # FEATURE: bridge high-water reporting (OME-906). Emitted only PAST the soft cap: a run
    # that never queued has nothing to report, and an always-on line would bury the signal in
    # the runs that are fine. The pair answers "how close did this run come?" — which the
    # overflow error can only answer for runs that already failed.
    #
    # WHY not Prometheus: same two reasons as `RunCacheCounters` — the run mode is a one-shot
    # Job with no scrape endpoint, and `check_layering.py` forbids `runner.*` to import
    # `screamingface_engine.metrics`. The run's own telemetry stream is the only channel.
    if bridge.backlogged:
        frames.append(
            Traced(
                payload=LogData.at(
                    "WARN",
                    f"event backlog peaked at {bridge.high_water} events "
                    f"(soft cap {bridge.soft_cap})",
                    {
                        BRIDGE_HIGH_WATER: bridge.high_water,
                        BRIDGE_SOFT_CAP: bridge.soft_cap,
                    },
                ),
                span=None,
            )
        )
    if counters.observed:
        # The run's cache summary (spec §7): hits, misses and bypasses BY REASON, which is what
        # turns "I asked for no caching and something still cached" into an answerable question.
        frames.append(
            Traced(
                payload=LogData.at("INFO", counters.summary_body(), counters.attributes()),
                span=None,
            )
        )
    return frames


def _log_frame(event: Log) -> LogData:
    # The engine's severity is a free string; anything the protocol does not name maps to INFO.
    severity = cast(Severity, event.severity.upper())
    return LogData.at(severity if severity in SEVERITY_NUMBER else "INFO", event.body)


World = tuple[IOLayer, Callable[[], Awaitable[None]] | None]
"""A resolved world: its io layer plus the teardown that owns whatever it allocated.

Exported so the composition root can type its factory WITHOUT importing the engine — only
this module and `connector` may (pinned by
``test_only_url4_executor_module_imports_url4``).
"""

WorldFactory = Callable[[], Awaitable[World]]


class Url4Executor(Executor):
    """The `Executor` port implementation that drives one url4 run against the real engine.

    Resolves its `World` (an `IOLayer` plus teardown) lazily on first `execute`, runs
    `url4.dag.run` against it with a `_Bridge` as observer, and maps the resulting
    `url4.observe` events through `_RunState` into the `ExecStep` frames it yields.
    """

    def __init__(
        self,
        io: IOLayer | None = None,
        *,
        queue_cap: int = 1024,
        result_cap: int = job_env.DEFAULT_RESULT_INLINE_CAP_BYTES,
        hard_cap: int = job_env.DEFAULT_RESULT_HARD_CAP_BYTES,
        memory_budget: int = job_env.DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES,
        artifact_store: ArtifactWriter | None = None,
        world_aclose: Callable[[], Awaitable[None]] | None = None,
        world_factory: WorldFactory | None = None,
        io_wrap: Callable[[IOLayer], IOLayer] | None = None,
        io_concurrency: int | None = None,
    ) -> None:
        self._io = io
        self._queue_cap = queue_cap
        # WHY: `result_cap` is now the INLINE threshold (biggest body that rides the
        # result frame), not a truncation point; `hard_cap` bounds the spill path. The
        # result already sits in this process's memory when checked (string + encoded
        # copy ≈ 2-3× its size), so operators size hard_cap to pod RAM, not disk.
        self._result_cap = result_cap
        self._hard_cap = hard_cap
        # WHY bytes, not a count: the bridge's hard cap is this budget divided by
        # `EVENT_SIZE_ESTIMATE_BYTES`, so an operator bounds what the backlog may COST —
        # a count cap was a ceiling on DAG width (OME-906).
        self._memory_budget = memory_budget
        self._artifact_store = artifact_store
        self._world_aclose = world_aclose
        self._world_factory = world_factory
        # FEATURE (OME-908): the run's downstream admission policy, injected as data.
        # `io_wrap` is the LOCAL shape — one wrapper binding this run into the process's
        # shared `FairShareGate` — and when set it REPLACES URL4's per-run bound, so the
        # `url4_run` call below passes `concurrency=None` explicitly (an opt-out; leaving
        # the kwarg off would stack `BoundedIOLayer(32)` under the gate and re-create the
        # static cap the gate exists to replace). `io_concurrency` is the DEPLOYED shape —
        # a static per-run budget a one-shot Job enforces through that same layer. Neither
        # set ⇒ the kwarg is omitted entirely and URL4's own default applies, which keeps
        # an unconfigured run byte-identical to a pre-OME-908 one.
        self._io_wrap = io_wrap
        self._io_concurrency = io_concurrency
        self._io_wrapped = False
        # FEATURE (OME-1069): the most recent run's process-level summary, recorded in
        # `execute` and read back by the composition root for its terminal/summary log lines.
        # `None` until a run has executed (or when the caller closed the generator early).
        self._last_summary: RunSummary | None = None
        # Derived ONCE, at construction, from the injected policy: which `concurrency` (if
        # any) the `url4_run` call states. See the policy comment above for why gate-mode
        # must say `None` explicitly while an unconfigured run says nothing at all.
        self._run_kwargs: dict[str, Any] = (
            {"concurrency": None}
            if io_wrap is not None
            else ({} if io_concurrency is None else {"concurrency": io_concurrency})
        )

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        """Run `url4` to completion, yielding `ExecStep` frames as observation events arrive.

        The engine runs in a separate task while this generator drains its events through the
        `_Bridge`, so a slow consumer never blocks the engine's synchronous observer callback
        (see `_run_steps`). On exit — including early return by the caller not exhausting the
        iterator — the world is always closed via `_aclose_world`, even when the run failed
        or was cancelled.
        """
        # INVARIANT: the world is resolved HERE, not in the composition root. Anything raised
        # before `lifecycle.run` publishes its first frame is invisible — no NATS connection,
        # no `ensure_stream`, so an attached client sees heartbeats forever and never a
        # Terminated. Resolving inside `execute` puts config and connect failures inside
        # `run`'s try, where they become Terminated(status="failed") with a real error code.
        await self._resolve_world()
        bridge = _Bridge(self._queue_cap, memory_budget=self._memory_budget)
        state = _RunState()
        started = time.monotonic()
        try:
            async for step in self._run_steps(url4, trace, bridge, state, started):
                yield step
        except asyncio.CancelledError:
            # The run was stopped (deadline, an external stop, the caller's cancellation).
            # `lifecycle.run` publishes Terminated(stopped) and re-raises; the summary
            # records the outcome so the composition root can log it.
            self._record_summary("stopped", trace, started, bridge, state)
            raise
        except Exception as exc:
            # A failed run states no cost and no cache counts: neither is exact, and a
            # partial figure would read as a complete one. The error code/type follow the
            # stream's own `_error_info` vocabulary (code, or None when the exception
            # carries none).
            self._record_summary("failed", trace, started, bridge, state, error=exc)
            raise
        finally:
            await self._aclose_world()

    async def _run_steps(
        self,
        url4: str,
        trace: TraceContext | None,
        bridge: _Bridge,
        state: _RunState,
        started: float,
    ) -> AsyncIterator[ExecStep]:
        """Drive the engine task and yield its wire frames, ending with `Completed`.

        The engine runs in a separate task (`_drive`) while this generator drains its events
        through the `_Bridge`, so a slow consumer never blocks the engine's synchronous
        observer callback. On exit — including early return by the caller not exhausting the
        iterator — any still-running driving task is cancelled and awaited, and an already
        finished task's exception (if not itself a cancellation) is retrieved so it isn't
        reported as "never retrieved".
        """

        async def _drive() -> str:
            try:
                if trace is not None:
                    return await url4_run(
                        url4,
                        self._io,
                        observer=bridge,
                        trace_id=trace.trace_id,
                        root_span_id=trace.root_span_id,
                        **self._run_kwargs,
                    )
                return await url4_run(url4, self._io, observer=bridge, **self._run_kwargs)
            finally:
                bridge.close()

        task = asyncio.ensure_future(_drive())
        try:
            async for ev in bridge.drain():
                for frame in state.map(ev):
                    yield frame
            result_str = await task
            for frame in _closing_logs(bridge, state.cache_counters):
                yield frame
            # WHY to_thread: for a spilled result this hashes and writes up to hard_cap
            # bytes — synchronous disk work that would otherwise stall the very loop that
            # pumps heartbeats, letting a client declare a FINISHING run dead.
            result = await asyncio.to_thread(
                state.build_result,
                result_str,
                inline_cap=self._result_cap,
                hard_cap=self._hard_cap,
                store=self._artifact_store,
            )
            subtree = state.build_subtree()
            # FEATURE (OME-1069): recorded BEFORE the Completed yield, because
            # `lifecycle.run` breaks out of its `async for` on Completed and never resumes
            # this generator — code after the yield would never run. The summary is the
            # operator's one-stop answer in a Job's logs; exact-only, like the stream's
            # own cost frames.
            self._record_summary("succeeded", trace, started, bridge, state, subtree=subtree)
            yield Completed(result=result, subtree_cost=subtree)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            elif not task.cancelled():
                task.exception()

    def _record_summary(
        self,
        outcome: RunOutcome,
        trace: TraceContext | None,
        started: float,
        bridge: _Bridge,
        state: _RunState,
        *,
        subtree: CostUsageData | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Record the run's process-level summary (OME-1069).

        Exact-only, like the rest of the run's accounting: cost and cache counters are
        stated only for a completed run — a failed run's figures are partial and must not
        read as exact. The error code/type follow the stream's own `_error_info`
        vocabulary.
        """

        code = getattr(error, "code", None) if error is not None else None
        self._last_summary = RunSummary(
            outcome=outcome,
            trace_id=trace.trace_id if trace is not None else None,
            error_code=code if isinstance(code, str) else None,
            error_type=type(error).__name__ if error is not None else None,
            duration_s=time.monotonic() - started,
            cost_usd=subtree.cost.total_usd if subtree is not None else None,
            pricing_version=subtree.pricing_version if subtree is not None else None,
            cache_attributes=state.cache_counters.attributes() if subtree is not None else None,
            dropped_logs=bridge.dropped,
            high_water=bridge.high_water,
        )

    def last_summary(self) -> RunSummary | None:
        """The most recent run's process-level summary, or None if no run executed.

        FEATURE (OME-1069): read by the composition root after `lifecycle.run` returns to
        log the run's terminal outcome and summary. `None` covers both "never executed"
        and "the caller closed the generator before it completed" — the two shapes a
        caller cannot tell apart, and neither has a summary to state.
        """

        return self._last_summary

    async def _resolve_world(self) -> None:
        """Build the world on first execute. Idempotent; a failure leaves nothing to close.

        The factory owns cleanup of anything it allocated before failing, so there is no
        half-built world to tear down here.
        """
        if self._io is None and self._world_factory is not None:
            self._io, self._world_aclose = await self._world_factory()
        # FEATURE (OME-908): the admission wrapper binds ONCE, to whatever io this run
        # uses — the resolved world or a directly injected test io — and a second
        # `execute` on the same executor must not wrap the wrapper.
        if self._io_wrap is not None and self._io is not None and not self._io_wrapped:
            self._io = self._io_wrap(self._io)
            self._io_wrapped = True

    async def _aclose_world(self) -> None:
        if self._world_aclose is None:
            return
        try:
            await self._world_aclose()
        except Exception:  # noqa: BLE001 - teardown failure must not mask the run's real outcome
            _logger.warning("aigateway world teardown failed", exc_info=True)


def deny_by_default_world() -> IOLayer:
    return StaticIOLayer()


__all__ = ["Url4Executor", "deny_by_default_world"]
