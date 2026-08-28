"""The console script is the container's ENTRYPOINT, so its wiring is deployment behaviour."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from report_intake import cli


def test_the_entrypoint_serves_the_app_on_the_configured_address(
    hermetic_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main()` with nothing passed, which is what the console-script wrapper calls.

    `sys.argv` is set to the bare command because that is now load-bearing: argparse falls back to
    it, and under pytest the real one carries the test session's own arguments. This is the
    production path — `ENTRYPOINT ["report-intake"]` with no arguments — exercised end to end.
    """
    recorded: dict[str, Any] = {}

    def _record(target: str, **options: Any) -> None:
        recorded["target"] = target
        recorded.update(options)

    monkeypatch.setattr(cli.uvicorn, "run", _record)
    monkeypatch.setattr(sys, "argv", ["report-intake"])
    monkeypatch.setenv("REPORT_INTAKE_HOST", "0.0.0.0")
    monkeypatch.setenv("REPORT_INTAKE_PORT", "9199")

    cli.main()

    assert recorded["target"] == "report_intake.main:app"
    assert (recorded["host"], recorded["port"]) == ("0.0.0.0", 9199)


def test_the_entrypoint_still_serves_when_given_no_arguments_at_all(
    hermetic_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Dockerfile's `ENTRYPOINT ["report-intake"]` passes none, so the argument-free
    invocation reaching uvicorn is deployment behaviour rather than a convenience. Asserted
    against an EMPTY argv, not the default `None`, so the subcommand parser is genuinely in the
    path — a `required=True` on it would fail here rather than in the fleet."""
    served: list[str] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda target, **_: served.append(target))

    assert cli.main([]) == 0
    assert served == ["report_intake.main:app"]


def test_an_unrecognised_argument_is_a_usage_error_rather_than_a_silent_serve(
    hermetic_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`report-intake queeu list` must not start a web server inside a `kubectl exec` session and
    bind the port. Argparse's own exit code 2, which is also why neither of the console's codes
    is 2."""
    served: list[str] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda target, **_: served.append(target))

    with pytest.raises(SystemExit) as refused:
        cli.main(["queeu"])

    assert refused.value.code == 2
    assert served == []
