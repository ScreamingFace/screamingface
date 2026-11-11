from decimal import Decimal

import httpx
import pytest

import screamingface as sf


def payload():
    amount = {
        "status": "available",
        "amount_usd": "12.34",
        "as_of": "2026-11-11T12:00:00Z",
        "reason": None,
    }
    return {
        "object": "credit_status",
        "provider": "openrouter",
        "connection_token": "a" * 64,
        "account": dict(amount),
        "key": dict(amount),
        "hosted": {
            "status": "unavailable",
            "amount_usd": None,
            "as_of": None,
            "reason": "hosted_unavailable",
        },
        "management_key_configured": True,
    }


def test_credit_api_and_management_setup_are_secret_safe():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=payload())
        if request.method == "PUT":
            assert b"private-management" in request.content
        return httpx.Response(204)

    with sf.Client(
        engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handler)
    ) as client:
        result = client.credits()
        assert isinstance(result, sf.CreditStatus)
        assert result.account.amount_usd == Decimal("12.34")
        assert result.hosted.status == "unavailable"
        client.set_credit_management_key("openrouter", api_key="private-management")
        client.clear_credit_management_key("openrouter")
    assert [r.method for r in seen] == ["GET", "PUT", "DELETE"]
    assert all("private-management" not in str(r.url) for r in seen)


@pytest.mark.asyncio
async def test_async_credit_api():
    async with sf.AsyncClient(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload())),
    ) as client:
        assert (await client.credits()).account.amount_usd == Decimal("12.34")


@pytest.mark.parametrize("change", ["provider", "extra", "nan"])
def test_untrusted_response_becomes_unavailable(change):
    body = payload()
    if change == "provider":
        body["provider"] = "other"
    elif change == "extra":
        body["secret"] = "private-secret"
    else:
        body["account"]["amount_usd"] = "NaN"
    with sf.Client(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as client:
        result = client.credits()
    assert result.account.status == "unavailable"
    assert result.account.amount_usd is None
    assert "private-secret" not in repr(result)


def test_failure_never_becomes_zero_or_exposes_body():
    with sf.Client(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(503, text="private-secret")),
    ) as client:
        result = client.credits()
    assert result.account.amount_usd is None
    assert "private-secret" not in repr(result)


@pytest.mark.parametrize("provider", ["../secrets", "openrouter?admin=1", "OPENROUTER"])
def test_provider_validation_precedes_request(provider):
    def handler(request):
        pytest.fail("invalid provider must not reach transport")

    with (
        sf.Client(
            engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(ValueError),
    ):
        client.credits(provider)


def test_default_credit_api(monkeypatch):
    from screamingface import _default_client

    with sf.Client(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload())),
    ) as client:
        monkeypatch.setattr(_default_client, "default_client", lambda: client)
        assert sf.credits().key.amount_usd == Decimal("12.34")


def test_credit_card_distinguishes_balance_allowance_and_unknown():
    from screamingface._ui.credit_view import credit_html
    from screamingface.credit import _decode

    body = payload()
    body["key"].update(status="unlimited", amount_usd=None)
    result = _decode(httpx.Response(200, json=body), "openrouter")
    html = credit_html(result)
    assert html.index("Account balance") < html.index("Key allowance")
    assert "$12.34" in html
    assert "No key limit" in html
    assert "Hosted allowance" not in html
    assert "spending cap, not additional credit" in html
    assert "2026-11-11" in html
    body["account"]["status"] = "stale"
    assert "Refresh failed" in credit_html(_decode(httpx.Response(200, json=body), "openrouter"))


def test_credit_card_refresh_and_secret_input():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/connections":
            return httpx.Response(200, json={"object": "list", "data": []})
        if request.method != "GET":
            return httpx.Response(204)
        return httpx.Response(200, json=payload())

    with sf.Client(
        engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handler)
    ) as client:
        panel = sf.ConnectionPanel(client)
        panel.refresh_credits()
        assert "$12.34" in panel._repr_html_()
        panel.set_credit_management_key("private-management")
        assert calls[-2].method == "PUT"
        panel.clear_credit_management_key()
        assert calls[-2].method == "DELETE"
        panel.close()


def test_widget_clears_management_password_before_submitting():
    def handler(request):
        if request.url.path == "/v1/connections":
            return httpx.Response(200, json={"object": "list", "data": []})
        return httpx.Response(200, json=payload())

    with sf.Client(
        engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handler)
    ) as client:
        panel = sf.ConnectionPanel(client)
        widget = panel.widget()
        assert panel._view is not None
        controls = panel._view._credits.children[1].children
        password, save = controls[1:3]
        seen = []

        def submit(api_key: str) -> None:
            assert password.value == ""
            seen.append(api_key)

        panel.set_credit_management_key = submit
        password.value = "private-management"
        save.click()
        assert seen == ["private-management"]
        assert "private-management" not in panel._repr_html_()
        widget.close()


@pytest.mark.asyncio
async def test_async_management_setup_and_removal():
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(204)

    async with sf.AsyncClient(
        engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handler)
    ) as client:
        await client.set_credit_management_key("openrouter", api_key="private-management")
        await client.clear_credit_management_key("openrouter")
    assert seen == ["PUT", "DELETE"]


@pytest.mark.parametrize("operation", ["set", "clear"])
def test_management_failure_does_not_expose_upstream_body(operation):
    with sf.Client(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(
            lambda r: httpx.Response(409, text="private-management")
        ),
    ) as client:
        with pytest.raises(sf.ProviderConnectionError) as caught:
            if operation == "set":
                client.set_credit_management_key("openrouter", api_key="private-management")
            else:
                client.clear_credit_management_key("openrouter")
    assert "private-management" not in str(caught.value)
    assert "ambiguous" not in str(caught.value)


@pytest.mark.parametrize(
    "amount",
    [
        {
            "status": "available",
            "amount_usd": True,
            "as_of": "2026-11-11T12:00:00Z",
            "reason": None,
        },
        {"status": "available", "amount_usd": "1", "as_of": "2026-11-11", "reason": None},
        {"status": "unavailable", "amount_usd": "0", "as_of": None, "reason": "lookup_failed"},
        {"status": [], "amount_usd": None, "as_of": None, "reason": None},
    ],
)
def test_inconsistent_observations_are_not_displayed(amount):
    body = payload()
    body["account"] = amount
    with sf.Client(
        engine_url="http://localhost:9100",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as client:
        assert client.credits().account.amount_usd is None


def test_sdk_reads_hosted_key_allowance_without_inventing_an_account_balance():
    body = payload()
    body["hosted"] = dict(body["key"])
    body["account"] = {
        "status": "unavailable",
        "amount_usd": None,
        "as_of": None,
        "reason": "hosted_unavailable",
    }
    body["management_key_configured"] = False
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as client:
        result = client.credits()
    assert result.hosted.amount_usd == Decimal("12.34")
    assert result.hosted == result.key
    assert result.account.amount_usd is None
