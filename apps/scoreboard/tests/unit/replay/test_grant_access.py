"""RP-1, RP-2, RP-2a, RP-3, RP-4d, RP-9 and RP-9a: who may get a grant, and what a refusal says.

FEATURE: OME-1307 (E14) replay grants. INVARIANT (OME-894): a 404 never confirms that a private or
gated result exists, and nothing is signed for a pin that does not resolve. STORY: as Bruno I ask
to replay Ana's run; I get a grant only when Ana's run is public and redistributable.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from scoreboard.core.registry import InvalidPin, RevisionPin
from scoreboard.core.replay.pins import ResultPin, ScorePin, parse_replay_pin
from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score
from tests.unit.replay._helpers import decode_grant, grants_counted, request_grant
from tests.unit.replay.conftest import GrantKey, SeedResult, SpySigner
from tests.unit.submissions._receipts import ANA, BRUNO, URL4_A

pytestmark = pytest.mark.asyncio

NOT_FOUND = {
    "detail": {
        "code": "replay_pin_not_found",
        "message": "the pin names no run you may replay",
    }
}


async def test_non_owner_private_pin_404_no_leak(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    seeded = await seed_result(benchmark="priv", reporter=ANA)

    bruno = await request_grant(
        grant_cf_client, f"result:{seeded.result_id}", user=BRUNO, benchmark_id="priv"
    )
    unknown = await request_grant(
        grant_cf_client, f"result:{uuid.uuid4()}", user=BRUNO, benchmark_id="priv"
    )
    ana = await request_grant(
        grant_cf_client, f"result:{seeded.result_id}", user=ANA, benchmark_id="priv"
    )

    assert bruno.status_code == 404
    assert bruno.json() == unknown.json() == NOT_FOUND
    assert bruno.content == unknown.content
    for header in ("cache-control", "vary"):
        assert bruno.headers[header] == unknown.headers[header]
    assert bruno.headers["cache-control"] == "private, no-store"
    assert ana.status_code == 200


async def test_non_owner_non_redistributable_public_pin_404_owner_ok(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    seeded = await seed_result(benchmark="gated", reporter=ANA)
    pin = f"result:{seeded.result_id}"

    bruno = await request_grant(grant_cf_client, pin, user=BRUNO, benchmark_id="gated")
    ana = await request_grant(grant_cf_client, pin, user=ANA, benchmark_id="gated")

    assert bruno.status_code == 404
    assert bruno.json() == NOT_FOUND
    assert ana.status_code == 200
    assert ana.json()["result_id"] == seeded.result_id


async def test_disabled_fallback_sub_anonymous_public_ok_gated_and_private_404(
    grant_client: AsyncClient, grant_key: GrantKey
) -> None:
    # WHY models and not a submit: a `disabled` submit cannot set a verified reporter, so the rows
    # are written directly (RP-2a; the only `disabled` test of the grant flow).
    ids: dict[str, str] = {}
    for board in ("pub", "gated", "priv"):
        head = await Score.create(
            benchmark_id=board,
            spec_id="kevins-best",
            url4_expression=URL4_A,
            score=0.5,
            total_questions=2,
            correct_questions=1,
            ran_with_providers=["openai"],
        )
        result = await ReportedResult.create(
            head=head,
            is_original=True,
            reporter=ANA,
            score=0.5,
            total_questions=2,
            cache_version_id=uuid.uuid4(),
        )
        ids[board] = str(result.id)

    public = await request_grant(grant_client, f"result:{ids['pub']}", user=None)
    gated = await request_grant(
        grant_client, f"result:{ids['gated']}", user=None, benchmark_id="gated"
    )
    private = await request_grant(
        grant_client, f"result:{ids['priv']}", user=None, benchmark_id="priv"
    )
    forged = await request_grant(
        grant_client, f"result:{ids['gated']}", user=ANA, benchmark_id="gated"
    )

    assert public.status_code == 200
    assert decode_grant(public.json()["grant"], grant_key)["sub"] == "anonymous"
    assert gated.status_code == private.status_code == forged.status_code == 404


async def test_withdrawn_pin_410_for_non_owner_owner_ok(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    public = await seed_result(benchmark="pub", reporter=ANA)
    private = await seed_result(benchmark="priv", reporter=ANA)
    for result_id in (public.result_id, private.result_id):
        await CacheVersionPublication.filter(result_id=result_id).update(state="withdrawn")

    bruno = await request_grant(grant_cf_client, f"result:{public.result_id}", user=BRUNO)
    ana = await request_grant(grant_cf_client, f"result:{public.result_id}", user=ANA)
    hidden = await request_grant(
        grant_cf_client, f"result:{private.result_id}", user=BRUNO, benchmark_id="priv"
    )

    assert bruno.status_code == 410
    assert bruno.json()["detail"]["code"] == "cache_version_withdrawn"
    assert ana.status_code == 200
    # WHY: not_found is answered before withdrawn, so a private result never reveals itself.
    assert hidden.status_code == 404
    assert hidden.json() == NOT_FOUND


async def test_verified_identity_required_in_cloudflare_mode(
    grant_cf_app: FastAPI,
    grant_cf_client: AsyncClient,
    grant_untrusted_client: AsyncClient,
    spy: SpySigner,
    seed_result: SeedResult,
) -> None:
    seeded = await seed_result(reporter=ANA)
    pin = f"result:{seeded.result_id}"

    missing = await request_grant(grant_cf_client, pin, user=None)
    untrusted = await request_grant(grant_untrusted_client, pin, user=ANA)

    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "identity_not_verified"
    assert untrusted.status_code == 403
    assert untrusted.json() == {"detail": UNTRUSTED_PEER_DETAIL}
    for response in (missing, untrusted):
        assert response.headers["cache-control"] == "private, no-store"
    assert spy.calls == []
    assert grants_counted(grant_cf_app, "unauthenticated") == 2


async def test_unknown_pin_404_before_run_no_spend(
    grant_cf_app: FastAPI,
    grant_cf_client: AsyncClient,
    spy: SpySigner,
    seed_result: SeedResult,
) -> None:
    # A name whose only result has no cache version never resolves (a run with no receipt).
    await seed_result(reporter=ANA, receipt=False)
    real = await seed_result(reporter=BRUNO, url4=URL4_A, benchmark="other")
    attempts = [
        ("no-such-system", "pub"),
        (f"result:{uuid.uuid4()}", "pub"),
        ("kevins-best", "pub"),
        (f"result:{real.result_id}", "no-such-board"),
    ]

    responses = [
        await request_grant(grant_cf_client, pin, user=BRUNO, benchmark_id=board)
        for pin, board in attempts
    ]

    assert [r.status_code for r in responses] == [404] * 4
    assert all(r.json() == NOT_FOUND for r in responses)
    assert spy.calls == []
    assert grants_counted(grant_cf_app, "not_found") == 4


@pytest.mark.parametrize(
    "pin",
    ["x@r0", "x@2026-13-01", "x@2026-09-01T10:00:00", "result:not-a-uuid", "score:"],
)
async def test_malformed_pin_422_invalid_replay_pin(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, spy: SpySigner, pin: str
) -> None:
    response = await request_grant(grant_cf_client, pin, user=BRUNO)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_replay_pin"
    assert response.headers["cache-control"] == "private, no-store"
    assert spy.calls == []
    assert grants_counted(grant_cf_app, "invalid") == 1


async def test_parse_replay_pin_forms() -> None:
    ident = uuid.uuid4()

    assert parse_replay_pin(f"result:{ident}") == ResultPin(ident)
    assert parse_replay_pin(f"score:{ident}") == ScorePin(ident)
    assert parse_replay_pin("kevins-best@r1") == RevisionPin("kevins-best", 1)
    with pytest.raises(InvalidPin):
        parse_replay_pin("result:not-a-uuid")
