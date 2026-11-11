"""Read-only credit observations for the current execution connection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

import httpx

from screamingface.connections import _provider_id
from screamingface.errors import ProviderConnectionError

type CreditState = Literal["available", "stale", "unavailable", "unlimited"]
_REASONS = frozenset(
    {
        "unsupported",
        "hosted_unavailable",
        "not_connected",
        "management_key_required",
        "account_unverified",
        "credential_rejected",
        "lookup_failed",
        "invalid_response",
    }
)


@dataclass(frozen=True)
class CreditAmount:
    """USD amount and observation time; ``unlimited`` means no key limit, not free usage."""

    status: CreditState
    amount_usd: Decimal | None = None
    as_of: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CreditStatus:
    """Account balance and allowances for one execution connection.

    On the platform, ``hosted`` mirrors ``key``: they describe the same limited
    OpenRouter key and must not be added together. The platform account total is hidden.
    """

    provider: str
    account: CreditAmount
    key: CreditAmount
    hosted: CreditAmount
    connection_token: str | None = None
    management_key_configured: bool = False


def credits(provider: str = "openrouter", *, refresh: bool = True) -> CreditStatus:
    """Read credits for the default Client's execution connection."""
    from screamingface._default_client import default_client

    return default_client().credits(provider, refresh=refresh)


def _path(provider: str, *, refresh: bool | None = None) -> str:
    path = f"/v1/credits/{_provider_id(provider)}"
    return path if refresh is None else path + f"?refresh={str(refresh).lower()}"


def _unavailable(provider: str) -> CreditStatus:
    unknown = CreditAmount("unavailable", reason="lookup_failed")
    return CreditStatus(
        provider, unknown, unknown, CreditAmount("unavailable", reason="hosted_unavailable")
    )


def _decimal(raw: object) -> Decimal | None:
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (str, int, float))):
        raise ValueError("invalid amount")
    amount = Decimal(str(raw)) if raw is not None else None
    if amount is not None and not amount.is_finite():
        raise ValueError("invalid amount")
    return amount


def _amount(value: object) -> CreditAmount:
    if not isinstance(value, dict) or set(value) != {"status", "amount_usd", "as_of", "reason"}:
        raise ValueError("invalid amount")
    status = value["status"]
    if status not in {"available", "stale", "unavailable", "unlimited"}:
        raise ValueError("invalid status")
    amount = _decimal(value["amount_usd"])
    if (status in {"available", "stale"}) != (amount is not None):
        raise ValueError("inconsistent amount")
    stamp = value["as_of"]
    if stamp is not None and not isinstance(stamp, str):
        raise ValueError("invalid timestamp")
    as_of = datetime.fromisoformat(stamp) if stamp is not None else None
    if status != "unavailable" and (as_of is None or as_of.tzinfo is None):
        raise ValueError("missing observation time")
    reason = value["reason"]
    if reason is not None and (not isinstance(reason, str) or reason not in _REASONS):
        raise ValueError("invalid reason")
    return CreditAmount(cast("CreditState", status), amount, as_of, reason)


def _decode(response: httpx.Response, provider: str) -> CreditStatus:
    try:
        body = response.json()
        if (
            response.status_code != 200
            or not isinstance(body, dict)
            or set(body)
            != {
                "object",
                "provider",
                "account",
                "key",
                "hosted",
                "connection_token",
                "management_key_configured",
            }
        ):
            raise ValueError("invalid response")
        token = body["connection_token"]
        if token is not None and (
            not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token)
        ):
            raise ValueError("invalid connection token")
        configured = body["management_key_configured"]
        if (
            body["object"] != "credit_status"
            or body["provider"] != provider
            or not isinstance(configured, bool)
        ):
            raise ValueError("invalid context")
        return CreditStatus(
            provider,
            _amount(body["account"]),
            _amount(body["key"]),
            _amount(body["hosted"]),
            token,
            configured,
        )
    except (ValueError, TypeError, InvalidOperation):
        return _unavailable(provider)


def _secret(api_key: str) -> str:
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096:
        raise ValueError("A management key is required")
    return api_key.strip()


def _setup_result(response: httpx.Response | None) -> None:
    if response is None or response.status_code != 204:
        raise ProviderConnectionError(
            "Credit settings could not be updated", code="credit_setup_failed"
        ) from None
