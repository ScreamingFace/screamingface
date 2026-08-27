"""The console script is the container's ENTRYPOINT, so its wiring is deployment behaviour."""

from __future__ import annotations

from typing import Any

import pytest

from report_intake import cli


def test_the_entrypoint_serves_the_app_on_the_configured_address(
    hermetic_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: dict[str, Any] = {}

    def _record(target: str, **options: Any) -> None:
        recorded["target"] = target
        recorded.update(options)

    monkeypatch.setattr(cli.uvicorn, "run", _record)
    monkeypatch.setenv("REPORT_INTAKE_HOST", "0.0.0.0")
    monkeypatch.setenv("REPORT_INTAKE_PORT", "9199")

    cli.main()

    assert recorded["target"] == "report_intake.main:app"
    assert (recorded["host"], recorded["port"]) == ("0.0.0.0", 9199)
