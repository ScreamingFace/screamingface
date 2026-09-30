"""PB-1, PB-2, PB-2a, PB-2b, PB-6, PB-19 — `POST /v1/results/{id}/publish` (C10).

FEATURE: OME-1307 (E14). D5: the main path runs `cloudflare_headers` and every call sends
`as_user(...)`. Only PB-2a uses the `disabled` fallback.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response

from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import Benchmark, CacheVersionPublication
from tests.unit.publish._fakes import NOW, Seeded
from tests.unit.publish._rows import seed_rows
from tests.unit.submissions._receipts import ANA, BRUNO, as_user

pytestmark = pytest.mark.asyncio

Seed = Callable[..., Awaitable[Seeded]]


async def _publish(client: AsyncClient, result_id: str, user: str | None = ANA) -> Response:
    headers = as_user(user) if user is not None else {}
    return await client.post(f"/v1/results/{result_id}/publish", headers=headers)


async def _state(result_id: str) -> str:
    return (await CacheVersionPublication.get(result_id=result_id)).state


async def test_publish_private_board_or_not_redistributable_409_reason(
    publish_client: AsyncClient, seed_result: Seed
) -> None:
    gated = await seed_result(publish_client, board="gated")
    private = await seed_result(publish_client, board="priv")
    no_receipt = await seed_result(publish_client, board="pub", with_receipt=False)

    for seeded, reason in (
        (gated, "not_redistributable"),
        (private, "private_board"),
        (no_receipt, "no_cache_version"),
    ):
        response = await _publish(publish_client, seeded.result_id)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "not_publishable"
        assert detail["reason"] == reason
    assert await _state(gated.result_id) == "private"
    assert await _state(private.result_id) == "private"


async def test_publish_by_non_reporter_403_private_404(
    publish_client: AsyncClient, seed_result: Seed
) -> None:
    public = await seed_result(publish_client, board="pub")
    private = await seed_result(publish_client, board="priv")

    not_owner = await _publish(publish_client, public.result_id, BRUNO)
    hidden = await _publish(publish_client, private.result_id, BRUNO)
    unknown = await _publish(publish_client, str(uuid.uuid4()), BRUNO)

    assert not_owner.status_code == 403
    assert not_owner.json()["detail"]["code"] == "not_result_owner"
    assert hidden.status_code == 404
    assert unknown.status_code == 404
    # INVARIANT (OME-894): a private result of another caller is indistinguishable from no result.
    assert hidden.json() == unknown.json() == {"detail": "result not found"}
    assert await _state(public.result_id) == "private"


async def test_publish_in_disabled_mode_is_503(publish_disabled_client: AsyncClient) -> None:
    seeded = await seed_rows(board="pub")

    plain = await publish_disabled_client.post(f"/v1/results/{seeded.result_id}/publish")
    forged = await publish_disabled_client.post(
        f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA)
    )

    for response in (plain, forged):
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "publish_unavailable"
    assert await _state(seeded.result_id) == "private"


async def test_publish_needs_verified_identity(
    publish_client: AsyncClient, publish_untrusted_client: AsyncClient, seed_result: Seed
) -> None:
    seeded = await seed_result(publish_client, board="pub")

    anonymous = await _publish(publish_client, seeded.result_id, None)
    untrusted = await _publish(publish_untrusted_client, seeded.result_id, ANA)

    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "identity_not_verified"
    assert untrusted.status_code == 403
    assert untrusted.json()["detail"] == UNTRUSTED_PEER_DETAIL
    assert await _state(seeded.result_id) == "private"


async def test_owner_publish_202_requested(publish_client: AsyncClient, seed_result: Seed) -> None:
    seeded = await seed_result(publish_client, board="pub")

    response = await _publish(publish_client, seeded.result_id)

    assert response.status_code == 202
    assert response.json() == {"state": "requested"}
    row = await CacheVersionPublication.get(result_id=seeded.result_id)
    assert row.state == "requested"
    assert row.requested_by == ANA
    assert row.requested_at == NOW
    assert row.release_tag == f"cv-{seeded.version_id}"


async def test_publish_unavailable_503_without_app_config(
    unconfigured_client: AsyncClient, seed_result: Seed
) -> None:
    seeded = await seed_result(unconfigured_client, board="pub")

    response = await _publish(unconfigured_client, seeded.result_id)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "publish_unavailable"
    # PB-19: an unavailable deployment changes nothing.
    assert await _state(seeded.result_id) == "private"


async def test_a_board_that_turns_private_before_the_request_is_refused(
    publish_client: AsyncClient, seed_result: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route re-checks the board after its checks and before it requests anything.

    WHY: the worker copies the cache of this result to a public repository, so a board that
    turned private since the first read must stop the request (visibility-exit rule, OME-894).
    """
    from scoreboard.routes import publish as publish_routes

    seeded = await seed_result(publish_client, board="pub")
    original = publish_routes._load

    async def load_then_flip(result_id: uuid.UUID) -> object:
        loaded = await original(result_id)
        await Benchmark.filter(id="pub").update(visibility="private")
        return loaded

    monkeypatch.setattr(publish_routes, "_load", load_then_flip)

    response = await _publish(publish_client, seeded.result_id)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "private_board"
    assert await _state(seeded.result_id) == "private"


async def test_a_takedown_that_wins_the_race_makes_the_publish_409_withdrawn(
    publish_client: AsyncClient, seed_result: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scoreboard.routes import publish as publish_routes

    seeded = await seed_result(publish_client, board="pub")
    original = publish_routes._load

    async def load_then_withdraw(result_id: uuid.UUID) -> object:
        loaded = await original(result_id)
        await CacheVersionPublication.filter(result_id=result_id).update(state="withdrawn")
        return loaded

    monkeypatch.setattr(publish_routes, "_load", load_then_withdraw)

    response = await _publish(publish_client, seeded.result_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "withdrawn"
    assert await _state(seeded.result_id) == "withdrawn"
