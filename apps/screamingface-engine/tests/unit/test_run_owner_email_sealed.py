"""E5 P2 spec D8, R16: a Run keeps its owner's email sealed, and only the driver opens it.

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Run the Engine starts after I
have gone, my email never shows in a database dump or a logged SQL statement.
INVARIANT: the Run row holds only the sealed value; a value this App cannot open fails the
Candidate `owner_unreadable` before anything is sent.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from run_driver_support import DriverRunner, drivers
from run_registry_support import (
    DATABASES,
    DEADLINE,
    LOST_AFTER,
    ORPHAN_GRACE,
    T0,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    start_spec,
)

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.config import Settings
from screamingface_engine.runs.models import Run
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.sealing import EmailSeal, Unreadable, decode_key
from screamingface_engine.runs.store import TortoiseRunStore
from screamingface_engine.runs.wiring import RunsConfigError, email_seal, install_runs

EMAIL = "alice@example.org"
ALICE = owner_key(EMAIL)


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _store_with(registry: Registry, seal: EmailSeal) -> TortoiseRunStore:
    """The same database, opened by an App whose key is ``seal``'s."""
    return TortoiseRunStore(
        clock=registry.clock,
        lost_after=LOST_AFTER,
        outcomes_survive_restart=True,
        started_at=T0,
        orphan_grace=ORPHAN_GRACE,
        default_deadline=DEADLINE,
        seal=seal,
    )


# --- the seal ----------------------------------------------------------------------------


def test_a_sealed_email_opens_to_itself_and_reads_as_nothing_like_it() -> None:
    seal = EmailSeal(decode_key(_key()))

    sealed = seal.seal(EMAIL)

    assert seal.open(sealed) == EMAIL
    assert sealed.startswith("v1:")
    assert "alice" not in sealed and "example" not in sealed


def test_each_seal_takes_a_fresh_nonce() -> None:
    """INVARIANT: GCM under one key leaks with a repeated nonce."""
    seal = EmailSeal(decode_key(_key()))

    assert seal.seal(EMAIL) != seal.seal(EMAIL)


@pytest.mark.parametrize(
    "sealed",
    ["alice@example.org", "v1:", "v1:not-base64:also-not", "v2:AAAA:BBBB", "v1:AAAA:BBBB:CCCC"],
    ids=["plain", "empty", "not base64", "another version", "too many parts"],
)
def test_what_was_not_sealed_by_this_key_never_opens(sealed: str) -> None:
    with pytest.raises(Unreadable):
        EmailSeal(decode_key(_key())).open(sealed)


def test_a_value_sealed_under_another_key_never_opens() -> None:
    sealed = EmailSeal(decode_key(_key())).seal(EMAIL)

    with pytest.raises(Unreadable):
        EmailSeal(decode_key(_key())).open(sealed)


@pytest.mark.parametrize(
    "key",
    ["not base64!", base64.b64encode(b"short").decode(), base64.b64encode(os.urandom(64)).decode()],
    ids=["not base64", "too short", "too long"],
)
def test_a_key_is_32_bytes_of_base64(key: str) -> None:
    with pytest.raises(ValueError, match="run email key"):
        decode_key(key)


def test_a_configured_key_that_is_not_one_fails_the_app_at_start() -> None:
    with pytest.raises(RunsConfigError, match="URL4_CLOUD_RUN_EMAIL_KEY"):
        email_seal(Settings(run_email_key=SecretStr("not a key")))


def test_a_hosted_app_with_runs_on_and_no_key_does_not_start() -> None:
    """R16: a key made per process would strand every hosted Run at the next restart."""
    settings = Settings(database_url="postgres://engine:secret@db.example:5432/engine")

    with pytest.raises(RunsConfigError, match="URL4_CLOUD_RUN_EMAIL_KEY"):
        install_runs(FastAPI(), settings, InMemoryCandidateOutcomeStream(), local=False)


# --- the Run row and the driver ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_row_holds_the_email_only_sealed(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a", owner_email=EMAIL))

    row = await Run.get(id=run.id)

    assert row.sealed_owner_email is not None
    assert row.sealed_owner_email.startswith("v1:")
    assert "example.org" not in row.sealed_owner_email
    plan = await registry.store.pending_starts(run.id)
    assert plan is not None and (plan.owner_email, plan.owner_unreadable) == (EMAIL, False)


@pytest.mark.asyncio
async def test_the_driver_starts_the_candidate_as_its_owner(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a", owner_email=EMAIL))
    runner = DriverRunner()

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    assert runner.starts[0]["identity"] == {"X-User-Email": EMAIL}


@pytest.mark.asyncio
async def test_an_email_this_app_cannot_open_fails_the_candidate_before_any_start(
    registry: Registry,
) -> None:
    """R16: the key was replaced, so no start can say whose it is."""
    run, _ = await registry.store.register(ALICE, start_spec("a", "b", owner_email=EMAIL))
    rekeyed = _store_with(registry, EmailSeal(decode_key(_key())))
    runner = DriverRunner()

    plan = await rekeyed.pending_starts(run.id)
    await drivers(rekeyed, runner, registry.clock).drive_once(run.id)

    assert plan is not None and (plan.owner_email, plan.owner_unreadable) == (None, True)
    assert runner.starts == []
    record = await rekeyed.get(ALICE, run.id)
    assert record is not None
    assert [(c.state, c.error_code) for c in record.candidates] == [
        ("failed", "owner_unreadable"),
        ("failed", "owner_unreadable"),
    ]


@pytest.mark.asyncio
async def test_a_reopened_store_in_the_same_process_reads_what_the_first_sealed(
    registry: Registry,
) -> None:
    """With no key configured (local mode, tests) the key is the process's, not the store's."""
    run, _ = await registry.store.register(ALICE, start_spec("a", owner_email=EMAIL))

    plan = await registry.restarted(survives_restart=True).pending_starts(run.id)

    assert plan is not None and plan.owner_email == EMAIL


@pytest.mark.asyncio
async def test_a_repeated_post_keeps_an_attached_runs_held_deadline(registry: Registry) -> None:
    """A follower moves an attached Run's deadline (R10), so a repeated `POST /runs` with the
    same `client_key` still matches it rather than reading as another evaluation."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    registry.clock.advance(seconds=100)
    await registry.store.hold(run.id)

    again, created = await registry.store.register(ALICE, start_spec("a"))

    assert (again.id, created) == (run.id, False)
    assert again.deadline_at == T0 + timedelta(seconds=100) + ORPHAN_GRACE
