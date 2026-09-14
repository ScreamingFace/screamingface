"""Read the gateway's cache answer off a chat-completions response, and decide what
to do with it (spec §7 / D7, plan Batch 7).

The mirror image of :mod:`screamingface_engine.runner.cache`, and a separate module
from it on purpose: that one is four lines guarding ONE invariant — nothing but
`use-cache` ever goes out — and burying a structured-field parser beside it would
hide the single most expensive rule in this feature. Egress out, ingress here.

**WHY reading it back is mandatory rather than nice-to-have.** A cache hit costs nothing
upstream, yet `_report_usage` bills it exactly like a fresh call. Turning caching on without
this makes the run's cost taxonomy wrong in the direction that HIDES savings — so nobody ever
reports the bug.

TWO SOURCES, IN PREFERENCE ORDER (spec §2.2):

1. **`Cache-Status`** — RFC 9211, Standards Track, and an exact fit: `hit`, `fwd=bypass` and
   `fwd=miss` are its own defined tokens. Read FIRST even though aigateway does not emit it yet,
   because doing so costs nothing today and means url4 needs no change on the day it does.
2. **`X-AIGW-Cache` / `-Reason` / `-Key`** — the ad hoc triple aigateway emits today, verbatim.

`Cache-Status` is an RFC 8941 Structured Field **List**: one member per cache that handled the
response — aigateway, an Envoy sidecar, a CDN — ordered origin-closest first. url4 selects the
**aigateway member**, never blindly the first. Reading a CDN's `hit` as aigateway's answer would
report a saving that never happened and mark a real provider dispatch as free.

THREE GUARANTEES this module owes its caller:

1. **It never raises.** Every function here runs on the response path of every gateway call. A
   cache outcome is an observation ABOUT a call, never a term OF it; failing a run over a
   malformed header would trade a missing telemetry field for a dead ensemble.
2. **It never invents.** Anything undecipherable degrades to ``None`` — an absent status, not a
   guessed one. A fabricated `bypass` reads as "the cache refused this", a claim nobody made.
3. **It carries the gateway's vocabulary verbatim.** Normalising `opted_out` and
   `unsupported_control` into one word would erase the difference between "url4 asked for no
   cache and got none" and "url4 sent a key the gateway does not know and silently lost every
   hit" — which is the question this telemetry exists to answer.

**`Age`, and D11.** Freshness is read from the standard `Age` field (RFC 9111 §5.1) — "the
sender's estimate of the time since the response was generated", which is precisely the fact a
`max-age` bound is compared against. `Cache-Status`'s `ttl` parameter is deliberately NOT read as
an age: RFC 9211 §2.4 defines it as the *remaining freshness lifetime*, the inverse quantity, and
against a corpus whose rows never expire it has no meaning at all. Until the gateway reports an
age, a bounded hit cannot be proven fresh — see :func:`requires_revalidation`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from url4.streaming.protocol import CachePolicy

CacheStatus = Literal["hit", "miss", "bypass"]
"""The protocol's closed outcome vocabulary, restated for the parse.

AIDEV-NOTE: the same literal is spelled on `url4.streaming.protocol.SpanData` and on
`url4.observe.ModelResponse` — the wire end and the engine end of the same fact. Change all
three together; a value that parses here but does not validate there is a run-time 500 on the
publishing path, not a type error.
"""

_CACHE_STATUS_FIELD = "Cache-Status"
_AGE_FIELD = "Age"
_LEGACY_STATUS_FIELD = "X-AIGW-Cache"
_LEGACY_REASON_FIELD = "X-AIGW-Cache-Reason"
_LEGACY_KEY_FIELD = "X-AIGW-Cache-Key"

_AIGATEWAY_MEMBER = "aigateway"
"""The cache identity url4 believes in a `Cache-Status` list. Every other member belongs to some
intermediary and says nothing about whether the GATEWAY served this call from its corpus."""

_HIT_PARAM, _FWD_PARAM, _DETAIL_PARAM, _KEY_PARAM = "hit", "fwd", "detail", "key"
_FWD_BYPASS = "bypass"
"""RFC 9211 §2.2's one token meaning the cache was not consulted at all. Every other `fwd` token
(`miss`, `uri-miss`, `vary-miss`, `stale`, …) means it WAS consulted and had nothing to serve —
the difference between "you opted out" and "we looked and it wasn't there"."""

_SF_TRUE = "?1"
"""RFC 8941 §3.3.6's Boolean true. A bare parameter (`; hit`) is true by definition (§3.1.2), so
only an explicit `hit=?0` can turn it off."""

_LEGACY_STATUSES: dict[str, CacheStatus] = {"hit": "hit", "miss": "miss", "bypass": "bypass"}
"""A LOOKUP rather than a membership test, so the closed vocabulary and the type that carries it
cannot drift apart: a value the protocol would reject is one this mapping simply does not have."""

_KEYED_STATUSES = frozenset({"hit", "miss"})
"""A bypassed request has no entry, so a key on it identifies nothing. aigateway already sets its
header only for these two; url4 re-states the rule rather than trusting the sender."""


@dataclass(frozen=True, slots=True)
class CacheOutcome:
    """What one gateway round trip reported about the cache. Every field is optional because
    every one of them can be legitimately absent — an older gateway, a non-cache error path, or
    a response that never reached the cache at all."""

    status: CacheStatus | None
    reason: str | None
    key: str | None
    """The entry's identity — a hash PREFIX by construction (the gateway truncates it), never
    prompt or response content, which is what makes it safe to carry.

    AIDEV-NOTE: parsed but not published. `SpanData` carries no key field, and inventing one to
    hold this would put a per-entry identifier on a wire type nothing consumes. It is read here
    so the "hit/miss only" rule is enforced at the seam that would otherwise leak it, and so a
    future consumer has it without re-deriving the parse. Never label a metric with it (spec §7).
    """
    age_s: int | None
    retried: bool = False
    """Whether a transport retry preceded the round trip that produced this outcome.

    A retried attempt may ALREADY have been processed and billed upstream with only its response
    lost, so a hit that follows one cannot prove the cache avoided anything — the row it hit may
    be the one the lost attempt just paid for and wrote. Carried here rather than derived later
    because only the posting function knows it happened, and the fact dies with the response.

    Defaulted `False` so every existing construction site keeps its meaning: absent evidence of a
    retry is not evidence of one.
    """


def read_cache_outcome(headers: Mapping[str, str], *, retried: bool = False) -> CacheOutcome:
    """The cache outcome a chat-completions response reported. Total — it never raises.

    Args:
        headers: The response's fields. Matched case-insensitively (RFC 9110 §5.1), so an
            `httpx.Headers` and a plain dict behave the same.
        retried: Whether a transport retry preceded the round trip these headers came from. Carried
            straight onto the returned outcome — see `CacheOutcome.retried`.

    Returns:
        The parsed outcome, preferring `Cache-Status` and falling back to the `X-AIGW-Cache*`
        triple. An unusable preferred field falls THROUGH to the fallback rather than shadowing
        it: the signal exists in the other field, and dropping it because the standard one was
        garbage would lose the outcome for no reason.
    """
    reported = _from_cache_status(headers) or _from_legacy_triple(headers)
    age_s = _non_negative_int(_field(headers, _AGE_FIELD))
    if reported is None:
        return CacheOutcome(status=None, reason=None, key=None, age_s=age_s, retried=retried)
    keyed = reported.status in _KEYED_STATUSES
    return CacheOutcome(
        status=reported.status,
        reason=reported.reason or None,
        key=(reported.key or None) if keyed else None,
        age_s=age_s,
        retried=retried,
    )


def requires_revalidation(policy: CachePolicy, outcome: CacheOutcome) -> bool:
    """Whether this answer must be refused and the call re-issued with an explicit opt-out.

    D11 (spec §3.5) says a `max-age` bound is HONOURED. Two upstream halves are missing: the
    gateway's control grammar accepts no bound, and it reports no age. So url4 honours the bound
    at the only place left to it — the response — by refusing what it cannot prove fresh.

    Args:
        policy: The run's resolved policy. ``max_age`` is url4-internal and never left this
            process; it exists precisely so this decision can be made.
        outcome: What the gateway just reported.

    Returns:
        ``True`` only for a HIT whose age is unknown or beyond the bound.

        The three ``False`` cases each matter. **No bound stated** — the D1 default asks for
        nothing, so the overwhelming majority of runs pay nothing for D11 existing. **A miss or a
        bypass** — that answer was just generated, so its age is zero and every bound already
        holds; re-issuing there would double the cost of every call a bounded run makes. **A hit
        within the bound** — the honoured path, dormant until the gateway reports `Age`.

        Cost of the ``True`` case: one extra round trip, and a body read then discarded. Cheap
        against the alternative, which is silently serving an answer of unknown age out of a
        corpus that never expires to a caller who explicitly bounded it.
    """
    if policy.max_age is None or outcome.status != "hit":
        return False
    if outcome.age_s is None:
        return True
    # `>` not `>=`: RFC 9111 §5.2.1.1 asks for an age "less than or equal to" the bound, so an
    # entry exactly at it is still acceptable.
    return outcome.age_s > policy.max_age


@dataclass(frozen=True, slots=True)
class _Reported:
    """One source's raw reading, before the key rule and the age are applied to it."""

    status: CacheStatus
    reason: str | None
    key: str | None


def _from_cache_status(headers: Mapping[str, str]) -> _Reported | None:
    """The aigateway member of an RFC 9211 `Cache-Status` list, or ``None`` when the field is
    absent, names no aigateway member, or names one that states neither a hit nor a forward."""
    raw = _field(headers, _CACHE_STATUS_FIELD)
    if not raw:
        return None
    for member in _split_top_level(raw, ","):
        name, params = _parse_member(member)
        # A member that names us but says nothing usable does not stop the scan: a second one
        # that does is worth more than an early return of nothing.
        if name.lower() == _AIGATEWAY_MEMBER and (reported := _reported_from(params)) is not None:
            return reported
    return None


def _reported_from(params: dict[str, str | None]) -> _Reported | None:
    """Read one member's parameters as an outcome, or ``None`` when it states none.

    `detail` outranks the `fwd` token as the reason: `fwd` says only THAT the request was
    forwarded, while `detail` is where a cache puts its own word for WHY — which under aigateway
    is the vocabulary (`opted_out`, `unsupported_control`, …) this whole field exists to surface.
    """
    detail, key = params.get(_DETAIL_PARAM), params.get(_KEY_PARAM)
    if _HIT_PARAM in params and _is_true(params[_HIT_PARAM]):
        return _Reported("hit", detail, key)
    fwd = params.get(_FWD_PARAM)
    if not fwd:
        return None
    status: CacheStatus = "bypass" if fwd.strip().lower() == _FWD_BYPASS else "miss"
    return _Reported(status, detail or fwd, key)


def _from_legacy_triple(headers: Mapping[str, str]) -> _Reported | None:
    """The `X-AIGW-Cache*` triple aigateway emits today, verbatim.

    A status outside the closed vocabulary yields ``None`` rather than a guess: the field is a
    free string on the wire, and no rule could recover which of the three an unknown word meant.
    """
    status = _LEGACY_STATUSES.get((_field(headers, _LEGACY_STATUS_FIELD) or "").strip().lower())
    if status is None:
        return None
    return _Reported(
        status,
        (_field(headers, _LEGACY_REASON_FIELD) or "").strip() or None,
        (_field(headers, _LEGACY_KEY_FIELD) or "").strip() or None,
    )


def _field(headers: Mapping[str, str], name: str) -> str | None:
    """One field's value, matched case-insensitively.

    `httpx.Headers` already is case-insensitive; a plain mapping a caller hands in is not, and
    RFC 9110 §5.1 makes field names case-insensitive regardless of which one arrived.
    """
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    return next((v for k, v in headers.items() if k.lower() == lowered), None)


def _split_top_level(raw: str, sep: str) -> list[str]:
    """Split on `sep` OUTSIDE quoted strings.

    INVARIANT: quote-aware, because an RFC 8941 String may contain the separator — a cache named
    `"CDN, Inc."` splits into two bogus members under a naive `split(",")`, and the real
    aigateway member is then never found. Characters are kept verbatim; unescaping is
    :func:`_unquote`'s job. An unterminated quote simply swallows the rest of the field, which
    leaves an undecipherable member rather than an exception.
    """
    parts: list[str] = []
    current = ""
    in_quotes = False
    escaped = False
    for char in raw:
        if escaped:
            escaped = False
        elif char == "\\" and in_quotes:
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
        elif char == sep and not in_quotes:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return parts


def _parse_member(raw: str) -> tuple[str, dict[str, str | None]]:
    """One list member as `(cache name, parameters)`.

    A parameter with no `=` is a Boolean true by RFC 8941 §3.1.2 and is recorded as ``None`` —
    distinguishable from `hit=?0`, which is an explicit false. Unnamed parameters are dropped;
    a later repeat of a name wins, matching §3.1.2's "the last instance".
    """
    parts = _split_top_level(raw, ";")
    name = _unquote(parts[0].strip())
    params: dict[str, str | None] = {}
    for part in parts[1:]:
        key, assigned, value = part.partition("=")
        key = key.strip().lower()
        if key:
            params[key] = _unquote(value.strip()) if assigned else None
    return name, params


def _unquote(raw: str) -> str:
    """An RFC 8941 String with its delimiters removed and its escapes resolved.

    Anything not delimited — a Token, an Integer, a fragment left by an unterminated quote — is
    returned unchanged, so a bare `aigateway` and a quoted `"aigateway"` read identically.
    """
    if len(raw) < 2 or not raw.startswith('"') or not raw.endswith('"'):
        return raw
    out = ""
    escaped = False
    for char in raw[1:-1]:
        if not escaped and char == "\\":
            escaped = True
            continue
        out += char
        escaped = False
    return out


def _is_true(value: str | None) -> bool:
    """RFC 8941 Boolean semantics: a bare parameter is true; only `?1` is true when written out."""
    return value is None or value.strip() == _SF_TRUE


def _non_negative_int(raw: str | None) -> int | None:
    """`raw` as whole non-negative seconds, or ``None`` when it is not that.

    RFC 9111 §5.1 defines `Age` as a non-negative integer. Anything else is unusable, and an
    unusable age must read as UNKNOWN — the conservative direction, since it is exactly an
    unknown age that makes a caller's freshness bound unenforceable.
    """
    if raw is None:
        return None
    try:
        seconds = int(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


__all__ = ["CacheOutcome", "CacheStatus", "read_cache_outcome", "requires_revalidation"]
