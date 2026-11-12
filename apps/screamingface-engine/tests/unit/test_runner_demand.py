"""`claimable_demand`: the runner-pool scale signal from per-bucket readings (spec D1)."""

import math

import pytest

from screamingface_engine.runner_demand import RunnerDemand, claimable_demand
from screamingface_engine.runner_queue import BucketReading


def _r(running: int, queued: int, cap: int) -> BucketReading:
    return BucketReading(running=running, queued=queued, max_ack_pending=cap)


@pytest.mark.parametrize("n", [1, 4, 8])
def test_the_spec_scenario_adds_one_pod_for_a_third_caller(n: int) -> None:
    # A and B are at their cap of 4 each, with n more queued behind it. C has n queued and no
    # headroom limit. Only min(n, 4) of C's runs can start, so one new pod suffices.
    result = claimable_demand([_r(4, 4, 4), _r(4, 4, 4), _r(0, n, 4)])

    assert result == RunnerDemand(
        demand=8 + min(n, 4),
        running=8,
        claimable=min(n, 4),
        queued=8 + n,
        unbound_buckets=0,
    )
    assert math.ceil(result.demand / 4) == 3


def test_an_empty_queue_is_zero() -> None:
    result = claimable_demand([_r(0, 0, 4)] * 16)

    assert result == RunnerDemand(demand=0, running=0, claimable=0, queued=0, unbound_buckets=0)


def test_no_readings_is_zero() -> None:
    result = claimable_demand([])

    assert result == RunnerDemand(demand=0, running=0, claimable=0, queued=0, unbound_buckets=0)


def test_partial_headroom_limits_the_claimable_runs() -> None:
    result = claimable_demand([_r(2, 5, 4)])

    assert result.demand == 4
    assert result.running == 2
    assert result.claimable == 2
    assert result.queued == 5


@pytest.mark.parametrize("cap", [-1, 0])
def test_no_cap_makes_every_queued_run_claimable(cap: int) -> None:
    result = claimable_demand([_r(3, 7, cap)])

    assert result.claimable == 7
    assert result.demand == 10


def test_an_unbound_bucket_counts_and_adds_nothing() -> None:
    result = claimable_demand([None, _r(1, 1, 4)])

    assert result.unbound_buckets == 1
    assert result.demand == 2
    assert result.running == 1
    assert result.claimable == 1


def test_running_above_a_lowered_cap_gives_no_negative_headroom() -> None:
    result = claimable_demand([_r(6, 3, 4)])

    assert result.claimable == 0
    assert result.demand == 6
