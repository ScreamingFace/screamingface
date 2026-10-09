"""Recovery preserves newer main provenance and public persistence options."""

from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._results.store import ResultStore


def test_recovery_retains_main_archive_savings_and_unpriced_hit_count(tmp_path):
    original, saved = saved_fixture(tmp_path, 2)
    outcome = replace(
        saved.outcome,
        root_usage=sf.Usage(cost_usd=None),
        cache_saved_cost_usd=Decimal("0.25"),
        cache_saved_cost_archive_usd=Decimal("0.75"),
        cache_hits=4,
        cache_unpriced_hits=1,
    )
    store = ResultStore(tmp_path)
    saved = store.record(saved.engine_url, saved.candidate, outcome, saved.evaluation)
    loaded = store.load(saved.key)
    assert loaded.outcome.cache_saved_cost_archive_usd == Decimal("0.75")
    assert loaded.outcome.cache_unpriced_hits == 1
    recovered = sf.reports.get(saved.key, directory=tmp_path)
    candidate = recovered.candidates[0]
    assert candidate.cache_saved_cost_usd == Decimal("0.25")
    assert candidate.cache_saved_cost_archive_usd == Decimal("0.75")
    assert candidate.cache_unpriced_hits == 1
    assert candidate.cache_hits == 4
    assert candidate.run_cost_status == "partial"
    assert candidate.cases == original.candidates[0].cases


@pytest.mark.parametrize("save", [True, False])
def test_public_client_selects_result_persistence(save):
    with sf.Client(engine_url="https://fixture.example", save_results=save) as client:
        transport = cast(Url4CloudTransport, client._transport)
        assert (transport._result_store is not None) is save


@pytest.mark.asyncio
@pytest.mark.parametrize("save", [True, False])
async def test_public_async_client_selects_result_persistence(save):
    async with sf.AsyncClient(engine_url="https://fixture.example", save_results=save) as client:
        transport = cast(AsyncUrl4CloudTransport, client._transport)
        assert (transport._result_store is not None) is save
