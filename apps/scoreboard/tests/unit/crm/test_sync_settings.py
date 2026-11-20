"""The sync job's settings and entry point (OME-1504).

FEATURE: the HubSpot token reaches only the sync job, through `SCOREBOARD_HUBSPOT_*` variables;
without a token the job sends nothing, and a half-configured job refuses to start.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from scoreboard import hubspot_sync
from scoreboard.config import Settings
from scoreboard.crm.decisions import Stages
from scoreboard.crm.settings import HubSpotSyncSettings

_ENV = (
    "SCOREBOARD_HUBSPOT_TOKEN",
    "SCOREBOARD_HUBSPOT_PIPELINE_ID",
    "SCOREBOARD_HUBSPOT_EARLY_STAGE_IDS",
    "SCOREBOARD_HUBSPOT_SUBMISSION_STAGE_IDS",
    "SCOREBOARD_HUBSPOT_DROPPED_OUT_STAGE_ID",
    "SCOREBOARD_HUBSPOT_INTERNAL_EMAILS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def test_without_a_token_nothing_else_is_required() -> None:
    settings = HubSpotSyncSettings()
    assert settings.token is None


def test_a_full_configuration_parses_lists_and_masks_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_TOKEN", "pat-secret")
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_PIPELINE_ID", "941434182")
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_EARLY_STAGE_IDS", "1450673809, 1489861179")
    monkeypatch.setenv(
        "SCOREBOARD_HUBSPOT_SUBMISSION_STAGE_IDS", "1450673810,1450673811,1450673812"
    )
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_DROPPED_OUT_STAGE_ID", "1450673814")
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_INTERNAL_EMAILS", "Friend@Partner.org, ,x@y.org")

    settings = HubSpotSyncSettings()

    assert settings.stages() == Stages(
        early=("1450673809", "1489861179"),
        submissions=("1450673810", "1450673811", "1450673812"),
        dropped_out="1450673814",
    )
    assert settings.internal_emails == frozenset({"friend@partner.org", "x@y.org"})
    # INVARIANT: the token never appears in a repr, a log line or an error.
    assert settings.token is not None and settings.token.get_secret_value() == "pat-secret"
    assert repr(settings.token) == "SecretStr('**********')"


def test_a_token_without_the_ids_refuses_to_start_and_does_not_echo_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = f"pat-{uuid.uuid4().hex}"
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_TOKEN", token)
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_SUBMISSION_STAGE_IDS", "a,b")

    with pytest.raises(ValidationError) as raised:
        HubSpotSyncSettings()

    [error] = raised.value.errors()
    context = error.get("ctx") or {}
    missing = str(context["error"]).split("missing: ")[1].split(", ")
    assert missing == [
        "SCOREBOARD_HUBSPOT_PIPELINE_ID",
        "SCOREBOARD_HUBSPOT_DROPPED_OUT_STAGE_ID",
        "SCOREBOARD_HUBSPOT_SUBMISSION_STAGE_IDS (exactly 3)",
    ]
    # WHY a substring check here: the leak is in the rendered message a crash log prints, and the
    # token is a 36-character random value, so no timestamp or id can collide with it.
    assert token not in str(raised.value)


def test_the_web_settings_never_carry_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: the web server that serves public traffic has no field for the HubSpot token.
    monkeypatch.setenv("SCOREBOARD_HUBSPOT_TOKEN", "pat-secret")
    assert {"token", "hubspot_token"}.isdisjoint(Settings.model_fields)
    assert not hasattr(Settings(), "token")


def test_main_without_a_token_sends_nothing_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database = tmp_path / "main.sqlite3"
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", f"sqlite://{database}")
    created: list[str] = []

    async def _fake_init(url: str) -> None:
        created.append(url)
        from tortoise import Tortoise

        from scoreboard.db import build_tortoise_config

        await Tortoise.init(config=build_tortoise_config(url))
        await Tortoise.generate_schemas()

    monkeypatch.setattr(hubspot_sync, "init_db", _fake_init)

    with caplog.at_level(logging.INFO, logger="scoreboard.hubspot_sync"):
        hubspot_sync.main([])

    assert created == [f"sqlite://{database}"]
    lines = [record.getMessage() for record in caplog.records]
    assert "hubspot sync: queued=0 skipped=0 sent=0 failed=0 waiting=0 rate_limited=False" in lines
