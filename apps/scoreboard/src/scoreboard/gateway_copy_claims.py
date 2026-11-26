"""The AI Gateway adapter of the `CopyClaims` port (OME-1947).

It sends `POST /v1/frozen-copies/{copy_id}/claim` with no body and with no identity header
(contracts.md K4). It sends the copy id only. The gateway trusts the peer address of the
scoreboard pod, not a header (owner decision 2026-11-25).

INVARIANT (erd.md I5): the mapping fails closed. Only the exact answers in `_RESULTS` give a
result. Each other answer, a timeout and a connection error give UNAVAILABLE. A 200 never counts
as a claim because of its status only.
"""

from __future__ import annotations

import httpx

from scoreboard.config import Settings
from scoreboard.core.copy_claims import ClaimResult, CopyClaims

_RESULTS: dict[tuple[int, str], ClaimResult] = {
    (200, "claimed"): ClaimResult.CLAIMED,
    (200, "already"): ClaimResult.ALREADY,
    (404, "frozen_copy_not_found"): ClaimResult.NOT_FOUND,
    (409, "frozen_copy_not_sealed"): ClaimResult.NOT_SEALED,
    (410, "expired"): ClaimResult.EXPIRED,
    (410, "abandoned"): ClaimResult.ABANDONED,
}
# WHY: 404 and 409 name their case in `detail.code`. The two 410 answers share one code and name
# their case in `detail.state`.
_DETAIL_FIELD: dict[int, str] = {404: "code", 409: "code", 410: "state"}


def _sealed_word(body: object, copy_id: str) -> str | None:
    if not isinstance(body, dict):
        return None
    already = body.get("already")
    exact = (
        body.get("status") == "sealed"
        and isinstance(already, bool)
        and body.get("id", copy_id) == copy_id
    )
    if not exact:
        return None
    return "already" if already else "claimed"


def _detail_word(body: object, field: str) -> str | None:
    detail = body.get("detail") if isinstance(body, dict) else None
    word = detail.get(field) if isinstance(detail, dict) else None
    return word if isinstance(word, str) else None


def _answer_key(status_code: int, body: object, copy_id: str) -> tuple[int, str] | None:
    if status_code == 200:
        word = _sealed_word(body, copy_id)
    else:
        field = _DETAIL_FIELD.get(status_code)
        word = None if field is None else _detail_word(body, field)
    return None if word is None else (status_code, word)


class GatewayCopyClaims:
    """Sends claims to the AI Gateway with one HTTP client that it owns."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def claim(self, copy_id: str) -> ClaimResult:
        # WHY no retry: the SDK sends the submit again after a 503 (contracts.md K5).
        # INVARIANT: catch only these two types. A CancelledError must go up to the caller.
        try:
            response = await self._client.post(f"/v1/frozen-copies/{copy_id}/claim")
            key = _answer_key(response.status_code, response.json(), copy_id)
        except (httpx.HTTPError, ValueError):
            key = None
        return (
            ClaimResult.UNAVAILABLE if key is None else _RESULTS.get(key, ClaimResult.UNAVAILABLE)
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_copy_claims(settings: Settings) -> CopyClaims | None:
    """The claim client of the settings, or None when the gateway URL is empty."""
    if not settings.gateway_url:
        return None
    return GatewayCopyClaims(
        base_url=settings.gateway_url,
        timeout_s=settings.gateway_timeout_s,
    )
