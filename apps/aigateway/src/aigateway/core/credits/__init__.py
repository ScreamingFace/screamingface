"""Safe credit observations; values are independent of provider credentials."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

Reason = Literal[
    "unsupported",
    "hosted_unavailable",
    "not_connected",
    "management_key_required",
    "account_unverified",
    "credential_rejected",
    "lookup_failed",
    "invalid_response",
]


class CreditAmount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["available", "unavailable", "stale", "unlimited"]
    amount_usd: Decimal | None = Field(default=None, allow_inf_nan=False)
    as_of: datetime | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def consistent(self) -> CreditAmount:
        has_amount = self.status in {"available", "stale"}
        if has_amount != (self.amount_usd is not None):
            raise ValueError("inconsistent credit amount")
        if self.status != "unavailable" and (self.as_of is None or self.as_of.tzinfo is None):
            raise ValueError("missing observation time")
        return self


class CreditReading(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: CreditAmount
    key: CreditAmount


class CreditStatus(CreditReading):
    object: Literal["credit_status"] = "credit_status"
    provider: str
    connection_token: str | None = None
    hosted: CreditAmount = CreditAmount(status="unavailable", reason="hosted_unavailable")
    management_key_configured: bool = False


class CreditProvider(Protocol):
    async def read(self, api_key: str, management_key: str | None, /) -> CreditReading: ...


def unavailable(reason: Reason) -> CreditAmount:
    return CreditAmount(status="unavailable", reason=reason)
