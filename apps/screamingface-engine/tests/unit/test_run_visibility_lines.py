"""The App's run-visibility log lines: `run created` and the identity on `run scheduled`.

FEATURE: queue visibility in the logs (OME-1924 part 1, epic OME-1314).
STORY: as on-call reading the App log during a saturated queue, I can name every run's owner
key, Run id, Benchmark, Case count and Candidate from the log alone — never from the database
the read-only session cannot open.
INVARIANT: identity in a log record is the sha256 owner key (`runs.records.owner_key`), never
the email; unknown values are `-`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import BODY, _Engine

from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

# WHY the odd spelling: `owner_key` trims and lowercases, so the logged key must equal the one
# run history stores for "ada@example.org" — the raw header text must appear nowhere.
RAW_EMAIL = " Ada@Example.ORG "
ADA = {"X-User-Email": RAW_EMAIL}
ADA_KEY = owner_key("ada@example.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def _no_email_anywhere(caplog: pytest.LogCaptureFixture) -> None:
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "@" not in joined
    assert "example.org" not in joined.lower()


# --- `run created` at POST /runs ------------------------------------------------------------


async def test_create_run_logs_owner_key_and_run_facts(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    engine = _Engine(registry)
    with caplog.at_level(logging.DEBUG):
        response = await engine.create(ADA)

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert f"run={response.json()['id']}" in line
    assert f"owner={ADA_KEY}" in line
    assert f"benchmark={BODY['benchmark']} cases={BODY['case_count']} candidates=2" in line
    assert line.endswith("created=True")
    _no_email_anywhere(caplog)


async def test_a_repeated_create_logs_created_false(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    engine = _Engine(registry)
    await engine.create(ADA)
    caplog.clear()  # only the repeat's line is under test
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        again = await engine.create(ADA)

    assert again.status_code == 200
    (line,) = _lines(caplog, "run created ")
    assert line.endswith("created=False")


# --- identity on `run scheduled` at start ---------------------------------------------------


def _scheduled(caplog: pytest.LogCaptureFixture) -> str:
    (line,) = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("run scheduled topic=")
    ]
    return line


async def test_scheduled_owner_matches_run_history_key(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(ADA)).json()["id"]
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        resp = await engine.start("topic-a", run_id, candidate="1", **ADA)

    assert resp.status_code == 202
    line = _scheduled(caplog)
    assert f"owner={ADA_KEY}" in line
    assert f"run={run_id} candidate=1" in line
    _no_email_anywhere(caplog)


async def test_an_unbound_start_logs_dashes(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    engine = _Engine(registry)
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.routes"):
        resp = await engine.start("topic-b", **ADA)

    assert resp.status_code == 202
    line = _scheduled(caplog)
    assert f"owner={ADA_KEY}" in line
    assert line.endswith("run=- candidate=-")


async def test_a_start_without_identity_logs_anonymous(caplog: pytest.LogCaptureFixture) -> None:
    # STORY: a hosted Engine with Runs off and no identity header — the line still has a
    # readable owner field, never a blank or an exception.
    from test_runs_routes import LIFETIME_S, SECRET, TOKEN_T0, WINDOW_S

    from screamingface_engine.auth import JwtCodec

    engine = _Engine(None)
    token = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        "topic-c", TOKEN_T0
    )
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.routes"):
        resp = await engine.client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={"URL4-Capability": token, "Prefer": "respond-async"},
        )

    assert resp.status_code == 202
    assert "owner=anonymous run=- candidate=-" in _scheduled(caplog)
