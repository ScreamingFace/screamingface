"""What the gateway's response cache did across ONE run — hits, misses, and bypasses by reason
(spec §7 / D7, plan Batch 8).

**WHY counting is not optional.** Caching fails silently in both directions. A hit costs nothing
upstream, so nobody notices the savings; a bypass costs a hit, and the request that caused it
succeeded, so nobody notices the loss either. Per-span `cache_status` answers "what happened to
this call"; only a run-level total answers the question an operator actually asks — *did this run
use the cache, and if not, why not?* — without correlating every span by hand.

**Bypasses BY REASON is the load-bearing one.** The gateway's vocabulary distinguishes
`opted_out` (url4 asked for no cache, and got none — working as designed) from
`unsupported_control` (url4 sent a control key the gateway's closed grammar does not know, and
silently lost EVERY hit — a defect that raises nothing anywhere). Collapsing them into one
"bypasses" number would erase exactly the distinction this telemetry exists to surface.

WHY THIS IS NOT PROMETHEUS. Two reasons, and either alone would settle it:

1. The run mode is a one-shot Job. It has no scrape endpoint and exits when the run does, so a
   counter incremented there is a counter nobody ever reads.
2. `.claude/scripts/check_layering.py` forbids `screamingface_engine.runner.*` from importing
   `screamingface_engine.metrics` at all — the run mode must not load the serving half.

The run's own telemetry stream is the only channel that exists, and it is also the right one: the
question is about one run, and the answer arrives beside the spans it explains.

INVARIANT — **no counter is labelled by cache key, prompt or credential** (spec §7).
Enforced structurally rather than by review: :meth:`RunCacheCounters.record` accepts
a status and a reason and nothing else, so there is no slot a key could occupy. The
gateway's entry key IS parsed, one seam upstream
(:class:`screamingface_engine.world.cache_readback.CacheOutcome`), and deliberately
stops there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Literal

from screamingface_engine.world.accounting import AMOUNT_PRECISION
from screamingface_engine.world.cache_readback import CacheStatus

SavedCostProvenance = Literal["reported", "archive_matched"]
"""How a saved-cost amount was established.

Deliberately spelled again rather than imported from `url4.observe`: only the runner's adapter
modules may import the url4 engine (pinned by `test_only_engine_extensions_import_url4`), and
this counter is not one of them. It mirrors `CacheStatus` beside it — the same literal the wire
type uses, defined at the engine boundary so no url4 import is needed. Change both together.
"""

CACHE_HITS = "cache.hits"
CACHE_MISSES = "cache.misses"
CACHE_BYPASSES = "cache.bypasses"
SAVED_COST_USD = "cache.saved_cost_usd"
SAVED_COST_ARCHIVE_USD = "cache.saved_cost_archive_usd"
SAVED_COST_REPORTED_HITS = "cache.saved_cost.reported_hits"
SAVED_COST_ARCHIVE_HITS = "cache.saved_cost.archive_hits"
SAVED_COST_UNPRICED_HITS = "cache.saved_cost.unpriced_hits"
"""The five saved-cost attributes (PRD §3.5 / ans:Q2).

`cache.saved_cost_usd` holds provider-authored (`reported`) money ONLY;
`cache.saved_cost_archive_usd` holds `archive_matched` money ONLY. There is NO combined key and
no third accumulator: the two provenances make different claims and a single figure would erase
the difference (PRD S7/M8). Both totals are absent rather than `0` when the run had no hits of
that provenance, because "no evidence" and "saved nothing" are different answers.
"""
BYPASS_REASON_PREFIX = "cache.bypass."
"""Namespace for the per-reason breakdown, so `cache.bypasses` and its parts read as one family
and a consumer can find the breakdown by prefix without knowing the gateway's vocabulary."""

UNSTATED_REASON = "unstated"
"""The bucket for a bypass that named no reason.

Its own bucket rather than being dropped: the breakdown must always sum to `cache.bypasses`, and
a reader who finds it does not — because some counts silently went nowhere — cannot trust either
number. Spelled without a space so it is usable as an attribute-key suffix; the equivalent notion
for a POLICY renders as :data:`screamingface_engine.notices.NOT_STATED`, which is prose, not a key.
"""

OVERFLOW_REASON = "other"
REASON_BUCKET_CAP = 16
"""Ceiling on distinct reason buckets, past which reasons collapse into
:data:`OVERFLOW_REASON` — at most ``REASON_BUCKET_CAP + 1`` buckets in all.

The same cardinality doctrine `screamingface_engine.metrics._route_label` applies to
a Prometheus label, for the same reason: the reason is an UPSTREAM FREE STRING,
carried verbatim on purpose, and a gateway that ever embeds a request id in one
would otherwise mint a new attribute per call. The cap costs nothing in practice —
the gateway's actual vocabulary is a handful of tokens — and it collapses rather
than drops, so the breakdown still sums to the total it belongs to.
"""

_COUNTED_BYPASS: CacheStatus = "bypass"


def _accumulated(total: Decimal | None, amount: Decimal) -> Decimal:
    """``amount`` added to ``total``, an absent total meaning this is the first contribution.

    WHY not `(total or 0) + amount`: a total of `Decimal("0")` is falsy, and collapsing it into
    the absent case would be harmless here only by luck. `None` and zero are different claims
    everywhere else in this module, so they stay different here too.

    WHY the local context: `Decimal.__add__` rounds to the AMBIENT precision, 28 digits by
    default, while `avoided_usd_from_aigw` converts each amount at `AMOUNT_PRECISION`. Adding
    under the smaller context would round a value that was deliberately preserved one step
    earlier — and silently, since `Decimal` signals inexactness only if the caller asks.

    WHY the precision is DERIVED rather than fixed at `AMOUNT_PRECISION`: that constant sizes ONE
    amount at the producer's published bound (18 integer + 33 fractional digits = 51 significant
    digits, plus 2 of headroom). A SUM of N such amounts needs `51 + ceil(log10(N))`, so a fixed
    53 rounds the total once N reaches 1000 — a running total can require more digits than any
    single contribution to it, and no constant can bound a sum with no bound on its length.
    """
    if total is None:
        return amount
    with localcontext() as ctx:
        ctx.prec = max(AMOUNT_PRECISION, _exact_sum_precision(total, amount))
        return total + amount


def _exact_sum_precision(total: Decimal, amount: Decimal) -> int:
    """Significant digits enough that `total + amount` rounds nothing away.

    The figure a sum needs is set by the EXPONENT SPAN of its operands, not by their digit counts:
    it must reach from the most significant place either operand occupies — plus one, for a carry
    out of the top — down to the least significant place either one occupies.

    INVARIANT: total. A non-finite operand has no exponent to reason about and falls back to
    `AMOUNT_PRECISION`; it cannot reach here through any live path (`ModelResponse` and
    `_CANONICAL_AMOUNT` both reject non-finite amounts at the seam) and must not be able to turn
    accounting into an exception if one ever does. The provider call is long paid for by then.
    """
    low, high = total.as_tuple().exponent, amount.as_tuple().exponent
    if not isinstance(low, int) or not isinstance(high, int):
        return AMOUNT_PRECISION
    most_significant = max(total.adjusted(), amount.adjusted()) + 1
    return most_significant - min(low, high) + 1


@dataclass(slots=True)
class SavedCostTotals:
    """Avoided money, in one accumulator per provenance — the whole never-mix rule, in one place.

    WHY a type of its own rather than two fields wherever saved cost is tallied: the rule that
    routes an amount to its provenance and refuses to combine the two (PRD S5/S7) is load-bearing
    at BOTH scopes — `RunCacheCounters` extends this for the run, and `_SpanState` holds one for
    the span. Two hand-written copies of that routing is two places for it to drift.

    AIDEV-NOTE: extended rather than composed by `RunCacheCounters` deliberately — the field
    names below are the run counter's own published names, and `test_the_counter_carries_exactly
    _two_saved_cost_accumulators` reads them off `dataclasses.fields(RunCacheCounters)`.
    """

    # FEATURE: saved cost (ans:Q2). `None` until the first priceable hit of that provenance;
    # NEVER defaulted to zero, because a zero total would read as "the cache saved nothing" when
    # the honest answer is "no hit of this kind was observed". The two totals are separate
    # accumulators by construction — no code path adds them.
    saved_cost_usd: Decimal | None = None
    saved_cost_archive_usd: Decimal | None = None

    def add_saved_cost(
        self, amount_usd: Decimal | None, provenance: SavedCostProvenance | None
    ) -> SavedCostProvenance | None:
        """Accumulate one cache HIT's avoided cost under its own provenance.

        INVARIANT: ACCUMULATES, never assigns. Money is additive, so a scope that sees several
        hits — a tool-calling turn is several round trips against one span (PRD §4.1) — must
        report their sum. Assigning would publish one hit's amount as if it were the scope's.

        Returns the total the amount landed in, or `None` when it landed in neither: no amount,
        or a provenance this engine cannot price. The caller uses that to keep its own coverage
        counts without re-deciding the routing.
        """
        if amount_usd is not None:
            if provenance == "reported":
                self.saved_cost_usd = _accumulated(self.saved_cost_usd, amount_usd)
                return provenance
            if provenance == "archive_matched":
                self.saved_cost_archive_usd = _accumulated(self.saved_cost_archive_usd, amount_usd)
                return provenance
        return None


@dataclass(slots=True)
class RunCacheCounters(SavedCostTotals):
    """One run's cache tallies. Plain integers, lifted onto the wire by the executor.

    Not a `prometheus_client` object for the layering reason in the module docstring, and not one
    even in spirit: a counter here is scoped to a run and dies with it, which is what makes it
    answerable without any label identifying WHICH run.
    """

    hits: int = 0
    misses: int = 0
    bypasses: int = 0
    # Coverage counts, one per outcome. They make each partial total auditable (PRD §3.9):
    # `reported`/`archive_matched` count the priced hits behind their total, and `unpriced_hits`
    # counts hits whose stored cost this engine could not price (no reference, unknown unit).
    reported_hits: int = 0
    archive_hits: int = 0
    unpriced_hits: int = 0
    _bypass_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def observed(self) -> bool:
        """Whether this run saw any cache outcome at all.

        The gate the executor publishes on. Most runs call no gateway — a static expression, a
        reduce over already-fetched leaves — and an older gateway reports nothing even when one
        is called. Emitting "0 hit, 0 miss, 0 bypass" for those would put a line on every run's
        stream that says only that the feature exists, which trains a reader to skip the line on
        the runs where it says something.
        """
        return bool(self.hits or self.misses or self.bypasses)

    @property
    def bypass_reasons(self) -> Mapping[str, int]:
        """The per-reason breakdown, read-only. Always sums to :attr:`bypasses`."""
        return self._bypass_reasons

    @property
    def saved_cost_observed(self) -> bool:
        """Whether this run saw any cache hit at all — the gate for publishing saved cost.

        Most runs never touch the cache, and emitting a saved-cost block of zeroes on every run
        would put the same three-zero line on the runs where it says nothing. A hit whose cost
        could not be priced still counts: it is coverage the reader needs, not silence.
        """
        return bool(self.reported_hits or self.archive_hits or self.unpriced_hits)

    def record_saved_cost(
        self, amount_usd: Decimal | None, provenance: SavedCostProvenance | None
    ) -> None:
        """Tally one cache HIT's avoided cost, under its own provenance.

        Call this only for a hit; a miss or a bypass avoided nothing. `provenance` decides the
        accumulator, so the two can never be mixed: `reported` money is provider-authored and
        `archive_matched` money is paired from the DRACO archive (PRD ans:Q5). Anything else —
        no reference, an unknown unit, a status this engine cannot price — is an unpriced hit and
        enters no total (PRD S14).

        The routing itself lives on :meth:`SavedCostTotals.add_saved_cost`, shared with the
        per-span totals; this adds only the coverage count the run publishes beside each total.
        """
        landed = self.add_saved_cost(amount_usd, provenance)
        if landed == "reported":
            self.reported_hits += 1
        elif landed == "archive_matched":
            self.archive_hits += 1
        else:
            self.unpriced_hits += 1

    def record(self, status: CacheStatus | None, reason: str | None) -> None:
        """Tally one gateway round trip's reported outcome.

        Args:
            status: What the gateway said, or ``None`` when it said nothing — an older gateway,
                or a path that never reached the cache. ``None`` counts as NOTHING rather than as
                a miss: "not reported" is not "the cache was consulted and had nothing", and
                inventing the second from the first would report a cache interaction that never
                happened.
            reason: The gateway's own word for that status, verbatim. Only a bypass's reason is
                broken out — a miss means the entry simply was not there, which answers nothing a
                reader would ask, while a bypass means the cache was never consulted at all,
                which is precisely the case that needs a why.
        """
        if status == "hit":
            self.hits += 1
        elif status == "miss":
            self.misses += 1
        elif status == _COUNTED_BYPASS:
            self.bypasses += 1
            self._count_reason((reason or "").strip() or UNSTATED_REASON)

    def attributes(self) -> dict[str, str | int | float | bool | None]:
        """The counters as `LogData` attributes: the three totals, plus one entry per reason.

        INVARIANT: every value is an integer count and every key is under `cache.`. That is the
        whole enforcement of spec §7's "no metric labelled by cache key, prompt or credential" —
        the shape admits no other kind of value.
        """
        attributes: dict[str, str | int | float | bool | None] = {
            CACHE_HITS: self.hits,
            CACHE_MISSES: self.misses,
            CACHE_BYPASSES: self.bypasses,
        }
        for reason, count in self._bypass_reasons.items():
            attributes[f"{BYPASS_REASON_PREFIX}{reason}"] = count
        if self.saved_cost_observed:
            # Counts first, so a reader always has the coverage beside any total. Each total is
            # published only when its own provenance was observed — an absent key says "no such
            # hit", which a `0` would misstate as "such a hit, worth nothing". The amount rides
            # as a canonical decimal STRING: the attribute is a flat log scalar, and a float
            # carrier would round the provider's exact value.
            attributes[SAVED_COST_REPORTED_HITS] = self.reported_hits
            attributes[SAVED_COST_ARCHIVE_HITS] = self.archive_hits
            attributes[SAVED_COST_UNPRICED_HITS] = self.unpriced_hits
            if self.saved_cost_usd is not None:
                attributes[SAVED_COST_USD] = format(self.saved_cost_usd, "f")
            if self.saved_cost_archive_usd is not None:
                attributes[SAVED_COST_ARCHIVE_USD] = format(self.saved_cost_archive_usd, "f")
        return attributes

    def summary_body(self) -> str:
        """The human-readable half of the summary line.

        The totals are stated here as well as in the attributes on purpose: a reader scanning a
        run's log sees the answer without expanding a structured payload, and the reasons — which
        are the part worth expanding for — stay in the attributes where they can be aggregated.
        """
        body = (
            f"gateway response cache: {self.hits} hit, {self.misses} miss, {self.bypasses} bypass"
        )
        if self.saved_cost_observed:
            # Labelled COUNTERFACTUAL wherever it is rendered (PRD S5): this is what the hits
            # would have cost, not what the run paid, and the two separate totals keep the
            # provider-authored money distinguishable from the archive-paired money.
            parts = []
            if self.saved_cost_usd is not None:
                parts.append(f"{format(self.saved_cost_usd, 'f')} reported")
            if self.saved_cost_archive_usd is not None:
                parts.append(f"{format(self.saved_cost_archive_usd, 'f')} archive-matched")
            body += (
                f"; counterfactual saved {', '.join(parts) or 'nothing priceable'}"
                f" ({self.unpriced_hits} unpriced hit)"
            )
        return body

    def _count_reason(self, reason: str) -> None:
        """Increment ``reason``'s bucket, collapsing into :data:`OVERFLOW_REASON` once the cap is
        reached. An already-known reason always keeps its own bucket, so the cap can never move a
        count that was already being reported separately."""
        if reason not in self._bypass_reasons and len(self._bypass_reasons) >= REASON_BUCKET_CAP:
            reason = OVERFLOW_REASON
        self._bypass_reasons[reason] = self._bypass_reasons.get(reason, 0) + 1


__all__ = [
    "BYPASS_REASON_PREFIX",
    "CACHE_BYPASSES",
    "CACHE_HITS",
    "CACHE_MISSES",
    "OVERFLOW_REASON",
    "REASON_BUCKET_CAP",
    "SAVED_COST_ARCHIVE_HITS",
    "SAVED_COST_ARCHIVE_USD",
    "SAVED_COST_REPORTED_HITS",
    "SAVED_COST_UNPRICED_HITS",
    "SAVED_COST_USD",
    "SavedCostProvenance",
    "SavedCostTotals",
    "UNSTATED_REASON",
    "RunCacheCounters",
]
