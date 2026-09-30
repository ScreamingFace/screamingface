"""Plain helpers of the SB-grants tests: ask for a grant, read a counter, decode a grant."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import FastAPI
from httpx import AsyncClient, Response

from tests.unit.replay.conftest import GrantKey
from tests.unit.submissions._receipts import as_user


async def request_grant(
    client: AsyncClient, pin: str, *, user: str | None, benchmark_id: str = "pub"
) -> Response:
    """`POST /v1/replay-grants` as `user` (the mesh header); no header when `user` is None."""
    headers = as_user(user) if user is not None else {}
    return await client.post(
        "/v1/replay-grants", json={"pin": pin, "benchmark_id": benchmark_id}, headers=headers
    )


def grants_counted(app: FastAPI, result: str) -> float:
    value = app.state.metrics.registry.get_sample_value(
        "scoreboard_replay_grants_total", {"result": result}
    )
    return 0.0 if value is None else value


def decode_grant(grant: str, key: GrantKey) -> dict[str, Any]:
    return jwt.decode(
        grant,
        key.public_key,
        algorithms=["EdDSA"],
        audience="aigateway",
        issuer="scoreboard",
        # WHY: the tests pin the scoreboard clock (`FIXED_NOW`), which is not the wall clock. The
        # tests assert `iat` and `exp` themselves instead.
        options={"verify_exp": False, "verify_iat": False},
    )


def granted_result_id(response: Response) -> str:
    """The result a grant names; the status is asserted first so a refusal reads as one."""
    assert response.status_code == 200, response.text
    return str(response.json()["result_id"])
