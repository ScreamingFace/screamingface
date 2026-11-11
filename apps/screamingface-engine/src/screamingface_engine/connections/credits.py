"""Validated credit HTTP contract; never accepts provider credentials in responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from screamingface_engine import job_env

from .port import Caller, ConnectionBadResponse, ConnectionMethodUnsupported
from .provider_id import is_provider_id


class CreditAmount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["available", "stale", "unavailable", "unlimited"]
    amount_usd: Decimal | None = Field(default=None, allow_inf_nan=False)
    as_of: datetime | None = None
    reason: (
        Literal[
            "unsupported",
            "hosted_unavailable",
            "not_connected",
            "management_key_required",
            "account_unverified",
            "credential_rejected",
            "lookup_failed",
            "invalid_response",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent(self) -> CreditAmount:
        has_amount = self.status in {"available", "stale"}
        if has_amount != (self.amount_usd is not None):
            raise ValueError("inconsistent credit amount")
        if self.status != "unavailable" and (self.as_of is None or self.as_of.tzinfo is None):
            raise ValueError("missing observation time")
        return self


class CreditStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object: Literal["credit_status"]
    provider: str
    connection_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    account: CreditAmount
    key: CreditAmount
    hosted: CreditAmount
    management_key_configured: bool


class GatewayCredits:
    def __init__(self, request: Callable[..., Awaitable[httpx.Response]], *, enabled: bool) -> None:
        self._request = request
        self._enabled = enabled

    async def read(self, caller: Caller, provider: str, *, refresh: bool) -> CreditStatus:
        path = _path(provider)
        if not self._enabled and not job_env.identity_from_headers(httpx.Headers(caller.identity)):
            unavailable = CreditAmount(status="unavailable", reason="hosted_unavailable")
            return CreditStatus(
                object="credit_status",
                provider=provider,
                account=unavailable,
                key=unavailable,
                hosted=unavailable,
                management_key_configured=False,
            )
        if not self._enabled:
            path += "/key"
        response = await self._request(
            "GET", path, caller, params={"refresh": str(refresh).lower()}
        )
        try:
            result = CreditStatus.model_validate_json(response.content)
        except ValidationError:
            raise ConnectionBadResponse() from None
        if response.status_code != 200 or result.provider != provider:
            raise ConnectionBadResponse()
        if not self._enabled:
            # Hosted allowance is the execution key's allowance, not another wallet.
            unavailable = CreditAmount(status="unavailable", reason="hosted_unavailable")
            allowance = result.key if result.key.status != "unlimited" else unavailable
            result = result.model_copy(
                update={
                    "account": unavailable,
                    "hosted": allowance,
                    "management_key_configured": False,
                }
            )
        return result

    async def configure(self, caller: Caller, provider: str, api_key: str) -> None:
        if not self._enabled:
            raise ConnectionMethodUnsupported()
        response = await self._request(
            "PUT", _path(provider) + "/management-key", caller, json={"api_key": api_key}
        )
        if response.status_code != 204:
            raise ConnectionBadResponse()

    async def remove(self, caller: Caller, provider: str) -> None:
        if not self._enabled:
            raise ConnectionMethodUnsupported()
        response = await self._request("DELETE", _path(provider) + "/management-key", caller)
        if response.status_code != 204:
            raise ConnectionBadResponse()


def _path(provider: str) -> str:
    if not is_provider_id(provider):
        raise ConnectionBadResponse()
    return f"/v1/credits/{provider}"
