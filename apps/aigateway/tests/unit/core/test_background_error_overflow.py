"""OME-1026 final pass F6 — the background-error sink must be loud even when it overflows.

FEATURE: a background programming error always fails something. The retention sink
exists so a bug in a refresh nobody awaited — the suite's no-egress tripwire above
all — cannot scroll past in a log while the run stays green.

STORY: as the engineer reading a green suite I need that green to mean "no test
reached the real internet", including the run where fifty tests tried at once.

INVARIANT (the hole this file closes): the sink retains a BOUNDED number of
exceptions, so past the cap it can only count. A check that inspected the retained
list alone therefore passed green precisely in the worst case — many failures — and
``take_unexpected`` reset that count on its way out, erasing the only evidence that
anything had been dropped.
"""

from __future__ import annotations

import asyncio

import pytest

from aigateway.core.background_error_sink import (
    _MAX_RETAINED_UNEXPECTED,
    assert_no_unexpected,
    dropped_unexpected,
    mark_observed,
    reset_unexpected,
    take_unexpected,
)
from aigateway.core.background_refresh import (
    BackgroundRefreshManager,
)
from aigateway.core.parameter_discovery import DiscoveryError

_EGRESS = "test attempted real discovery egress to https://api.example.invalid/v1/models"


@pytest.fixture(autouse=True)
def _isolated_sink():
    """Both channels start and end empty, so a case measures only its own errors."""
    reset_unexpected()
    yield
    reset_unexpected()


async def _fail_many(
    count: int, *, error: type[BaseException] = AssertionError
) -> list[asyncio.Task]:
    """Drive ``count`` DISTINCT background failures through the real manager.

    Returns the tasks: since the sink retains a sanitized RECORD rather than the
    exception (OME-1026 adversarial B3), a test that wants to ``mark_observed`` an
    error has to hold the exception itself — which is exactly what a real awaiting
    caller does.
    """
    manager = BackgroundRefreshManager[tuple[str, int]](max_inflight=count + 1)

    async def _boom(index: int) -> None:
        raise error(f"{_EGRESS}#{index}")

    tasks = []
    for index in range(count):
        task = manager.start_or_join(("k", index), lambda index=index: _boom(index))
        assert task is not None
        tasks.append(task)
    await manager.drain()
    return tasks


# ── the bound, and the counter that survives it ───────────────────────────────


@pytest.mark.asyncio
async def test_retention_is_bounded_and_the_overflow_is_counted() -> None:
    """40 failures against a cap of 32: the sink keeps 32 objects and counts 8."""
    await _fail_many(40)

    assert dropped_unexpected() == 40 - _MAX_RETAINED_UNEXPECTED
    assert len(take_unexpected()) == _MAX_RETAINED_UNEXPECTED


@pytest.mark.asyncio
async def test_forty_background_errors_cannot_pass_green() -> None:
    """The headline case. Overflow must fail, and must SAY it overflowed."""
    await _fail_many(40)

    with pytest.raises(AssertionError) as caught:
        assert_no_unexpected("forty failures")

    message = str(caught.value)
    # The report names the bug CLASS and the identity, and (adversarial B3) never the
    # exception's own text: that may carry upstream content, and this message lands in
    # CI logs. "Which bug, whose identity" is what an operator acts on.
    assert "AssertionError" in message, message
    assert "('k', 0)" in message, message
    assert _EGRESS not in message, message
    # INVARIANT: the dropped count is reported, not merely used as a boolean — an
    # operator reading this failure must be able to tell 33 failures from 3 000.
    assert "8" in message, message


@pytest.mark.asyncio
async def test_overflow_alone_fails_even_when_every_retained_error_was_observed() -> None:
    """The exact shape that used to pass: nothing retained, yet errors were dropped.

    # WHY this is reachable: ``mark_observed`` removes an error that reached a
    # caller, so a burst where the retained 32 were all awaited empties the list
    # while the dropped ones — which nobody ever saw — are the real evidence.
    """
    tasks = await _fail_many(40)
    take_unexpected()
    for task in tasks:
        exc = task.exception()
        assert exc is not None
        mark_observed(exc)

    assert dropped_unexpected() == 8, "the overflow evidence must survive observation"
    with pytest.raises(AssertionError, match="dropped"):
        assert_no_unexpected("only overflow left")


# ── evidence must not vanish quietly ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_take_unexpected_does_not_erase_the_overflow_evidence() -> None:
    """Draining the retained objects is not a statement about the dropped ones."""
    await _fail_many(40)

    take_unexpected()

    assert dropped_unexpected() == 8, "take_unexpected must not silently reset the count"


@pytest.mark.asyncio
async def test_a_failing_assertion_clears_both_channels() -> None:
    """Failing IS draining: one overflow must not cascade into every later test."""
    await _fail_many(40)
    with pytest.raises(AssertionError):
        assert_no_unexpected("first")

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0
    assert_no_unexpected("second")  # must be silent now


@pytest.mark.asyncio
async def test_reset_clears_both_channels() -> None:
    """The isolation primitive the per-test fixture needs."""
    await _fail_many(40)

    reset_unexpected()

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0


# ── what must NOT be counted ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ordinary_discovery_failures_never_reach_either_channel() -> None:
    """A DiscoveryError is a normal failed attempt, however many of them there are."""
    await _fail_many(40, error=_SanitizedFailure)

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0
    assert_no_unexpected("forty upstream failures")


class _SanitizedFailure(DiscoveryError):
    """A DiscoveryError constructible from one message, for the case above."""

    def __init__(self, message: str) -> None:
        super().__init__("bad_status")


# ── the suite-wide wiring, not just the primitive ─────────────────────────────


@pytest.mark.asyncio
async def test_the_suite_wide_observation_point_fails_on_a_leaked_egress_assertion() -> None:
    """The teardown hook itself, driven directly.

    # WHY the fixture delegates to a plain function: a failure path that only runs
    # during teardown is a failure path no test can pin. This drives the same call the
    # autouse fixture makes.
    """
    from tests.conftest import observe_background_discovery_errors

    await _fail_many(1)

    # Matched on the sanitized report, not on the exception's text (adversarial B3):
    # the type name is what identifies the tripwire now, and the key says whose refresh.
    with pytest.raises(AssertionError, match=r"AssertionError"):
        observe_background_discovery_errors("test_something")


def test_the_background_error_observation_is_autouse() -> None:
    """Suite-WIDE means autouse: an opt-in check is not a guarantee."""
    from tests import conftest

    # pytest 9 wraps a fixture in ``FixtureFunctionDefinition``; its marker carries the
    # declaration. Read from the installed object rather than assumed, so an upgrade
    # that moves it fails HERE rather than silently reporting "autouse" forever.
    def _autouse(fixture: object) -> bool:
        return bool(fixture._fixture_function_marker.autouse)  # type: ignore[attr-defined]

    assert _autouse(conftest._background_discovery_errors)
    assert _autouse(conftest._anthropic_private_discovery_disabled)
    # The opt-in half must NOT be autouse, or "explicitly enabled" would mean nothing.
    assert not _autouse(conftest.anthropic_live_discovery)


@pytest.mark.asyncio
async def test_a_cancelled_refresh_is_not_an_error_report() -> None:
    """Supersede and shutdown cancel tasks deliberately; that is not a bug."""
    manager = BackgroundRefreshManager[str](max_inflight=4)
    started = asyncio.Event()

    async def _parked() -> None:
        started.set()
        await asyncio.sleep(3600)

    task = manager.start_or_join("parked", _parked)
    assert task is not None
    await started.wait()
    assert manager.cancel("parked") is True
    await manager.drain()

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0
