"""The anonymous budget, and the two ways a rate limit becomes decoration.

Spec §10 names both directly: rotating the client-IP header must not reset the budget, and
filling the key table must throttle rather than release budgets. Everything else here is the
arithmetic those two rest on.
"""

from __future__ import annotations

from ipaddress import ip_network

from report_intake.identity.rate_limit import (
    CLIENT_IP_HEADER,
    MAX_KEY_LENGTH,
    TokenBucketLimiter,
    rate_limit_key,
)

_MESH = (ip_network("10.0.0.0/8"),)


class _Clock:
    """A hand-wound monotonic clock: the refill is arithmetic, and sleeping to observe it would
    make the suite slow and flaky in exchange for nothing."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(clock: _Clock, **overrides: int) -> TokenBucketLimiter:
    settings: dict[str, int] = {"limit": 30, "window_s": 60, "burst": 5, "max_keys": 100}
    settings.update(overrides)
    return TokenBucketLimiter(clock=clock, **settings)


def test_a_caller_may_burst_and_is_then_held_to_the_sustained_rate() -> None:
    """The two numbers answer different questions: the burst is what a double-click needs, the
    rate is what a submission loop runs into."""
    limiter = _limiter(_Clock(), burst=3)

    assert [limiter.check("10.1.2.3").allowed for _ in range(4)] == [True, True, True, False]


def test_a_throttled_caller_is_told_how_long_to_wait() -> None:
    """A `429` with no usable backoff hint is answered by an immediate retry, which is the
    behaviour the limit exists to stop."""
    limiter = _limiter(_Clock(), limit=30, window_s=60, burst=1)
    limiter.check("10.1.2.3")

    decision = limiter.check("10.1.2.3")

    assert not decision.allowed
    # 30 per 60 s is one token every 2 s, and the hint is rounded up rather than truncated to 0.
    assert decision.retry_after_s == 2


def test_the_budget_refills_over_the_window() -> None:
    clock = _Clock()
    limiter = _limiter(clock, limit=30, window_s=60, burst=2)
    limiter.check("10.1.2.3")
    limiter.check("10.1.2.3")
    assert not limiter.check("10.1.2.3").allowed

    clock.advance(2.0)

    assert limiter.check("10.1.2.3").allowed


def test_the_bucket_never_refills_past_its_burst() -> None:
    """Otherwise an idle caller banks a window's worth of requests and spends them at once, which
    is exactly the spike the burst is supposed to bound."""
    clock = _Clock()
    limiter = _limiter(clock, burst=3)
    limiter.check("10.1.2.3")
    clock.advance(3600.0)

    assert [limiter.check("10.1.2.3").allowed for _ in range(4)] == [True, True, True, False]


def test_two_callers_do_not_share_a_budget() -> None:
    limiter = _limiter(_Clock(), burst=1)
    limiter.check("10.1.2.3")

    assert limiter.check("10.1.2.4").allowed


def test_a_full_key_table_throttles_a_new_caller_rather_than_evicting_an_old_one() -> None:
    """Spec §10, and the reason overflow is not evict-oldest: evicting would make filling the
    table the way to clear somebody else's window."""
    limiter = _limiter(_Clock(), burst=1, max_keys=2)
    limiter.check("10.0.0.1")
    limiter.check("10.0.0.2")

    assert not limiter.check("10.0.0.3").allowed
    # The two that were already throttled still are: nothing was released to make room.
    assert not limiter.check("10.0.0.1").allowed
    assert not limiter.check("10.0.0.2").allowed


def test_a_key_that_has_refilled_to_capacity_may_be_forgotten_to_make_room() -> None:
    """The one eviction rule that releases no budget: a bucket at capacity is indistinguishable
    from a key that has never been seen, because that is exactly what a new key is handed."""
    clock = _Clock()
    limiter = _limiter(clock, limit=30, window_s=60, burst=1, max_keys=1)
    limiter.check("10.0.0.1")
    clock.advance(120.0)

    assert limiter.check("10.0.0.2").allowed

    clock.advance(120.0)

    # And the forgotten key is back to a full bucket, which is what it would have refilled to.
    assert limiter.check("10.0.0.1").allowed


def test_the_key_is_the_peer_by_default() -> None:
    key = rate_limit_key({}, "10.1.2.3", _MESH, trust_client_ip_header=False)

    assert key == "10.1.2.3"


def test_rotating_the_client_ip_header_does_not_reset_the_budget() -> None:
    """Spec §10. Trusting the header by default would mean trusting it always — the mesh proxy is
    the peer on every request — so a rotated header would yield a fresh bucket per request."""
    limiter = _limiter(_Clock(), burst=1)
    peer = "10.1.2.3"

    decisions = [
        limiter.check(
            rate_limit_key(
                {CLIENT_IP_HEADER: f"203.0.113.{n}"},
                peer,
                _MESH,
                trust_client_ip_header=False,
            )
            or ""
        ).allowed
        for n in range(3)
    ]

    assert decisions == [True, False, False]


def test_the_client_ip_header_is_read_only_when_the_operator_opted_in() -> None:
    keyed_off = rate_limit_key(
        {CLIENT_IP_HEADER: "203.0.113.7"}, "10.1.2.3", _MESH, trust_client_ip_header=False
    )
    keyed_on = rate_limit_key(
        {CLIENT_IP_HEADER: "203.0.113.7"}, "10.1.2.3", _MESH, trust_client_ip_header=True
    )

    assert keyed_off == "10.1.2.3"
    assert keyed_on == "203.0.113.7"


def test_the_client_ip_header_is_ignored_from_a_peer_outside_the_mesh() -> None:
    """The second guard on the opt-in. Without it, opting in would be equivalent to trusting the
    header from anyone who can reach the port."""
    key = rate_limit_key(
        {CLIENT_IP_HEADER: "203.0.113.7"}, "198.51.100.4", _MESH, trust_client_ip_header=True
    )

    assert key == "198.51.100.4"


def test_a_blank_client_ip_header_falls_back_to_the_peer() -> None:
    key = rate_limit_key({CLIENT_IP_HEADER: "  "}, "10.1.2.3", _MESH, trust_client_ip_header=True)

    assert key == "10.1.2.3"


def test_a_key_from_a_header_is_bounded() -> None:
    """Under the opt-in a caller supplies part of the key, and an unbounded one would make the
    table's memory a function of what a caller sends rather than of `anon_rate_max_keys`."""
    key = rate_limit_key(
        {CLIENT_IP_HEADER: "x" * 5000}, "10.1.2.3", _MESH, trust_client_ip_header=True
    )

    assert key is not None and len(key) == MAX_KEY_LENGTH


def test_a_request_with_no_visible_peer_has_no_key() -> None:
    """`None` is a refusal, not an exemption: an unattributable unauthenticated write is refused
    rather than admitted under a shared bucket."""
    assert rate_limit_key({}, None, _MESH, trust_client_ip_header=False) is None
