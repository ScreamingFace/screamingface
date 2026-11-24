"""The frozen copy retention sweep settings (OME-1947, S-22, spec `prd/copy-sweep.md`).

The sweep has no switch (owner decision Q22). Each setting has a default and a lower limit; a
value outside the limit fails at start-up and names the setting.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.config import Settings

_SWEEP_NAMES = (
    "AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS",
    "AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS",
    "AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES",
)


def _settings(**values: object) -> Settings:
    # WHY: _env_file=None stops a developer .env file from changing the result; the dict spread
    # keeps pyright quiet about the pydantic-settings init keyword (house pattern:
    # test_cache_snapshot_settings.py).
    return Settings(**{"_env_file": None, **values})


def test_the_sweep_settings_have_their_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SWEEP_NAMES:
        monkeypatch.delenv(name, raising=False)
    s = _settings()
    assert (
        s.frozen_copy_sweep_interval_seconds,
        s.frozen_copy_open_idle_seconds,
        s.frozen_copy_sweep_max_entries,
    ) == (3600, 86400, 100000)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS", "59"),
        ("AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS", "0"),
        ("AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES", "0"),
    ],
)
def test_a_sweep_setting_outside_its_limit_is_refused_and_named(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as exc_info:
        _settings()
    assert name in str(exc_info.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS", "60"),
        ("AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS", "1"),
        ("AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES", "1"),
    ],
)
def test_the_lowest_legal_value_is_accepted(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    _settings()
