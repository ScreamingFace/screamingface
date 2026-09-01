"""Turns aigateway's `_aigw` usage-accounting block into the cost evidence a run publishes.

FEATURE: per-run cost reporting (`OME-849`). aigateway produces provider-call FACTS and explicitly
refuses to convert currency, attribute, or roll up — that boundary is stated in
`apps/aigateway/docs/usage-accounting.md`. This module is the consumer on the other side of it: the
Executor owns cost, because `url4.streaming` requires the executor to hand it a populated
`CostUsageData` and performs no arithmetic itself.

STORY: as a researcher reading a run Report, I see what my run cost — and an em dash rather than a
confident wrong number whenever the gateway could not observe the whole call.

INVARIANT — the rule the whole module exists to enforce: `Decimal("0")` and `None` are DIFFERENT
answers. Zero means the call was genuinely free (a cache hit); `None` means the evidence cannot
support a price. Collapsing them reports paid work as free, which is the failure aigateway's own
review named — treating absence of observation as proof of absence.

Scope today is OpenRouter, whose amounts arrive in `openrouter_credits` and convert to USD 1:1 by
owner decision. Anthropic authors no cost at all and therefore stays unpriced.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.runner.cache_readback import CacheOutcome
from screamingface_engine.world_config import provider_of

__all__ = [
    "OPENROUTER_CREDIT_UNIT",
    "PRICING_VERSION",
    "UNPRICED",
    "CallAccounting",
    "accumulate",
    "read_aigw",
    "retained_operation_accounting",
    "usd_from_aigw",
]

# WHY the version names a METHOD rather than a date: a consumer reads it to learn HOW the number was
# reached, and it is the seam a future rate card arrives through (`ratecard-<date>`) without
# invalidating runs priced this way.
PRICING_VERSION = "openrouter-credits-1usd"
UNPRICED = "unpriced"

OPENROUTER_CREDIT_UNIT = "openrouter_credits"
# INVARIANT: an owner decision (2026-08-17), not something this code can verify. It lives here as a
# named constant so the assumption is visible rather than implied by an absent multiplication.
_CREDIT_TO_USD = Decimal(1)
# The producer's published amount bound is 18 integer + 33 fractional digits; this leaves headroom
# so no conversion can round a value that arrived at the bound.
_AMOUNT_PRECISION = 18 + 33 + 2

# Copied verbatim from the producer's published schema (the `amount` property). Keep it that way:
# a locally-invented variant would drift from the contract it exists to mirror.
_CANONICAL_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{0,32}[1-9])?$")

METADATA_KEY = "_aigw"


@dataclass(frozen=True, slots=True)
class CallAccounting:
    """One gateway call's accounting, as screamingface-engine reports it onto the
    span that made the call.

    INVARIANT: every field is optional and `None` means "the gateway did not report
    it" — never zero. A cache hit legitimately has no provider and no tokens while
    still being priced at zero.
    """

    provider: str | None
    response_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: Decimal | None
    complete: bool
    provider_latency_ms: int | None
    attempts: int | None


def accumulate[T: (int, Decimal)](prior: T | None, new: T | None) -> T | None:
    """Sum two optional quantities, where an unknown part makes the whole unknown.

    INVARIANT: a total that silently omits a part while presenting itself as a total is worse than
    no total — the caller cannot tell a complete sum from a lossy one. The producing gateway applies
    the same rule to its own subtotals, where one unreadable amount refuses the whole sum.
    """
    if prior is None or new is None:
        return None
    return prior + new


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _count(value: object) -> int | None:
    """A non-negative token count, or `None` for anything that is not one.

    `bool` is refused explicitly: it is an `int` subclass, so a stray `True` would otherwise be
    counted as one token.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _exact_amount(value: object) -> Decimal | None:
    """A canonical non-negative amount, or `None`.

    WHY the pattern is copied from the producer rather than re-derived: it IS the published contract
    (`usage_accounting.schema.json`, the `amount` property), so matching it exactly means this
    consumer accepts precisely what the producer promises to emit and nothing else. It rules out
    negatives, exponent spellings, `NaN`/`Infinity`, and trailing-zero spellings of one value — all
    in one place, with no arithmetic that could round.

    WHY `str` and `int` only: those are the carriers that survived the producer's exact-decimal
    parsing (its schema types the amount as a string). A `float` has already lost the raw-JSON
    provenance the producer went to trouble to preserve, so accepting one would launder a number
    that is no longer exact. `bool` is refused for the same reason as in `_count` — it is an `int`
    subclass, so `True` would otherwise price as one credit.
    """
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(text, str) or _CANONICAL_AMOUNT.fullmatch(text) is None:
        return None
    return Decimal(text)


def _is_cache_hit(accounting: Mapping[str, Any] | None) -> bool:
    if accounting is None:
        return False
    cache = _mapping(accounting.get("cache"))
    return cache is not None and cache.get("status") == "hit"


def _credits_to_usd(subtotals: object) -> Decimal | None:
    """USD from exactly one OpenRouter-credit subtotal, else `None`.

    INVARIANT: never add across units. Several subtotals means several currencies, and summing them
    would invent an exchange rate nobody supplied. An unrecognised unit degrades to unpriced, which
    is what keeps the 1:1 conversion honest once a second provider appears.
    """
    if not isinstance(subtotals, list) or len(subtotals) != 1:
        return None
    row = _mapping(subtotals[0])
    known_unit = row is not None and row.get("unit") == OPENROUTER_CREDIT_UNIT
    amount = _exact_amount(row.get("amount")) if known_unit and row is not None else None
    if amount is None:
        return None
    # WHY a local context rather than a bare `*`: multiplication rounds to the AMBIENT decimal
    # context's precision — 28 significant digits by default — which silently truncates an amount at
    # the producer's 18-integer + 33-fractional bound. With a 1:1 rate the multiply looks like an
    # identity and is not one. Proven by
    # `test_an_amount_at_the_contract_precision_bound_survives_exactly`.
    # INVARIANT: money arithmetic here is independent of whatever decimal context the caller happens
    # to be running under, exactly as the producing gateway guarantees for its own subtotals.
    with localcontext() as ctx:
        ctx.prec = _AMOUNT_PRECISION
        return amount * _CREDIT_TO_USD


def usd_from_aigw(aigw: object) -> Decimal | None:
    """USD for one gateway call, or `None` when the evidence cannot support a price.

    Implements the normative decision table in
    `docs/spec/2026-08-17-OME-849-run-cost-openrouter.md` §3.2.

    INVARIANT: total over its input and never raises. The provider call may already be billed by the
    time this runs, so accounting must never turn a completed response into a run failure — the same
    rule the producing gateway applies on its own side of the boundary.

    AIDEV-NOTE: `known_direct_cost_subtotals` is populated by the producer ONLY when its capture was
    complete and nothing was omitted, and it has already summed across retries. Do not re-derive
    money by walking `attempts[]` — that double-counts, and it discards the producer's own refusal
    to total unreadable amounts.
    """
    envelope = _mapping(aigw)
    economics = _mapping(envelope.get("request_economics")) if envelope is not None else None
    if envelope is None or economics is None:
        return None
    status = economics.get("direct_cost_status")
    if status == "complete":
        return _credits_to_usd(economics.get("known_direct_cost_subtotals"))
    # INVARIANT: the P0 distinction. `not_applicable` covers BOTH "served from cache, genuinely
    # free" and "a real billed call through a provider we cannot observe", and both present an
    # EMPTY subtotal list. Reading the list alone reports paid work as free.
    free = status == "not_applicable" and _is_cache_hit(_mapping(envelope.get("usage_accounting")))
    return Decimal(0) if free else None


def _attempt_usage(attempt: Mapping[str, Any]) -> tuple[int | None, ...]:
    """One attempt's five token classes, in `CallAccounting` order."""
    usage = _mapping(attempt.get("usage")) or {}
    inputs = _mapping(usage.get("input")) or {}
    outputs = _mapping(usage.get("output")) or {}
    return (
        _count(inputs.get("total")),
        _count(outputs.get("total")),
        _count(inputs.get("cache_read")),
        # WHY the producer's `cache_write` maps to our `cache_creation`: the two names describe the
        # same quantity — tokens written INTO the prompt cache — in the provider's vocabulary and in
        # the GenAI semantic conventions respectively.
        _count(inputs.get("cache_write")),
        _count(outputs.get("reasoning")),
    )


def _attempt_latency(attempt: Mapping[str, Any]) -> int | None:
    return _count(attempt.get("latency_ms"))


def read_aigw(aigw: object) -> CallAccounting | None:
    """Evidence for one gateway call, or `None` when there is no `_aigw` block to read.

    `None` means "no accounting at all" and tells the caller to fall back to the provider's own
    `usage` object — the pre-`_aigw` behaviour. It is deliberately distinct from evidence whose
    fields are all `None`, which means the gateway was asked and reported nothing.

    INVARIANT: tokens are summed across EVERY attempt, failures included. A retry genuinely costs
    twice, and the producer contract states outright that a failed attempt may still carry
    provider-authored usage, so dropping failures under-reports the run. The pre-existing live/root
    Usage contract takes identity from the terminal attempt; retained operation accounting applies
    its stricter all-attempt agreement policy separately.
    """
    envelope = _mapping(aigw)
    if envelope is None:
        return None
    accounting = _mapping(envelope.get("usage_accounting"))
    raw_attempts = accounting.get("attempts") if accounting is not None else None
    attempts_are_well_formed = isinstance(raw_attempts, list) and all(
        _mapping(attempt) is not None for attempt in raw_attempts
    )
    attempts = (
        [m for a in raw_attempts if (m := _mapping(a)) is not None]
        if isinstance(raw_attempts, list)
        else []
    )

    # Seed from the first attempt, then accumulate: seeding is what lets a genuine `None` in the
    # first attempt poison the class, rather than being mistaken for "nothing seen yet".
    totals: tuple[int | None, ...] = (None,) * 5
    if attempts:
        totals = _attempt_usage(attempts[0])
        for attempt in attempts[1:]:
            observed = _attempt_usage(attempt)
            totals = tuple(accumulate(totals[i], observed[i]) for i in range(5))

    terminal = attempts[-1] if attempts else None
    provider = terminal.get("provider") if terminal is not None else None
    response_model = terminal.get("response_model") if terminal is not None else None
    complete = (
        accounting is not None
        and accounting.get("capture_status") == "complete"
        and _count(accounting.get("omitted_attempts")) == 0
        and attempts_are_well_formed
    )
    latency = None
    if attempts:
        latency = _attempt_latency(attempts[0])
        for attempt in attempts[1:]:
            latency = accumulate(latency, _attempt_latency(attempt))
    return CallAccounting(
        provider=provider if isinstance(provider, str) and provider else None,
        response_model=response_model if isinstance(response_model, str) else None,
        input_tokens=totals[0],
        output_tokens=totals[1],
        cache_read_tokens=totals[2],
        cache_creation_tokens=totals[3],
        reasoning_tokens=totals[4],
        cost_usd=usd_from_aigw(envelope),
        complete=complete,
        provider_latency_ms=latency,
        # INVARIANT: a count only exists where every attempt was validated. Counting a list
        # the reader had to skip entries from would publish a retry story that never happened.
        attempts=len(attempts) if attempts_are_well_formed else None,
    )


def _agreed_attempt_identity(attempts: list[Mapping[str, Any]], field: str) -> str | None:
    if not attempts:
        return None
    values = tuple(attempt.get(field) for attempt in attempts)
    first = values[0]
    return (
        first
        if isinstance(first, str) and first.strip() and all(value == first for value in values[1:])
        else None
    )


def _retained_attempt_identities(aigw: object) -> tuple[str | None, str | None]:
    """Provider and served model shared by every contributing attempt."""

    envelope = _mapping(aigw)
    accounting = _mapping(envelope.get("usage_accounting")) if envelope is not None else None
    raw_attempts = accounting.get("attempts") if accounting is not None else None
    if not isinstance(raw_attempts, list):
        return None, None
    attempts = [_mapping(attempt) for attempt in raw_attempts]
    if any(attempt is None for attempt in attempts):
        return None, None
    complete_attempts = [attempt for attempt in attempts if attempt is not None]
    return (
        _agreed_attempt_identity(complete_attempts, "provider"),
        _agreed_attempt_identity(complete_attempts, "response_model"),
    )


def retained_operation_accounting(
    *,
    request_model: str,
    usage: Mapping[str, object] | None,
    aigw: object,
    cache: CacheOutcome,
) -> OperationAccounting:
    """Normalize one consumed response without changing live/root Usage reporting."""

    call = read_aigw(aigw)
    complete = call is not None and call.complete
    retained_provider, retained_response_model = (
        _retained_attempt_identities(aigw) if complete else (None, None)
    )
    if cache.status == "hit":
        return OperationAccounting(
            # INVARIANT: a cache hit performs no current provider dispatch. Its provider identity
            # is therefore the canonical provider for the declared route, never an attempt copied
            # from incomplete or stored Gateway evidence.
            provider=provider_of(request_model),
            request_model=request_model,
            response_model=retained_response_model,
            usage=OperationUsage(
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                reasoning_tokens=0,
                cost_usd="0",
            ),
            provider_latency_ms=0,
            # A hit performs no current provider dispatch, so zero attempts is the exact
            # truth on this path — the same reason cost and latency are zero, not null.
            provider_attempts=0,
            cache=_operation_cache(cache),
        )
    reported = usage or {}
    return OperationAccounting(
        provider=(
            retained_provider if complete else provider_of(request_model) if call is None else None
        ),
        request_model=request_model,
        response_model=retained_response_model,
        usage=OperationUsage(
            input_tokens=(
                call.input_tokens
                if complete and call is not None
                else _count(reported.get("prompt_tokens"))
                if call is None
                else None
            ),
            output_tokens=(
                call.output_tokens
                if complete and call is not None
                else _count(reported.get("completion_tokens"))
                if call is None
                else None
            ),
            cache_read_tokens=call.cache_read_tokens if complete and call is not None else None,
            cache_creation_tokens=(
                call.cache_creation_tokens if complete and call is not None else None
            ),
            reasoning_tokens=call.reasoning_tokens if complete and call is not None else None,
            cost_usd=(
                format(call.cost_usd, "f")
                if complete and call is not None and call.cost_usd is not None
                else None
            ),
        ),
        provider_latency_ms=(call.provider_latency_ms if complete and call is not None else None),
        provider_attempts=(call.attempts if complete and call is not None else None),
        cache=_operation_cache(cache),
    )


def _operation_cache(cache: CacheOutcome) -> OperationCache:
    return OperationCache(
        hits=int(cache.status == "hit"),
        misses=int(cache.status == "miss"),
        bypasses=int(cache.status == "bypass"),
        unknown=int(cache.status is None),
    )
