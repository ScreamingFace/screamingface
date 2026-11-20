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
    """Since E5 P2 the Engine's driver starts a Run's Candidates, so its `run scheduled` line
    names the owner key, the Run and the Candidate that join it to `run created`."""
    from run_driver_support import DriverRunner, drivers

    engine = _Engine(registry)
    run_id = (await engine.create(ADA)).json()["id"]
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await drivers(registry.store, DriverRunner(), registry.clock).drive_once(run_id)

    lines = _lines(caplog, "run scheduled topic=")
    assert sorted(line.rsplit(" candidate=", 1)[1] for line in lines) == ["0", "1"]
    assert all(f"owner={ADA_KEY} run={run_id} candidate=" in line for line in lines)
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


async def test_control_characters_in_the_benchmark_cannot_forge_a_log_line(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    # INVARIANT (security review, 2026-11-16): `benchmark` is the caller's text and RunSpec
    # admits any non-NUL character, so a newline inside it must not start a second, forged
    # `run created` line. Since #1840 review round 1, any Benchmark that is not a plain name
    # is logged as one `sha256:` token, so none of its text reaches the line.
    engine = _Engine(registry)
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await engine.create(ADA, benchmark="a\nrun created run=forged\x1b[0m")

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert "benchmark=sha256:" in line
    assert "forged" not in line and "\x1b" not in line
    assert "\n" not in line


@pytest.mark.parametrize(
    "sneaky",
    ["\x85", " ", " ", "\x9b", "​", "﻿"],
    ids=["NEL", "LINE SEP", "PARA SEP", "CSI", "ZWSP", "BOM"],
)
async def test_unicode_separators_and_format_characters_are_escaped_too(
    caplog: pytest.LogCaptureFixture, registry: Registry, sneaky: str
) -> None:
    # WHY (security review round 2): a line break is not only `\n` — NEL, U+2028/9 and the C1
    # controls split lines in some viewers, and format characters hide text. None of them is
    # a plain-name character, so the Benchmark is logged as its `sha256:` token.
    engine = _Engine(registry)
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await engine.create(ADA, benchmark=f"a{sneaky}b")

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert "benchmark=sha256:" in line
    assert sneaky not in line


async def test_a_benchmark_cannot_forge_fields_on_the_run_created_line(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    # HupBaHa's #1840 repro: spaces and `=` in the Benchmark forged `owner=`, `cases=`,
    # `candidates=` and `created=` ahead of the real ones on the same line.
    engine = _Engine(registry)
    forged = "real owner=forged cases=0 candidates=0 created=False"
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await engine.create(ADA, benchmark=forged)

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert "forged" not in line
    for field in ("owner=", "cases=", "candidates=", "created="):
        assert line.count(field) == 1, field


async def test_an_email_shaped_benchmark_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    # Spec anti-goal: an email in any log record. The Benchmark is caller text, so one shaped
    # like an address is logged only as its `sha256:` token.
    engine = _Engine(registry)
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await engine.create(ADA, benchmark="person@example.org")

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert "@" not in line
    assert "person" not in line
    assert "benchmark=sha256:" in line


async def test_a_plain_benchmark_name_stays_readable(
    caplog: pytest.LogCaptureFixture, registry: Registry
) -> None:
    engine = _Engine(registry)
    with caplog.at_level(logging.INFO, logger="screamingface_engine.rest.runs"):
        response = await engine.create(ADA, benchmark="mmlu_pro:v2/cot-5")

    assert response.status_code == 201
    (line,) = _lines(caplog, "run created ")
    assert " benchmark=mmlu_pro:v2/cot-5 cases=" in line
