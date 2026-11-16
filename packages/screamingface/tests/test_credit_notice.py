"""Run-start credit notices must never stop paid-work admission or invent a cause."""

import warnings
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from test_credits import payload

from screamingface._engine import credit_notice, runs
from screamingface._evaluation.model import (
    _compiled_candidate,
    _compiled_operation,
    _with_replay_frozen_copy,
)
from screamingface.credit import CreditAmount, CreditState, CreditStatus
from screamingface.warnings import EvaluationWarning


def candidate_for(model):
    return _compiled_candidate(
        name="test",
        kind="model",
        models=(model,),
        url4="(@)!'test'",
        operations=(_compiled_operation(id="answer", kind="model", label="answer", depends_on=()),),
    )


def reading(state: CreditState = "available", age=0, amount="0"):
    value = CreditAmount(
        state,
        Decimal(amount) if amount is not None else None,
        datetime.now(UTC) - timedelta(seconds=age),
    )
    return CreditStatus("openrouter", value, value, value, "a" * 64)


@pytest.mark.parametrize(
    "state,age,amount",
    [
        ("stale", 0, "0"),
        ("unavailable", 0, None),
        ("available", 301, "0"),
        ("available", -10, "0"),
        ("available", 0, "0.01"),
        ("unlimited", 0, None),
    ],
)
def test_no_notice_for_unknown_old_future_or_positive_values(state, age, amount):
    from screamingface._engine.credit_notice import zero_notice

    assert zero_notice(reading(state, age, amount)) is None


def test_zero_notice_is_factual_and_does_not_duplicate_hosted_budget():
    from screamingface._engine.credit_notice import zero_notice

    value = reading()
    text = zero_notice(value)
    assert text and "account credit" in text and "key allowance" in text
    assert "will still be attempted" in text
    assert "failed" not in text.lower()
    unknown = CreditAmount("unavailable", reason="hosted_unavailable")
    hosted = CreditStatus("openrouter", unknown, value.key, value.key, "a" * 64)
    text = zero_notice(hosted)
    assert text and text.count("allowance") == 1 and "account credit" not in text


def test_no_notice_without_verified_connection():
    from screamingface._engine.credit_notice import zero_notice

    v = reading()
    assert zero_notice(CreditStatus(v.provider, v.account, v.key, v.hosted)) is None


def test_best_effort_sync_lookup_and_warning_error_filter():
    from screamingface._engine.credit_notice import check_sync

    candidate = candidate_for("openrouter/example/model")
    body = payload()
    for name in ("account", "key"):
        body[name].update(amount_usd="0", as_of=datetime.now(UTC).isoformat())
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=body)

    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(handle)) as client:
        with pytest.warns(EvaluationWarning, match="will still be attempted"):
            check_sync(client, (candidate, candidate))
        with warnings.catch_warnings():
            warnings.simplefilter("error", EvaluationWarning)
            check_sync(client, (candidate,))
    assert len(seen) == 2
    assert seen[0].url.params["refresh"] == "false"
    assert seen[0].extensions["timeout"]["read"] <= 1


@pytest.mark.parametrize("kind", ["other", "replay", "empty"])
def test_no_lookup_for_other_providers_or_frozen_replay(kind):
    from screamingface._engine.credit_notice import check_sync

    model = "anthropic/example" if kind == "other" else "openrouter/example/model"
    candidate = candidate_for(model)
    if kind == "replay":
        candidate = _with_replay_frozen_copy(candidate, "frozen")
    candidates = () if kind == "empty" else (candidate,)
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request"))
    ) as c:
        check_sync(c, candidates)


@pytest.mark.asyncio
async def test_async_notice_and_failure_are_nonblocking():
    from screamingface._engine.credit_notice import check_async

    candidate = candidate_for("openrouter/example/model")
    body = payload()
    body["key"].update(amount_usd="0", as_of=datetime.now(UTC).isoformat())
    async with httpx.AsyncClient(
        base_url="http://localhost",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as c:
        with pytest.warns(EvaluationWarning, match="key allowance"):
            await check_async(c, (candidate,))

    def fail(request):
        raise httpx.ReadTimeout("private")

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(fail)
    ) as c:
        with warnings.catch_warnings(record=True) as caught:
            await check_async(c, (candidate,))
        assert not caught


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_run_registration_checks_credits_once_before_registration(monkeypatch, asynchronous):
    from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport

    seen = []
    candidates = (candidate_for("openrouter/example/model"),)

    def check(client, selected):
        assert selected is candidates
        seen.append("credits")

    async def check_async(client, selected):
        check(client, selected)

    def create(*args):
        seen.append("register")
        return runs.Unavailable("test")

    async def create_async(*args):
        return create(*args)

    for module, name, function in (
        (credit_notice, "check_sync", check),
        (credit_notice, "check_async", check_async),
        (runs, "create_sync", create),
        (runs, "create_async", create_async),
    ):
        monkeypatch.setattr(module, name, function)
    transport = (
        AsyncUrl4CloudTransport("http://localhost:9100")
        if asynchronous
        else Url4CloudTransport("http://localhost:9100")
    )
    try:
        with pytest.warns(EvaluationWarning, match="not recorded"):
            if isinstance(transport, AsyncUrl4CloudTransport):
                await transport.open_run("test", 1, candidates)
            else:
                transport.open_run("test", 1, candidates)
        assert seen == ["credits", "register"]
    finally:
        if isinstance(transport, AsyncUrl4CloudTransport):
            await transport.close()
        else:
            transport.close()
