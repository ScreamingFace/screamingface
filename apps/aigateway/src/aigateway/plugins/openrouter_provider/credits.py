"""OpenRouter credit observations using read-only requests to its fixed API origin."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from aigateway.core.credits import CreditAmount, CreditReading, Reason, unavailable

_ORIGIN = "https://openrouter.ai/api/v1"


class _LookupFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class OpenRouterCredits:
    """FEATURE: E5 P3. Lookup failures never become execution failures or fake zeros."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def read(self, api_key: str, management_key: str | None) -> CreditReading:
        if self._client is not None:
            return await self._read(self._client, api_key, management_key)
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            return await self._read(client, api_key, management_key)

    async def _read(
        self, client: httpx.AsyncClient, api_key: str, management_key: str | None
    ) -> CreditReading:
        return await self._observe(client, api_key, management_key)

    async def _observe(
        self, client: httpx.AsyncClient, api_key: str, management_key: str | None
    ) -> CreditReading:
        try:
            identity = await _get(client, "/key", api_key)
        except _LookupFailed as exc:
            return CreditReading(account=unavailable(exc.reason), key=unavailable(exc.reason))
        key = _key_allowance(identity)
        account = unavailable("management_key_required")
        if management_key is not None:
            account = await _account_balance(client, identity, management_key)
        return CreditReading(account=account, key=key)


async def _get(client: httpx.AsyncClient, path: str, secret: str) -> dict[str, Any]:
    try:
        # INVARIANT: fixed origin, fixed paths, no redirects or provider-authored URLs.
        # Bound each complete response, so an account timeout preserves the key reading.
        async with asyncio.timeout(3):
            response = await client.get(
                _ORIGIN + path,
                headers={"Authorization": f"Bearer {secret}"},
                timeout=3,
                follow_redirects=False,
            )
        if response.status_code in {401, 403}:
            raise _LookupFailed("credential_rejected")
        if response.status_code != 200:
            raise _LookupFailed("lookup_failed")
        data = response.json().get("data")
        if not isinstance(data, dict):
            raise _LookupFailed("invalid_response")
        return data
    except (httpx.HTTPError, TimeoutError, ValueError, AttributeError):
        # INVARIANT: never return provider text or an exception containing a credential.
        raise _LookupFailed("lookup_failed") from None


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("invalid amount")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("invalid amount")
    return amount


def _key_allowance(data: dict[str, Any]) -> CreditAmount:
    if "limit_remaining" not in data:
        return unavailable("invalid_response")
    if data["limit_remaining"] is None:
        return CreditAmount(status="unlimited", as_of=datetime.now(UTC))
    try:
        return CreditAmount(
            status="available",
            amount_usd=_decimal(data["limit_remaining"]),
            as_of=datetime.now(UTC),
        )
    except (ValueError, InvalidOperation):
        return unavailable("invalid_response")


def _same_account(inference: dict[str, Any], management: dict[str, Any]) -> bool:
    # INVARIANT: absence is not identity. Require provider-authored identity on BOTH keys;
    # a matching label, last characters, balance or user confirmation proves nothing.
    creator = inference.get("creator_user_id")
    context = ("creator_user_id", "organization_id", "workspace_id")
    return (
        isinstance(creator, str)
        and bool(creator.strip())
        and management.get("is_management_key") is True
        and all(field in inference and field in management for field in context)
        and all(inference[field] == management[field] for field in context)
        and all(
            inference[field] is None
            or (isinstance(inference[field], str) and bool(inference[field].strip()))
            for field in ("organization_id", "workspace_id")
        )
    )


async def _account_balance(
    client: httpx.AsyncClient, identity: dict[str, Any], management_key: str
) -> CreditAmount:
    try:
        management = await _get(client, "/key", management_key)
        if not _same_account(identity, management):
            return unavailable("account_unverified")
        data = await _get(client, "/credits", management_key)
        balance = _decimal(data["total_credits"]) - _decimal(data["total_usage"])
        return CreditAmount(status="available", amount_usd=balance, as_of=datetime.now(UTC))
    except _LookupFailed as exc:
        return unavailable(exc.reason)
    except (KeyError, ValueError, InvalidOperation):
        return unavailable("invalid_response")
