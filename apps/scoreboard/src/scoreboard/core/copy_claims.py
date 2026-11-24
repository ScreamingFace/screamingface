"""The port for the claim of a frozen copy (OME-1947).

The scoreboard tells the AI Gateway that a Score uses a frozen copy. The gateway then keeps that
copy. The adapter `scoreboard.gateway_copy_claims` implements the port.

FEATURE (OME-1947): the claim pass sends one claim for the copy of each stored Score. It has two
callers: ClaimPassTask (the lifespan starts it) and the command scoreboard.claim_copies
(contracts.md K9).

INVARIANT: this module imports no HTTP library, no model and no route (contracts.md K10).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class ClaimResult(StrEnum):
    """The result of one claim. Each answer that is not exact is UNAVAILABLE."""

    CLAIMED = "claimed"
    ALREADY = "already"
    NOT_SEALED = "not_sealed"
    ABANDONED = "abandoned"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


KEPT: frozenset[ClaimResult] = frozenset({ClaimResult.CLAIMED, ClaimResult.ALREADY})
"""The results that let a Score keep its frozen copy."""


class CopyClaims(Protocol):
    """Sends the claim of one frozen copy to the AI Gateway."""

    async def claim(self, copy_id: str) -> ClaimResult: ...

    async def aclose(self) -> None: ...


Sleep = Callable[[float], Awaitable[None]]
ReadRows = Callable[[], Awaitable[list[tuple[str, str]]]]

# WHY bound at import: a later global patch of asyncio.sleep must not change the wait of the task.
_ASYNC_SLEEP: Sleep = asyncio.sleep
_TASK_NAME = "frozen-copy-claim-pass"
RETRY_S = 600.0
"""The wait before a new pass after a pass that stopped (prd/score-claim.md C20)."""


@dataclass(frozen=True, slots=True)
class ScoreClaim:
    """The claim of the copy of one Score. `result` is None in a dry run."""

    score_id: str
    frozen_copy_id: str
    result: ClaimResult | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "score_id": self.score_id,
            "frozen_copy_id": self.frozen_copy_id,
            "result": None if self.result is None else self.result.value,
        }


class GatewayUnavailable(Exception):
    """The gateway did not answer one claim, and the pass stopped at that Score.

    `results` holds the claims of the pass up to the stop. The last one is UNAVAILABLE.
    """

    def __init__(self, results: list[ScoreClaim]) -> None:
        super().__init__(
            f"the gateway did not answer: the pass stopped after {len(results)} claims"
        )
        self.results = results


def count_results(results: Sequence[ScoreClaim]) -> dict[str, int]:
    """The count of each result, sorted by name. A dry-run row has no result and is not counted."""
    counts = Counter(claim.result.value for claim in results if claim.result is not None)
    return dict(sorted(counts.items()))


def not_kept(results: Sequence[ScoreClaim]) -> list[ScoreClaim]:
    """The claims with a result that does not keep the copy. A dry-run row is not in the list."""
    return [claim for claim in results if claim.result is not None and claim.result not in KEPT]


async def run_claim_pass(claims: CopyClaims, rows: Sequence[tuple[str, str]]) -> list[ScoreClaim]:
    """Send one claim for each (score id, copy id) row, one at a time, in the order of the rows.

    Raises GatewayUnavailable at the first UNAVAILABLE result.
    """
    results: list[ScoreClaim] = []
    for score_id, copy_id in rows:
        result = await claims.claim(copy_id)
        results.append(ScoreClaim(score_id, copy_id, result))
        if result is ClaimResult.UNAVAILABLE:
            raise GatewayUnavailable(results)
    return results


def _report(results: list[ScoreClaim]) -> None:
    # INVARIANT: ids and results only, never a user identity (prd/score-claim.md C21).
    logger.info(
        "claim pass done: scores=%d results=%s", len(results), json.dumps(count_results(results))
    )
    lost = not_kept(results)
    if lost:
        logger.warning(
            "claim pass: %d scores name a frozen copy that is not kept: %s",
            len(lost),
            json.dumps([claim.as_dict() for claim in lost]),
        )


class ClaimPassTask:
    """One owned task that runs the claim pass until one pass is complete, then ends."""

    def __init__(
        self,
        claims: CopyClaims,
        read_rows: ReadRows,
        *,
        retry_s: float = RETRY_S,
        sleep: Sleep | None = None,
    ) -> None:
        self._claims = claims
        self._read_rows = read_rows
        self._retry_s = retry_s
        self._sleep = sleep if sleep is not None else _ASYNC_SLEEP
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the task. A task that runs is left alone."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(self._loop(), name=_TASK_NAME)

    async def stop(self) -> None:
        """Cancel the task and wait until it ended. It does not wait for the pass to complete."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        # WHY asyncio.wait: it waits for the end of the task and catches no CancelledError.
        await asyncio.wait({task})

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    async def _loop(self) -> None:
        while not await self._attempt():
            await self._sleep(self._retry_s)

    async def _attempt(self) -> bool:
        # INVARIANT: catch Exception only, never CancelledError. A cancel at shutdown must end the
        # task (prd/score-claim.md C20, C23).
        try:
            results = await run_claim_pass(self._claims, await self._read_rows())
        except GatewayUnavailable:
            logger.warning(
                "claim pass stopped: the gateway did not answer; next pass in %g s", self._retry_s
            )
            return False
        except Exception as exc:
            # WHY the type only (owner decision Q29): the error text can hold row data.
            logger.error(
                "claim pass stopped: error=%s; next pass in %g s",
                type(exc).__name__,
                self._retry_s,
            )
            return False
        _report(results)
        return True
