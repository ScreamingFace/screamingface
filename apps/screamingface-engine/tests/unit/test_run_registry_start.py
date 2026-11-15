"""E5 P1 spec §4.1 and R2, what the routes ask of the registry: whether `POST /runs` created the
Run (201) or found it (200), and whether a scheduled start still stands after a cancel.

FEATURE: first-class Runs (OME-1785). Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
TOPIC = "t" * 64


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_register_says_whether_it_created_the_run(registry: Registry) -> None:
    first, created = await registry.store.register(ALICE, spec("alpha"))
    again, created_again = await registry.store.register(ALICE, spec("alpha"))

    assert (created, created_again) == (True, False)
    assert again == first


async def test_a_scheduled_start_stands(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)

    assert await registry.store.mark_scheduled(TOPIC) is True
    # The same start re-sent after a 503 is scheduled again and still stands.
    assert await registry.store.mark_scheduled(TOPIC) is True


async def test_a_start_that_lost_to_a_cancel_does_not_stand(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    await registry.store.cancel(ALICE, run.id)

    assert await registry.store.mark_scheduled(TOPIC) is False
    record = await registry.store.get(ALICE, run.id)
    assert record is not None and record.candidates[0].state == "stopped"


async def test_a_start_that_already_finished_stands(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded"))

    assert await registry.store.mark_scheduled(TOPIC) is True


async def test_an_unbound_topic_stands(registry: Registry) -> None:
    assert await registry.store.mark_scheduled(TOPIC) is True
