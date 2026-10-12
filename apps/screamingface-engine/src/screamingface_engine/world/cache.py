"""Translate a run's cache INTENT into aigateway's request-body vocabulary.

This module is the ONLY place in url4 that knows the string `use-cache`, and that is the whole
point of it existing. `packages/url4`'s :class:`~url4.streaming.protocol.CachePolicy` speaks
intent — "does this run participate?" — because it ships to SDK users and must not encode some
server's body shape (plan §4). The adapter that talks to that server owns the wire words.

INVARIANT — aigateway v2's cache-control grammar is CLOSED (spec §1.0). An unrecognised key
inside the `cache` object does NOT degrade to "ignored": it makes the whole request **bypass**
the cache, silently, with nothing raised anywhere, and even alongside an otherwise valid
`use-cache: true`. The only symptom is a cache that never hits. So:

    NOTHING but `use-cache`, and `attempt` for Attempt 2 and later, may ever appear in the
    object this module builds — and `policy_to_body_field` builds `use-cache` only.

FEATURE (OME-1458): `attempt` names Attempt 2..N of a Case, which the gateway keys beside the
request so Attempt 2 is never served Attempt 1's stored reply. A gateway that predates it reads
the field as unknown and bypasses: the Attempt is still asked afresh, only its rerun is not free.

`CachePolicy.max_age` is therefore url4-INTERNAL and is deliberately not read here. v2 refuses a
freshness bound (`global_controls.py:79-83`), so forwarding it would buy `unsupported_control`
instead of a bound; it is applied at read-back (plan Batch 7), where an entry's age can be
compared against it, and degrades to an opt-out until the gateway reports one.
"""

from __future__ import annotations

from collections.abc import Mapping

from url4.streaming.protocol import CachePolicy

_USE_CACHE = "use-cache"
"""aigateway v2's one and only cache-control key. Named once so the invariant above has a single
place to be violated, rather than a literal repeated at each branch."""


def policy_to_body_field(policy: CachePolicy) -> dict[str, dict[str, bool]]:
    """The `cache` field to merge into an aigateway chat-completions body, or nothing.

    A dumb translation on purpose. It takes a RESOLVED policy — the D1 default is applied once,
    at convergence (plan Batch 5), so the decision "what does silence mean?" lives in exactly one
    place and this function never has to re-derive it.

    Args:
        policy: The run's resolved cache intent. Never ``None``; a run that declared nothing
            arrives here as a policy, not as an absence.

    Returns:
        ``{"cache": {"use-cache": False}}`` when the run opted out, and an EMPTY dict otherwise
        — participation is expressed by saying nothing. v2 reads absent, ``null`` and ``{}``
        identically (spec §1.0), so the omission is not a shortcut: it keeps a default run's
        egress body byte-identical to today's (spec §9.1) and keeps the smallest possible surface
        exposed to the closed-grammar bypass. Merge with ``**`` at the call site.
    """
    # `participate is False` rather than `not policy.participate`: `None` means NOT STATED, and
    # under D1 an unstated policy participates — same wire answer as an explicit True. Only an
    # explicit opt-out earns a field on the wire.
    if policy.participate is False:
        # Built fresh per call. A module-level literal would be shared mutable state that two
        # concurrent runs could contaminate each other through, at the one seam where a wrong
        # value costs money silently.
        return {"cache": {_USE_CACHE: False}}
    return {}


_ATTEMPT = "attempt"
"""aigateway's Attempt-number key (OME-1458), sent only for Attempt 2 and later."""


def attempt_body_field(attempt: int | None) -> dict[str, dict[str, object]]:
    """The `cache` field naming Attempt ``attempt`` (2 or more), or nothing for Attempt 1.

    Attempt 1 adds nothing, so a Benchmark without Attempts sends what it always sent.
    """

    return {} if attempt is None else {"cache": {_ATTEMPT: attempt}}


def with_cache_policy(body: Mapping[str, object], policy: CachePolicy) -> dict[str, object]:
    """Merge the run's cache policy into one chat body, keeping an Attempt number it carries.

    For a body with no `cache` object this is ``{**body, **policy_to_body_field(policy)}``,
    the merge every call has always used. An Attempt 2+ body already carries
    ``{"cache": {"attempt": 2}}``; the policy's `use-cache` joins it inside that object —
    ``{"cache": {"use-cache": False, "attempt": 2}}`` for an opt-out — instead of replacing it.
    """

    stated: dict[str, bool] = policy_to_body_field(policy).get("cache", {})
    carried: object = body.get("cache")
    if not isinstance(carried, Mapping):
        return {**body, **policy_to_body_field(policy)}
    return {**body, "cache": {**carried, **stated}}


__all__ = ["attempt_body_field", "policy_to_body_field", "with_cache_policy"]
