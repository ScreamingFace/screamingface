"""A board that turns private between the resolver's read and the signature (E14, OME-894).

FEATURE: OME-1307 (E14) replay grants. STORY: as Ana I make my board private; a grant for Bruno
must not leave after that, even when the flip lands inside his one request.
INVARIANT (OME-894): the route re-reads `visibility` for a non-owner as its last await before
`signer.sign`. An owner needs no re-check: she may replay her own run on a private board.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from scoreboard.scores.models import Benchmark
from tests.unit.replay._helpers import granted_result_id, grants_counted, request_grant
from tests.unit.replay.conftest import SeedResult, SpySigner
from tests.unit.submissions._receipts import ANA, BRUNO

pytestmark = pytest.mark.asyncio


class _FlipAfterResolve:
    """Wraps the real resolver: it answers, then the board turns private (the seed job's flip)."""

    def __init__(self, inner: Any, board_id: str) -> None:
        self._inner = inner
        self._board_id = board_id

    async def resolve(self, *args: Any, **kwargs: Any) -> Any:
        resolved = await self._inner.resolve(*args, **kwargs)
        await Benchmark.filter(id=self._board_id).update(visibility="private")
        return resolved


async def test_a_non_owner_gets_no_grant_when_the_board_turns_private_after_the_resolver(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, seed_result: SeedResult, spy: SpySigner
) -> None:
    seeded = await seed_result(reporter=ANA)
    unknown = await request_grant(
        grant_cf_client, "result:00000000-0000-0000-0000-000000000000", user=BRUNO
    )
    grant_cf_app.state.replay_resolver = _FlipAfterResolve(
        grant_cf_app.state.replay_resolver, "pub"
    )

    response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=BRUNO)

    assert response.status_code == 404
    assert response.content == unknown.content
    assert response.headers["cache-control"] == "private, no-store"
    assert spy.calls == []
    assert grants_counted(grant_cf_app, "issued") == 0
    assert grants_counted(grant_cf_app, "not_found") == 2


async def test_the_owner_still_gets_a_grant_when_the_board_turns_private_after_the_resolver(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, seed_result: SeedResult, spy: SpySigner
) -> None:
    seeded = await seed_result(reporter=ANA)
    grant_cf_app.state.replay_resolver = _FlipAfterResolve(
        grant_cf_app.state.replay_resolver, "pub"
    )

    response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=ANA)

    assert granted_result_id(response) == seeded.result_id
    assert len(spy.calls) == 1


async def test_a_non_owner_still_gets_a_grant_when_the_board_stays_public(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, seed_result: SeedResult, spy: SpySigner
) -> None:
    seeded = await seed_result(reporter=ANA)

    response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=BRUNO)

    assert granted_result_id(response) == seeded.result_id
    assert len(spy.calls) == 1
