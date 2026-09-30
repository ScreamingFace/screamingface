"""A board that turns private during a submit gives no public data (OME-894, SB-submit owns it).

FEATURE: OME-1307 (E14). `RegistryService.resolve_for_submit` takes `board_visibility` as an
argument and is on the visibility-exit guard allowlist under REGISTRY INPUT: the caller owns the
revalidation. SB-submit does it twice: the row lock inside the write transaction (the decision and
the write see one state), and `turned_private` before any public answer leaves (the response).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.routes.scores import VISIBILITY_CHANGED_DETAIL
from scoreboard.scores.cluster_store import ClusterStore
from scoreboard.scores.models import Benchmark, ReportedResult, Score, System
from scoreboard.scores.store import ScoreStore
from tests.unit.submissions._receipts import ANA, BRUNO, post_score

pytestmark = pytest.mark.asyncio


async def _flip_to_private() -> None:
    await Benchmark.filter(id="pub").update(visibility="private")


async def test_a_board_that_turns_private_between_the_read_and_the_write_is_refused(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ScoreStore.lock_visibility

    async def flip_then_lock(self: ScoreStore, *args: Any, **kwargs: Any) -> None:
        await _flip_to_private()
        await real(self, *args, **kwargs)

    monkeypatch.setattr(ScoreStore, "lock_visibility", flip_then_lock)

    response = await post_score(clustered_cf_client)

    assert response.status_code == 409
    assert response.json() == {"detail": VISIBILITY_CHANGED_DETAIL}
    # Nothing is written under the rules of a board that changed.
    assert await Score.all().count() == 0
    assert await ReportedResult.all().count() == 0
    assert await System.all().count() == 0


@pytest.mark.parametrize("scenario", ["new-head", "joins-another-head", "idempotent-hit"])
async def test_a_board_that_turns_private_before_the_answer_gives_no_public_data(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    # The write finished while the board was public. The board then turns private, and the answer
    # of a submit that returns a head (Ana's head, for Bruno) must not leave.
    if scenario != "new-head":
        await post_score(clustered_cf_client, user=ANA, key="ana-run")
    real = ClusterStore.submit

    async def flip_after(self: ClusterStore, *args: Any, **kwargs: Any) -> Any:
        outcome = await real(self, *args, **kwargs)
        await _flip_to_private()
        return outcome

    monkeypatch.setattr(ClusterStore, "submit", flip_after)
    who, key, score = {
        "new-head": (ANA, None, 0.75),
        "joins-another-head": (BRUNO, "bruno-run", 0.5),
        "idempotent-hit": (BRUNO, "ana-run", 0.75),
    }[scenario]

    response = await post_score(clustered_cf_client, user=who, key=key, score=score)

    assert response.status_code == 409
    assert response.json() == {"detail": VISIBILITY_CHANGED_DETAIL}
    for leaked in ("url4_expression", "reported_result", "kevins-best", "submitted_by"):
        assert leaked not in response.text


async def test_a_private_board_answer_is_not_refused_for_being_private(
    clustered_cf_client: AsyncClient,
) -> None:
    # The re-check guards a PUBLIC decision only. A private write returns the caller's own data.
    response = await post_score(clustered_cf_client, benchmark_id="priv", user=ANA)

    assert response.status_code == 201
