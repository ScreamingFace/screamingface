"""The guard tells the code it re-runs that this is a retry, and which failure caused it.

STORY (OME-1533): a retry is only worth paying for when it can get a different answer. url4's
``;retry=`` re-runs the guarded subtree with nothing changed, so a handler that wants a retry to
behave differently (an Engine judge call leaving a response cache after an unparseable reply)
needs to know it IS a retry and what ended the send before. The guard publishes exactly that,
generically: the retry number and the failure's code. It knows nothing about caches.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import RecordingIOLayer

from url4.core.errors import ResolutionError
from url4.dag import GuardNode, GuardRetry, current_guard_retry, run


class _RecordingRetries:
    """A guarded stand-in that fails its first sends with chosen codes, then answers.

    It simulates a subtree whose leaf reads the retry at call time (as the Engine's model
    endpoint does); it does not prove anything about how a real route reaches the leaf.
    """

    deps: dict = {}

    def __init__(self, *failure_codes: str) -> None:
        self._failure_codes: list[str] = list(failure_codes)
        self.seen: list[GuardRetry | None] = []

    async def resolve(self, inputs: object, ctx: object) -> str:
        """Record the retry this send runs under, then fail or answer."""
        self.seen.append(current_guard_retry())
        if self._failure_codes:
            raise ResolutionError("send failed", code=self._failure_codes.pop(0))
        return "answer"


@pytest.mark.asyncio
async def test_a_first_send_reads_exactly_like_unguarded_code() -> None:
    # WHY: a reader that changes behaviour on "this is a retry" must leave every first send
    # alone, so a first send publishes nothing at all.
    inner = _RecordingRetries()

    assert await run(GuardNode(inner, retries=2), RecordingIOLayer()) == "answer"
    assert inner.seen == [None]


@pytest.mark.asyncio
async def test_each_retry_carries_the_code_of_the_failure_that_caused_it() -> None:
    # WHY: a reader must tell a retry after an unusable reply from a retry after a 5xx; the
    # code of the failure that caused THIS retry is what distinguishes them.
    inner = _RecordingRetries("judge_reply_invalid", "upstream_error")

    assert await run(GuardNode(inner, retries=2), RecordingIOLayer()) == "answer"
    assert inner.seen == [
        None,
        GuardRetry(number=1, failure_code="judge_reply_invalid"),
        GuardRetry(number=2, failure_code="upstream_error"),
    ]


@pytest.mark.asyncio
async def test_unguarded_code_sees_no_retry() -> None:
    inner = _RecordingRetries()

    assert await run(inner, RecordingIOLayer()) == "answer"
    assert inner.seen == [None]


@pytest.mark.asyncio
async def test_a_nested_guards_first_send_still_sees_the_outer_retry() -> None:
    # WHY: when the outer guard re-runs its subtree, a nested guard's first send IS a re-send
    # of that subtree; hiding the outer retry there would undo what the outer retry asked for.
    inner = _RecordingRetries("judge_reply_invalid")

    outer = GuardNode(GuardNode(inner, timeout=5), retries=1)
    assert await run(outer, RecordingIOLayer()) == "answer"
    assert inner.seen == [None, GuardRetry(number=1, failure_code="judge_reply_invalid")]


@pytest.mark.asyncio
async def test_a_nested_guards_own_retry_replaces_the_outer_one() -> None:
    # WHY: nearest wins — the nested guard is the one re-running its subtree, and ITS failure is
    # the one that caused the re-run.
    inner = _RecordingRetries("judge_reply_invalid", "upstream_error")

    outer = GuardNode(GuardNode(inner, retries=1), retries=1)
    assert await run(outer, RecordingIOLayer()) == "answer"
    assert inner.seen == [
        None,
        GuardRetry(number=1, failure_code="judge_reply_invalid"),
        GuardRetry(number=1, failure_code="upstream_error"),
    ]


@pytest.mark.asyncio
async def test_the_retry_is_unbound_again_once_the_guard_returns() -> None:
    # WHY: the retry is scoped to the guarded subtree; leaking it past the guard would make the
    # guard's later siblings look like retries.
    inner = _RecordingRetries("upstream_error")

    await run(GuardNode(inner, retries=1), RecordingIOLayer())
    assert current_guard_retry() is None


@pytest.mark.asyncio
async def test_a_timed_out_send_reports_the_timeout_code_to_the_retry() -> None:
    # WHY: ;t= turns a slow send into a transient `timeout` error; the retry must see that code
    # like any other, so a reader can tell "slow" from "unusable".
    class SlowThenFast:
        deps: dict = {}

        def __init__(self) -> None:
            self.seen: list[GuardRetry | None] = []

        async def resolve(self, inputs: object, ctx: object) -> str:
            """Hang on the first send so the guard times it out; answer on the retry."""
            self.seen.append(current_guard_retry())
            if len(self.seen) == 1:
                await asyncio.sleep(10)
            return "answer"

    inner = SlowThenFast()
    assert await run(GuardNode(inner, timeout=0.05, retries=1), RecordingIOLayer()) == "answer"
    assert inner.seen == [None, GuardRetry(number=1, failure_code="timeout")]
