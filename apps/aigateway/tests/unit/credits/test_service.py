from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aigateway.core.credits import CreditAmount, CreditReading, unavailable
from aigateway.core.credits.service import CreditService, ManagementKeyRejected


class Store:
    def __init__(self):
        self.rows = {}

    async def read(self, service, account):
        return self.rows.get((service, account))

    async def write(self, service, account, value):
        self.rows[service, account] = value

    async def delete(self, service, account):
        self.rows.pop((service, account), None)


class Provider:
    def __init__(self):
        self.calls = []
        self.result = CreditReading(
            account=CreditAmount(
                status="available", amount_usd=Decimal("10"), as_of=datetime.now(UTC)
            ),
            key=unavailable("lookup_failed"),
        )

    async def read(self, key, management):
        self.calls.append((key, management))
        return self.result


@pytest.mark.asyncio
async def test_management_key_is_bound_to_caller_and_inference_credential():
    provider = Provider()
    store = Store()
    service = CreditService(store, {"openrouter": provider})
    await service.configure("owner", "openrouter", "inference", "management")
    result = await service.read("owner", "openrouter", "inference", refresh=True)
    assert result.management_key_configured
    assert provider.calls[-1] == ("inference", "management")
    await service.read("other", "openrouter", "inference", refresh=True)
    assert provider.calls[-1] == ("inference", None)
    await service.read("owner", "openrouter", "replacement", refresh=True)
    assert provider.calls[-1] == ("replacement", None)


@pytest.mark.asyncio
async def test_unverified_key_is_never_stored():
    provider = Provider()
    provider.result = CreditReading(
        account=unavailable("account_unverified"), key=unavailable("lookup_failed")
    )
    store = Store()
    service = CreditService(store, {"openrouter": provider})
    with pytest.raises(ManagementKeyRejected):
        await service.configure("owner", "openrouter", "inference", "management")
    assert not store.rows


@pytest.mark.asyncio
async def test_transient_failure_retains_same_connection_observation_only():
    provider = Provider()
    service = CreditService(Store(), {"openrouter": provider})
    first = await service.read("owner", "openrouter", "inference", refresh=True)
    provider.result = CreditReading(
        account=unavailable("lookup_failed"), key=unavailable("lookup_failed")
    )
    stale = await service.read("owner", "openrouter", "inference", refresh=True)
    assert stale.account.status == "stale"
    assert stale.account.as_of == first.account.as_of
    assert stale.account.amount_usd == 10
    different = await service.read("owner", "openrouter", "replacement", refresh=True)
    assert different.account.amount_usd is None
    assert different.connection_token != first.connection_token


@pytest.mark.asyncio
async def test_cache_and_removal():
    provider = Provider()
    service = CreditService(Store(), {"openrouter": provider})
    await service.configure("owner", "openrouter", "inference", "management")
    first = await service.read("owner", "openrouter", "inference", refresh=False)
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 2
    await service.remove("owner", "openrouter")
    last = await service.read("owner", "openrouter", "inference", refresh=False)
    assert not last.management_key_configured
    assert first.connection_token != last.connection_token


@pytest.mark.asyncio
async def test_unsupported_provider_never_reads_secrets():
    result = await CreditService(Store(), {}).read("owner", "anthropic", None, refresh=True)
    assert result.account.reason == "unsupported"
    assert result.key.amount_usd is None


@pytest.mark.asyncio
async def test_management_store_failure_preserves_key_allowance():
    class BrokenStore(Store):
        async def read(self, service, account):
            raise RuntimeError("private credential")

    provider = Provider()
    provider.result = CreditReading(
        account=unavailable("management_key_required"),
        key=CreditAmount(status="available", amount_usd=Decimal("3"), as_of=datetime.now(UTC)),
    )
    result = await CreditService(BrokenStore(), {"openrouter": provider}).read(
        "owner", "openrouter", "inference", refresh=True
    )
    assert result.key.amount_usd == 3
    assert result.account.reason == "lookup_failed"
    assert "private credential" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_overlapping_reads_share_one_provider_request():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowProvider(Provider):
        async def read(self, key, management):
            entered.set()
            await release.wait()
            return await super().read(key, management)

    provider = SlowProvider()
    service = CreditService(Store(), {"openrouter": provider})
    first = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await entered.wait()
    second = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)
    assert len(provider.calls) == 1
    assert results[0] == results[1]


@pytest.mark.asyncio
async def test_removing_management_key_during_read_discards_old_account():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowProvider(Provider):
        async def read(self, key, management):
            if len(self.calls) > 0:
                entered.set()
                await release.wait()
            return await super().read(key, management)

    provider = SlowProvider()
    service = CreditService(Store(), {"openrouter": provider})
    await service.configure("owner", "openrouter", "inference", "management")
    pending = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await entered.wait()
    await service.remove("owner", "openrouter")
    release.set()
    result = await pending
    assert result.account.amount_usd is None
    assert not result.management_key_configured


@pytest.mark.asyncio
async def test_cached_reads_back_off_on_failures_and_recover_on_manual_refresh(monkeypatch):
    import aigateway.core.credits.service as module

    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    provider = Provider()
    provider.result = CreditReading(
        account=unavailable("management_key_required"),
        key=CreditAmount(status="available", amount_usd=Decimal("3"), as_of=datetime.now(UTC)),
    )
    service = CreditService(Store(), {"openrouter": provider})
    await service.read("owner", "openrouter", "inference", refresh=False)
    now[0] = 299
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 1
    provider.result = CreditReading(
        account=unavailable("management_key_required"), key=unavailable("lookup_failed")
    )
    now[0] = 300
    first_failure = await service.read("owner", "openrouter", "inference", refresh=False)
    assert first_failure.key.status == "stale"
    now[0] = 600
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 3
    now[0] = 900
    backed_off = await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 3
    assert backed_off.key.as_of == first_failure.key.as_of
    provider.result = CreditReading(
        account=unavailable("management_key_required"),
        key=CreditAmount(status="available", amount_usd=Decimal("2"), as_of=datetime.now(UTC)),
    )
    recovered = await service.read("owner", "openrouter", "inference", refresh=True)
    assert recovered.key.status == "available"
    assert recovered.key.amount_usd == 2
    now[0] = 1200
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 5


@pytest.mark.asyncio
async def test_one_cancelled_caller_does_not_cancel_another_callers_lookup():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowProvider(Provider):
        async def read(self, key, management):
            entered.set()
            await release.wait()
            return await super().read(key, management)

    provider = SlowProvider()
    service = CreditService(Store(), {"openrouter": provider})
    one = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await entered.wait()
    two = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await asyncio.sleep(0)
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    release.set()
    assert (await two).account.amount_usd == 10
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_unexpected_provider_failure_is_safe_for_reads_and_key_setup():
    class BrokenProvider(Provider):
        async def read(self, key, management):
            raise RuntimeError("private-provider-key")

    service = CreditService(Store(), {"openrouter": BrokenProvider()})
    result = await service.read("owner", "openrouter", "inference", refresh=True)
    assert result.account.amount_usd is None
    assert result.key.reason == "lookup_failed"
    assert "private-provider-key" not in result.model_dump_json()
    with pytest.raises(ManagementKeyRejected) as rejected:
        await service.configure("owner", "openrouter", "inference", "management")
    assert "private-provider-key" not in str(rejected.value)


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_owned_lookup_tasks():
    import asyncio

    entered, cancelled = asyncio.Event(), asyncio.Event()

    class SlowProvider(Provider):
        async def read(self, key, management):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return await super().read(key, management)

    service = CreditService(Store(), {"openrouter": SlowProvider()})
    request = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await entered.wait()
    await service.aclose()
    assert cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await request


@pytest.mark.asyncio
async def test_store_outage_still_shares_overlapping_provider_reads():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class BrokenStore(Store):
        async def read(self, service, account):
            raise RuntimeError("store unavailable")

    class SlowProvider(Provider):
        async def read(self, key, management):
            calls.append(key)
            entered.set()
            await release.wait()
            return await super().read(key, management)

    service = CreditService(BrokenStore(), {"openrouter": SlowProvider()})
    first = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await entered.wait()
    second = asyncio.create_task(service.read("owner", "openrouter", "inference", refresh=True))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)
    assert calls == ["inference"]
    assert all(result.account.reason == "lookup_failed" for result in results)


@pytest.mark.asyncio
async def test_failed_cached_refresh_backoff_is_bounded_and_caller_scoped(monkeypatch):
    import aigateway.core.credits.service as module

    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    provider = Provider()
    provider.result = CreditReading(
        account=unavailable("lookup_failed"), key=unavailable("lookup_failed")
    )
    service = CreditService(Store(), {"openrouter": provider})
    for stamp in (0, 300, 900, 2100, 3900):
        now[0] = stamp
        await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 5
    now[0] = 5699
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 5
    await service.read("other", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 6
    now[0] = 5700
    await service.read("owner", "openrouter", "inference", refresh=False)
    assert len(provider.calls) == 7


@pytest.mark.asyncio
async def test_changing_one_callers_management_key_does_not_evict_another_callers_cache():
    provider = Provider()
    service = CreditService(Store(), {"openrouter": provider})
    other = await service.read("other", "openrouter", "other-inference", refresh=False)
    await service.configure("owner", "openrouter", "inference", "management")
    calls = len(provider.calls)
    assert await service.read("other", "openrouter", "other-inference", refresh=False) == other
    assert len(provider.calls) == calls
    await service.remove("owner", "openrouter")
    assert await service.read("other", "openrouter", "other-inference", refresh=False) == other
    assert len(provider.calls) == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["account_unverified", "credential_rejected"])
async def test_rejected_identity_discards_balance_and_later_failure_cannot_resurrect_it(reason):
    provider = Provider()
    service = CreditService(Store(), {"openrouter": provider})
    assert (
        await service.read("owner", "openrouter", "inference", refresh=True)
    ).account.amount_usd == 10
    provider.result = CreditReading(account=unavailable(reason), key=unavailable(reason))
    rejected = await service.read("owner", "openrouter", "inference", refresh=True)
    assert rejected.account.amount_usd is None
    provider.result = CreditReading(
        account=unavailable("lookup_failed"), key=unavailable("lookup_failed")
    )
    subsequent = await service.read("owner", "openrouter", "inference", refresh=True)
    assert subsequent.account.amount_usd is None


@pytest.mark.asyncio
async def test_key_only_lookup_never_reads_management_credentials_or_returns_account_total():
    class UnreadableStore(Store):
        async def read(self, service, account):
            pytest.fail("key-only reads must not load management credentials")

    provider = Provider()
    provider.result = CreditReading(
        account=CreditAmount(
            status="available", amount_usd=Decimal("5000"), as_of=datetime.now(UTC)
        ),
        key=CreditAmount(status="available", amount_usd=Decimal("7"), as_of=datetime.now(UTC)),
    )
    service = CreditService(UnreadableStore(), {"openrouter": provider})
    result = await service.read(
        "owner", "openrouter", "limited-key", refresh=True, include_account=False
    )
    assert provider.calls == [("limited-key", None)]
    assert result.key.amount_usd == 7
    assert result.account.amount_usd is None
    assert not result.management_key_configured
    cached = await service.read(
        "owner", "openrouter", "limited-key", refresh=False, include_account=False
    )
    assert cached == result and len(provider.calls) == 1
