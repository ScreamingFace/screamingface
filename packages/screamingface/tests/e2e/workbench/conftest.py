"""Workbench lane fixtures (e2e workbench spec §3). Env-selected, never CLI options — see plan.

WHY env vars: ``pytest_addoption`` in a non-initial conftest does not register when the
invocation is ``pytest tests/e2e``.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Generator, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Final

import pytest

from workbench.bundle import write_setup_failure
from workbench.redaction import redact
from workbench.targets import LiveTarget, selected_target, start_target

REQUIRE_ALL_ENV: Final = "SCREAMINGFACE_WORKBENCH_REQUIRE_ALL"
OUT_ENV: Final = "SCREAMINGFACE_WORKBENCH_OUT"

_OUT_KEY: Final = pytest.StashKey[Path]()


@pytest.fixture(scope="session")
def workbench_out(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> Path:
    configured = os.environ.get(OUT_ENV)
    root = Path(configured) if configured else tmp_path_factory.mktemp("workbench-out")
    root.mkdir(parents=True, exist_ok=True)
    pytestconfig.stash[_OUT_KEY] = root.resolve()
    return root


@pytest.fixture(scope="session")
def live_target(
    workbench_out: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[LiveTarget]:
    """The selected target, booted once per session.

    WHY it depends on ``workbench_out`` (review finding 4): the evidence root must exist BEFORE
    the target boots, whatever order a test lists its fixtures in, and a target that errors or
    skips while booting leaves ``setup_error.txt`` + a summary row there. CI uploads that dir
    with ``if-no-files-found: error``, so an empty dir would also lose the reason.
    """
    name = selected_target()
    with ExitStack() as stack:
        try:
            target = stack.enter_context(
                start_target(name, tmp_path_factory.mktemp("workbench-target"))
            )
        except BaseException as exc:  # a skip is a BaseException (pytest OutcomeException)
            skipped = isinstance(exc, pytest.skip.Exception)
            detail = (
                f"Skipped: {exc}"
                if skipped
                else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
            write_setup_failure(workbench_out, target=name, skipped=skipped, detail=detail)
            raise
        yield target


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """With REQUIRE_ALL=1 a skipped notebook is a failure: an all-skipped run is not green.
    Every report of the lane is then redacted (``_redact_report``).

    WHY rewrite at makereport, not logreport: the session counts failures in a ``tryfirst``
    logreport hook that runs before a conftest's; a report fixed at creation is seen as failed
    by every consumer (exit status, terminal, junit).

    SCOPE: pytest calls a conftest's makereport only for items under its directory, so other
    e2e lanes in the same run never reach this; within the lane only ``test_notebook`` in
    ``test_notebooks.py`` is guarded (matched on the item, not on nodeid substrings).
    """
    report = yield
    if (
        os.environ.get(REQUIRE_ALL_ENV) == "1"
        and report.skipped
        and item.path.name == "test_notebooks.py"
        and getattr(item, "originalname", item.name) == "test_notebook"
    ):
        # A skip's longrepr is the (path, lineno, "Skipped: <reason>") tuple; keep the reason.
        why = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
        report.outcome = "failed"
        report.longrepr = f"{REQUIRE_ALL_ENV}=1 and the workbench skipped — {why}"
    _redact_report(report)
    return report


def _redact_report(report: pytest.TestReport) -> None:
    """Scrub every text a report carries to the terminal and JUnit (review finding 1).

    WHY here: the verdict redacts its own reasons, but a report also carries tracebacks (with
    ``-l``, every frame's locals), captured stdout/stderr/log and user properties, any of which
    can quote a key. This is the last point before every sink (terminal, junit, -r summary).
    A structured longrepr is replaced by its redacted rendering only when it held a secret,
    so ordinary failures keep their native formatting.
    """
    longrepr = report.longrepr
    if isinstance(longrepr, tuple):  # a skip: (path, lineno, "Skipped: <reason>")
        path, lineno, why = longrepr
        report.longrepr = (path, lineno, redact(why))
    elif longrepr is not None:
        text = str(longrepr)
        if (clean := redact(text)) != text:
            report.longrepr = clean
    report.sections = [(title, redact(body)) for title, body in report.sections]
    report.user_properties = [
        (name, value if redact(str(value)) == str(value) else redact(str(value)))
        for name, value in report.user_properties
    ]


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    root = config.stash.get(_OUT_KEY, None)
    if root is not None:
        terminalreporter.write_sep("-", "workbench evidence")
        terminalreporter.write_line(f"bundles + summary.md: {root}")
