"""Validated credit values shared by the Engine port and HTTP adapter."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    connection_token: str | None = None
    account: CreditAmount
    key: CreditAmount
    hosted: CreditAmount
    management_key_configured: bool

    @field_validator("connection_token")
    @classmethod
    def valid_token(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(c not in "abcdef0123456789" for c in value)
        ):
            raise ValueError("invalid connection token")
        return value
