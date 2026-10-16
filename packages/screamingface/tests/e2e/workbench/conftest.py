"""Workbench lane fixtures (e2e workbench spec §3). Env-selected, never CLI options — see plan.

WHY env vars: ``pytest_addoption`` in a non-initial conftest does not register when the
invocation is ``pytest tests/e2e``.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Final

import pytest

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
def live_target(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiveTarget]:
    with start_target(selected_target(), tmp_path_factory.mktemp("workbench-target")) as target:
        yield target


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """With REQUIRE_ALL=1 a skipped notebook is a failure: an all-skipped run is not green.

    WHY rewrite at makereport, not logreport: the session counts failures in a ``tryfirst``
    logreport hook that runs before a conftest's; a report fixed at creation is seen as failed
    by every consumer (exit status, terminal, junit).
    """
    report = yield
    if (
        os.environ.get(REQUIRE_ALL_ENV) == "1"
        and report.skipped
        and "workbench" in report.nodeid
        and "test_notebook" in report.nodeid
    ):
        # A skip's longrepr is the (path, lineno, "Skipped: <reason>") tuple; keep the reason.
        why = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
        report.outcome = "failed"
        report.longrepr = f"{REQUIRE_ALL_ENV}=1 and the workbench skipped — {why}"
    return report


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    root = config.stash.get(_OUT_KEY, None)
    if root is not None:
        terminalreporter.write_sep("-", "workbench evidence")
        terminalreporter.write_line(f"bundles + summary.md: {root}")
