"""The anonymous budget, keyed on something the caller cannot choose.

Spec §7 admits anonymous writes, which makes this the repo's first rate limit and the thing
standing between a public endpoint and the private workspace the team reads. Two properties
matter more than the algorithm:

**The key must not be attacker-controlled.** Trusting `CF-Connecting-IP` whenever the peer is
inside the trusted networks means trusting it always — the mesh proxy is the peer on every single
request — so rotating the header yields a fresh bucket per request. That is not merely a bypass:
each forged key also *occupies a slot* in the table below, so the same rotation evicts legitimate
callers' windows. The default is therefore the TCP peer, and the header is read only on an
explicit opt-in and only from a peer inside `allowed_networks` (plan §11 conflict 14).

**Overflow fails closed.** A bounded table needs an answer for "full", and evict-oldest makes
filling the table the way to clear somebody else's window. A new key that does not fit is
answered as throttled instead. The only entries ever dropped are buckets that have refilled to
capacity, which release no budget: a full bucket is exactly what a first-time caller is handed.

**Read the default key for what it is.** In a deployment the mesh proxy is the peer on every
request, so with `trust_client_ip_header` off the anonymous budget is effectively ONE bucket for
all anonymous callers rather than one per person. That is the deliberate reading of spec §7's
"key on the verified connection": per-caller limiting belongs at Cloudflare's edge, which can see
the real client, and this is the service-side backstop behind it. Do not "fix" it by trusting a
header — that is precisely the bypass the paragraph above describes, and it is why the setting
that would enable it defaults to off and is guarded twice.

A per-process table, deliberately. Plan §2.4 freezes the environment surface and names no shared
store, and the deployment runs a small replica count behind a mesh that does not pin a caller to
a replica — so the effective limit is `replicas × anon_rate_limit`. That is the accepted
imprecision: this is a spam brake in front of a human triage queue, not a quota.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network

from .mesh_identity import peer_in_networks

logger = logging.getLogger(__name__)

CLIENT_IP_HEADER = "CF-Connecting-IP"
"""The edge's client-address header. Read only under :attr:`Settings.trust_client_ip_header`, and
even then only from a mesh peer. Named here and nowhere else, for the same reason the identity
header is named in exactly one module."""

MAX_KEY_LENGTH = 64
"""How much of a key is kept. An address is far shorter; the bound exists because under the
opt-in a header supplies part of it, and an unbounded string would make the table's memory a
function of what a caller sends rather than of :attr:`Settings.anon_rate_max_keys`."""


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether this request fits in the caller's budget, and what to tell them if not."""

    allowed: bool
    retry_after_s: int
    """Seconds until the caller has a token again. Always positive, and meaningful only when
    ``allowed`` is False — a `429` with no backoff hint is answered by an immediate retry, which
    is the behaviour the limit exists to stop."""


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """A token bucket per key: ``burst`` capacity, refilled at ``limit`` per ``window_s``.

    Two numbers rather than one because they answer different questions. ``burst`` is what a
    legitimate double-click or a client's single retry needs; ``limit`` is what a submission loop
    runs into. A single "N per window" counter cannot express both, and picking one number means
    either refusing a retry or admitting a loop.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_s: int,
        burst: int,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # `time.monotonic` and not `time.time`: a clock step backwards over an NTP correction
        # would freeze every bucket for the size of the step.
        self._rate = limit / window_s
        self._window_s = window_s
        self._burst = float(burst)
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str) -> Decision:
        """Spend one token for ``key``, or refuse.

        Not a coroutine and not locked: the whole body is synchronous, so it runs to completion
        between `await` points on one event loop and there is no interleaving to protect against.
        A lock here would be a lie about the concurrency model, and an `async` signature would
        invite one to be added later.
        """
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            return self._admit_new_key(key, now)
        bucket.tokens = min(self._burst, bucket.tokens + (now - bucket.updated) * self._rate)
        bucket.updated = now
        if bucket.tokens < 1.0:
            return Decision(allowed=False, retry_after_s=self._seconds_until_a_token(bucket.tokens))
        bucket.tokens -= 1.0
        return Decision(allowed=True, retry_after_s=0)

    def _admit_new_key(self, key: str, now: float) -> Decision:
        """A key seen for the first time gets a full bucket — unless the table has no room."""
        if len(self._buckets) >= self._max_keys:
            self._drop_full_buckets(now)
        if len(self._buckets) >= self._max_keys:
            # INVARIANT: refuse, never evict. Everything still in the table at this point owes
            # budget, so making room would mean handing a throttled caller a fresh window — which
            # turns filling the table into the bypass. Throttling a new caller is the lesser harm
            # and it is loud: this line is the alert that the ceiling needs raising.
            logger.warning(
                "anonymous rate-limit key table is full at %d keys; throttling new callers "
                "rather than releasing budgets",
                self._max_keys,
            )
            return Decision(allowed=False, retry_after_s=self._window_s)
        self._buckets[key] = _Bucket(tokens=self._burst - 1.0, updated=now)
        return Decision(allowed=True, retry_after_s=0)

    def _drop_full_buckets(self, now: float) -> None:
        """Forget every key that has refilled to capacity.

        Dropping one of these releases NO budget: a bucket at capacity is indistinguishable from
        a key that has never been seen, because that is exactly what a new key is given. It is
        the only eviction rule with that property, which is why it is the only one here.
        """
        for key, bucket in list(self._buckets.items()):
            if bucket.tokens + (now - bucket.updated) * self._rate >= self._burst:
                del self._buckets[key]

    def _seconds_until_a_token(self, tokens: float) -> int:
        """Rounded UP, and never zero: `Retry-After: 0` invites the immediate retry this refuses."""
        return max(1, math.ceil((1.0 - tokens) / self._rate))


def rate_limit_key(
    headers: Mapping[str, str],
    peer: str | None,
    networks: Sequence[IPv4Network | IPv6Network],
    *,
    trust_client_ip_header: bool,
) -> str | None:
    """What this caller's budget is counted against, or ``None`` when there is nothing to count.

    ``None`` is a refusal, not an exemption — the gate turns it into a `429`. A request whose
    peer this process cannot see cannot be rate-limited at all, and the safe answer for an
    unauthenticated write is to refuse rather than to admit it under a shared key that every
    other unattributable request would also land in.

    The header path is guarded twice over: the operator must opt in AND the peer must be inside
    the mesh. Without the second condition the opt-in would be equivalent to trusting the header
    from anyone, since the proxy is always the peer.
    """
    if peer is None:
        return None
    if trust_client_ip_header and peer_in_networks(peer, networks):
        forwarded = (headers.get(CLIENT_IP_HEADER) or "").strip()
        if forwarded:
            return forwarded[:MAX_KEY_LENGTH]
    return peer[:MAX_KEY_LENGTH]
