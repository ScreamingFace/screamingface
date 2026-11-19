"""Credit reads must never report another account's money or invent a zero."""

from decimal import Decimal

import httpx
import pytest

from aigateway.plugins.openrouter_provider.credits import OpenRouterCredits

IDENTITY = {"creator_user_id": "owner-a", "organization_id": None, "workspace_id": None}


def transport(*, identity=None, remaining: object = 8, account_status=200, key_status=200):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.url.host == "openrouter.ai"
        if request.url.path.endswith("/credits"):
            return httpx.Response(
                account_status, json={"data": {"total_credits": 100.1, "total_usage": 25.05}}
            )
        management = request.headers["authorization"] == "Bearer management-secret"
        data = dict(IDENTITY if not management or identity is None else identity)
        data.update(is_management_key=management, limit_remaining=remaining)
        return httpx.Response(200 if management else key_status, json={"data": data})

    return httpx.MockTransport(handler), seen


@pytest.mark.asyncio
async def test_verified_account_total_and_key_allowance_are_separate():
    wire, seen = transport()
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", "management-secret")
    assert result.account.amount_usd == Decimal("75.05")
    assert result.key.amount_usd == Decimal("8")
    assert result.account.status == "available"
    assert len(seen) == 3
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity",
    [
        {},
        {**IDENTITY, "creator_user_id": "other"},
        {**IDENTITY, "organization_id": "other"},
        {**IDENTITY, "workspace_id": "other"},
    ],
)
async def test_unverified_identity_never_fetches_account_balance(identity):
    wire, seen = transport(identity=identity)
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", "management-secret")
    assert result.account.amount_usd is None
    assert result.account.reason == "account_unverified"
    assert result.key.amount_usd == 8
    assert not any(r.url.path.endswith("/credits") for r in seen)


@pytest.mark.asyncio
async def test_optional_management_key_leaves_key_allowance_available():
    wire, seen = transport(remaining=0)
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", None)
    assert result.account.reason == "management_key_required"
    assert result.key.amount_usd == 0
    assert result.key.status == "available"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_missing_key_limit_is_not_unlimited_money():
    wire, _ = transport(remaining=None)
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", None)
    assert result.key.status == "unlimited"
    assert result.key.amount_usd is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_account_failure_does_not_hide_key_allowance(status):
    wire, _ = transport(account_status=status)
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", "management-secret")
    assert result.account.status == "unavailable"
    assert result.account.amount_usd is None
    assert result.key.amount_usd == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, "NaN", "Infinity", {}, "not-money"])
async def test_invalid_amounts_are_unavailable_not_zero(value):
    wire, _ = transport(remaining=value)
    async with httpx.AsyncClient(transport=wire) as client:
        result = await OpenRouterCredits(client).read("inference-secret", None)
    assert result.key.status == "unavailable"
    assert result.key.amount_usd is None


@pytest.mark.asyncio
async def test_timeout_never_echoes_secrets():
    def handler(request):
        raise httpx.ReadTimeout("inference-secret management-secret", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenRouterCredits(client).read("inference-secret", "management-secret")
    assert result.key.reason == "lookup_failed"
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("value", [False, 0, {}, [], ""])
def test_malformed_matching_context_is_not_identity(value):
    from aigateway.plugins.openrouter_provider.credits import _same_account

    left = {**IDENTITY, "organization_id": value}
    right = {**left, "is_management_key": True}
    assert not _same_account(left, right)


@pytest.mark.asyncio
async def test_account_deadline_preserves_successful_key_allowance():
    def handler(request):
        if request.headers["authorization"] == "Bearer management-secret":
            raise TimeoutError("private-management")
        return httpx.Response(200, json={"data": {**IDENTITY, "limit_remaining": 4}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenRouterCredits(client).read("inference", "management-secret")
    assert result.key.amount_usd == 4
    assert result.account.reason == "lookup_failed"
