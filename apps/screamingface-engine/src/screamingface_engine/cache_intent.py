"""Parse the request ``Cache-Control`` field into a run's cache INTENT (spec §5.1, D6).

WHY this lives at the top level rather than in :mod:`screamingface_engine.rest.cache_header`
(unit 3): the exact same RFC 9111 request-directive parsing is now needed by BOTH the App
(the REST edge, a control-plane module) and the node tier's sync scope producer (unit 3,
which lives in the shared ``world`` package and may not import the control plane). A shared
leaf is the only layering-legal home for something both halves parse identically — a second
copy in ``world`` would let the App and the node tier disagree about the same header, which
is the exact drift class F1/F3 exist to remove. ``rest.cache_header`` re-exports these
names, so the App's existing import path is unchanged.

``Cache-Control`` is the standard field and it was chosen deliberately over a private
``URL4-Cache``: RFC 9111 already defines ``no-store`` / ``no-cache`` / ``max-age`` as *request*
directives with exactly the meaning wanted here, and D6 accepts the consequence that an
intermediary — Envoy, a CDN, a browser's hard-refresh — may both read it and add to it. That is
what the field means; a standard header intermediaries are asked to ignore would be the worst of
both.

**Every directive collapses to participate / opt-out AT THIS EDGE. None is forwarded verbatim.**
That is not a convenience, it is the correctness boundary: aigateway v2's cache-control grammar
is CLOSED to a single key, ``use-cache``, and any other key inside the request body's ``cache``
object makes the whole request BYPASS the cache — silently, with nothing raised anywhere (spec
§1.0). Forwarding ``no-store`` as itself would opt the caller out for the *wrong* reason
(``unsupported_control`` rather than the honest ``opted_out``), and forwarding ``max-age`` would
lose caching altogether. So this module speaks HTTP and returns intent; ``world/cache.py`` is
the only place that speaks the gateway's wire vocabulary.

TWO GUARANTEES this module owes every caller:

1. **It never raises.** The field is caller- and proxy-controlled; a cache directive is a hint
   about cost, not a term of the request, so failing a whole ensemble run over a malformed one
   trades a free missed hit for a dead run. Garbage is ignored.
2. **It never invents intent.** Undecipherable input returns ``None`` — *not stated* — which
   resolves to the ON default at convergence. Returning a default-constructed policy instead
   would let a malformed header shadow a perfectly good declaration on the WS attach frame.

``max-age`` is the one directive **preserved rather than collapsed** (D11, spec §3.5): url4 can
today neither ask the gateway for a freshness bound nor read an entry's age, so the directive
degrades to an opt-out at read-back — but the value survives this edge, so the day either
upstream blocker lifts the change is a branch, not a redesign.
"""

from __future__ import annotations

from dataclasses import dataclass

from url4.streaming.protocol import CachePolicy

_OPT_OUT_DIRECTIVES = frozenset({"no-store", "no-cache"})
"""Both mean "do not use the cache" once they reach v2, which has no read-only/write-only lane:
`no-cache` ("don't serve me a stored answer") can only be honoured by not participating at all.
Mapping it to anything else would be a promise the upstream cannot keep."""

_OPT_IN_DIRECTIVE = "url4-use-cache"
"""An extension token, url4-owned — RFC 9111 provides no *request* directive meaning "you may
serve me a stored answer", because that is HTTP's default and it is ours too (D1). It exists so a
caller can state participation rather than merely fail to forbid it, which is what lets the header
carrier override an opt-out declared on the attach frame."""

_MAX_AGE_DIRECTIVE = "max-age"


@dataclass(frozen=True)
class _Declared:
    """What one field-value actually said, before it is turned into a policy."""

    opt_out: bool
    opt_in: bool
    max_age: int | None

    @property
    def states_participation(self) -> bool:
        """Whether anything asked to participate. `is not None` and not truthiness: `max-age=0`
        is the strictest bound a caller can state, and dropping it for being falsy would turn the
        strictest request into silence — and silence into the ON default."""
        return self.opt_in or self.max_age is not None


def parse_cache_control(raw: str | None) -> CachePolicy | None:
    """The caller's declared cache intent, or ``None`` when the field stated nothing.

    Args:
        raw: The inbound ``Cache-Control`` field value, or ``None`` when the header is absent.

    Returns:
        ``CachePolicy(participate=False)`` when any opt-out directive appears — conflicts resolve
        to the safe side, because the worst case of opting out is a missed hit while the worst
        case of participating against a caller who refused is a stale or shared answer they
        explicitly declined. ``CachePolicy(participate=True, max_age=…)`` when something asked to
        participate. ``None`` when nothing decipherable was said, so the default applies.

        A returned policy carries ``max_age`` only alongside ``participate=True``: a freshness
        bound on a run that does not participate is meaningless, and carrying it would invent an
        "opted out, but only for 60s" state nothing downstream can act on.
    """
    if not raw:
        return None
    declared = _scan(raw)
    # Checked FIRST, so an opt-out anywhere in the list wins over anything else in it and the
    # outcome cannot depend on the order an intermediary happened to concatenate members in.
    if declared.opt_out:
        return CachePolicy(participate=False)
    return (
        CachePolicy(participate=True, max_age=declared.max_age)
        if declared.states_participation
        else None
    )


def _scan(raw: str) -> _Declared:
    """Fold the field's list members into what they collectively declared.

    Unknown members are dropped without disturbing known ones — `Cache-Control` is an open
    vocabulary that intermediaries legitimately add to, so an unrecognised member is ordinary
    traffic rather than an error. `only-if-cached` lands here on purpose (spec §8.3): honouring
    it would require a 504 when nothing is cached, and a url4 run fans out to many gateway calls,
    so one uncached leaf would kill an entire ensemble.
    """
    opt_out = False
    opt_in = False
    max_age: int | None = None
    for member in raw.split(","):
        name, _, value = member.partition("=")
        # Lower-cased because directive names are case-insensitive — the same normalisation
        # `_parse_prefer` already applies. A client that upper-cases would otherwise have its
        # opt-out silently dropped, which is the exact failure mode this design exists to avoid.
        key = name.strip().lower()
        if key in _OPT_OUT_DIRECTIVES:
            opt_out = True
        elif key == _OPT_IN_DIRECTIVE:
            opt_in = True
        elif key == _MAX_AGE_DIRECTIVE:
            max_age = _tighter(max_age, _delta_seconds(value))
    return _Declared(opt_out, opt_in, max_age)


def _delta_seconds(value: str) -> int | None:
    """A directive's argument as non-negative whole seconds, or ``None`` if it is not one.

    The argument may be written as a quoted-string, so the quotes are stripped before parsing.
    Anything else — empty, fractional, negative, non-numeric — makes the *directive* unusable
    rather than the field, so it is dropped and its neighbours are honoured unchanged.
    """
    try:
        seconds = int(value.strip().strip('"'))
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _tighter(current: int | None, candidate: int | None) -> int | None:
    """The stricter of two bounds, treating ``None`` as "no bound stated".

    A repeated `max-age` is a conflict like any other and resolves conservatively: the smaller
    bound admits fewer stale answers. First-wins or last-wins would let a duplicate appended by
    an intermediary LOOSEN what the caller asked for.
    """
    if candidate is None:
        return current
    if current is None:
        return candidate
    return min(current, candidate)


__all__ = ["parse_cache_control"]
