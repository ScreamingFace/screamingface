"""WR-1 .. WR-9 — `PUT /v1/admin/benchmarks/{id}/redistributable` (E14, OME-1307, D6).

FEATURE: OME-1307 (E14) D6, STORY: as an admin, I mark a benchmark redistributable after I check
its licence, and the call leaves an audit line. D5: the main path runs `cloudflare_headers`; only
WR-7 uses the `disabled` fallback.
INVARIANT under test: the route changes one column of a row that exists, never creates a
benchmark, and every attempt (refusals included) leaves one audit line that names the target.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from scoreboard.core.publish.release_body import escape_markdown
from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import Benchmark
from scoreboard.scores.store import ScoreStore
from tests.unit.publish._fakes import Seeded
from tests.unit.publish.conftest import ADMIN
from tests.unit.submissions._receipts import ANA, BRUNO, as_user

pytestmark = pytest.mark.asyncio

Seed = Callable[..., Awaitable[Seeded]]
_AUDIT = "scoreboard.routes.admin"
_REASON = "license: CC-BY-4.0"


async def _put(
    client: AsyncClient,
    benchmark_id: str = "gated",
    *,
    user: str | None = ADMIN,
    body: dict[str, Any] | None = None,
) -> Response:
    payload = body if body is not None else {"redistributable": True, "reason": _REASON}
    headers = as_user(user) if user is not None else {}
    return await client.put(
        f"/v1/admin/benchmarks/{benchmark_id}/redistributable", json=payload, headers=headers
    )


async def _redistributable(benchmark_id: str) -> bool:
    return (await Benchmark.get(id=benchmark_id)).redistributable


def _audit_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _AUDIT and record.getMessage().startswith("admin_action ")
    ]


async def test_admin_sets_redistributable_and_the_row_changes(
    publish_client: AsyncClient,
) -> None:
    response = await _put(publish_client)

    assert response.status_code == 200
    assert response.json() == {"benchmark_id": "gated", "redistributable": True, "changed": True}
    assert (await Benchmark.get(id="gated")).redistributable is True


async def test_same_value_again_is_a_noop_200(publish_client: AsyncClient) -> None:
    first = await _put(publish_client)
    second = await _put(publish_client)

    assert first.json()["changed"] is True
    assert second.status_code == 200
    assert second.json() == {"benchmark_id": "gated", "redistributable": True, "changed": False}
    assert await _redistributable("gated") is True

    back = await _put(
        publish_client, body={"redistributable": False, "reason": "licence withdrawn"}
    )

    assert back.status_code == 200
    assert back.json() == {"benchmark_id": "gated", "redistributable": False, "changed": True}
    assert await _redistributable("gated") is False


async def test_non_admin_is_403_and_nothing_changes(
    publish_client: AsyncClient,
    publish_untrusted_client: AsyncClient,
    no_admin_client: AsyncClient,
) -> None:
    # WHY the admin call first: it proves the route works, so each refusal below is a real refusal.
    baseline = await _put(publish_client, "pub", body={"redistributable": True, "reason": "x"})
    assert baseline.status_code == 200
    assert baseline.json()["changed"] is False

    not_admin = await _put(publish_client, user=BRUNO)
    anonymous = await _put(publish_client, user=None)
    untrusted = await _put(publish_untrusted_client)
    no_allowlist = await _put(no_admin_client)

    assert not_admin.status_code == 403
    assert not_admin.json()["detail"]["code"] == "admin_required"
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "identity_not_verified"
    assert untrusted.status_code == 403
    assert untrusted.json()["detail"] == UNTRUSTED_PEER_DETAIL
    assert no_allowlist.status_code == 503
    assert no_allowlist.json()["detail"]["code"] == "admin_unavailable"
    assert await _redistributable("gated") is False


async def test_unknown_benchmark_is_404_and_no_row_is_created(
    publish_client: AsyncClient,
) -> None:
    response = await _put(publish_client, "nope")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "benchmark_not_found"
    assert await Benchmark.filter(id="nope").exists() is False


async def test_every_attempt_is_audited_with_target_reason_change(
    publish_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_AUDIT)

    await _put(publish_client)
    (ok_line,) = _audit_lines(caplog)
    await _put(publish_client, user=BRUNO)
    refused_line = _audit_lines(caplog)[1]
    await _put(publish_client, "nope")
    missing_line = _audit_lines(caplog)[2]

    assert "admin_action actor=admin@x.org" in ok_line
    assert "benchmark_id=gated" in ok_line
    assert f"reason={escape_markdown(_REASON)}" in ok_line
    assert "outcome=200" in ok_line
    assert ok_line.endswith("change=redistributable=true")
    assert "actor=bruno@y.org" in refused_line
    assert "benchmark_id=gated" in refused_line
    assert "outcome=403" in refused_line
    # require_admin refused before the handler ran, so no change was named.
    assert "change=" not in refused_line
    assert "benchmark_id=nope" in missing_line
    assert "outcome=404" in missing_line
    # WHY the reason and change are set before the store call: a 404 is logged with both.
    assert missing_line.endswith("change=redistributable=true")


@pytest.mark.parametrize(
    "body",
    [
        {"redistributable": True},
        {"redistributable": "yes", "reason": "x"},
        {"redistributable": 1, "reason": "x"},
        {"redistributable": True, "reason": "x", "extra": 1},
        {"redistributable": True, "reason": ""},
    ],
    ids=["no-reason", "string-value", "int-value", "extra-field", "empty-reason"],
)
async def test_bad_body_is_422_and_audited(
    publish_client: AsyncClient, caplog: pytest.LogCaptureFixture, body: dict[str, Any]
) -> None:
    caplog.set_level(logging.INFO, logger=_AUDIT)

    response = await _put(publish_client, body=body)

    assert response.status_code == 422
    (line,) = _audit_lines(caplog)
    assert "outcome=422" in line
    assert await _redistributable("gated") is False


async def test_disabled_mode_is_503(publish_disabled_client: AsyncClient) -> None:
    # The only `disabled` test of this route (D5): a forged header must not make an admin.
    response = await _put(publish_disabled_client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "admin_unavailable"
    assert await _redistributable("gated") is False


async def test_seed_keeps_the_admin_decision(publish_client: AsyncClient) -> None:
    assert (await _put(publish_client)).status_code == 200

    # The seed job runs on every deploy and must not reset an admin decision.
    await ScoreStore().register_benchmark("gated", display_name="Gated")

    assert await _redistributable("gated") is True


async def test_redistributable_unblocks_publish_and_withdraw_line_is_unchanged(
    publish_client: AsyncClient, seed_result: Seed, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = await seed_result(publish_client, board="gated", user=ANA)
    publish_url = f"/v1/results/{seeded.result_id}/publish"

    blocked = await publish_client.post(publish_url, headers=as_user(ANA))

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert (detail["code"], detail["reason"]) == ("not_publishable", "not_redistributable")

    assert (await _put(publish_client)).status_code == 200
    accepted = await publish_client.post(publish_url, headers=as_user(ANA))

    assert accepted.status_code == 202
    assert accepted.json() == {"state": "requested"}

    caplog.set_level(logging.INFO, logger=_AUDIT)
    # WHY: the logging setup may already capture INFO, so the earlier PUT's line is dropped here.
    caplog.clear()
    withdraw = await publish_client.post(
        f"/v1/admin/results/{seeded.result_id}/withdraw",
        json={"reason": "x"},
        headers=as_user(ADMIN),
    )

    assert withdraw.status_code == 200
    (line,) = _audit_lines(caplog)
    assert line == (
        f"admin_action actor=admin@x.org result_id={seeded.result_id} reason=x outcome=200"
    )
    assert "benchmark_id=" not in line


_FORGED_ID = "x%0Aadmin_action%20actor=admin@x.org%20benchmark_id=pub%20reason=ok%20outcome=200"


@pytest.mark.parametrize("user", [BRUNO, None], ids=["non-admin", "anonymous"])
async def test_caller_text_in_the_target_cannot_forge_an_audit_line(
    publish_client: AsyncClient, caplog: pytest.LogCaptureFixture, user: str | None
) -> None:
    # WHY no credentials: the audit wrapper logs a 401 and a 403 before the Path rule is checked,
    # so the raw path parameter (percent-decoded by Starlette) must be encoded before it is logged.
    caplog.set_level(logging.INFO, logger=_AUDIT)

    response = await _put(publish_client, _FORGED_ID, user=user)

    assert response.status_code in (401, 403)
    (line,) = _audit_lines(caplog)
    assert "\n" not in line
    assert line.count("admin_action ") == 1
    assert "benchmark_id=x%0Aadmin_action%20actor" in line
    assert await Benchmark.filter(id__startswith="x").exists() is False


async def test_a_65_character_benchmark_id_is_422_audited_and_creates_no_row(
    publish_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_AUDIT)
    rows_before = await Benchmark.all().count()

    response = await _put(publish_client, "b" * 65)

    assert response.status_code == 422
    (line,) = _audit_lines(caplog)
    assert "outcome=422" in line
    assert await Benchmark.all().count() == rows_before
