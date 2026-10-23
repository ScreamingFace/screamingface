"""Review finding 4: a target that fails or skips during setup still leaves evidence.

WHY: CI uploads the evidence dir with ``if-no-files-found: error``. When ``live_target`` was set
up before ``workbench_out`` and the target errored or skipped, the dir never existed, the upload
failed, and the reviewer got no artifact saying why. The real lane fixtures run in a pytester
lane whose test requests ``live_target`` FIRST (the order that used to lose the evidence), with
``start_target`` replaced by one that fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from workbench import conftest as lane
from workbench.conftest import OUT_ENV
from workbench.redaction import MASK
from workbench.targets import LiveTarget

pytest_plugins = ["pytester"]

_ARGS = ("-p", "no:cacheprovider", "--import-mode=importlib", "-rA")
_CONFTEST = (
    "from workbench.conftest import live_target, workbench_out  # noqa: F401\n"
    "from workbench.conftest import pytest_runtest_makereport  # noqa: F401\n"
)
_TEST = """
def test_notebook(live_target, workbench_out):
    raise AssertionError("must not run: the target never came up")
"""
SECRET = "sk-or-v1-" + "s3cr3t" * 4  # fake, assembled at runtime


def _failing_target(exc: BaseException):  # type: ignore[no-untyped-def]
    @contextmanager
    def start(name: str, work_dir: Path) -> Iterator[LiveTarget]:
        raise exc
        yield  # pragma: no cover

    return start


@pytest.fixture
def out(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Path:
    pytester.makepyfile(**{"lane/conftest.py": _CONFTEST, "lane/test_notebooks.py": _TEST})
    root = pytester.path / "evidence"
    monkeypatch.setenv(OUT_ENV, str(root))
    monkeypatch.delenv("SCREAMINGFACE_WORKBENCH_REQUIRE_ALL", raising=False)
    monkeypatch.delenv("SCREAMINGFACE_WORKBENCH_TARGET", raising=False)
    return root


def test_a_target_setup_error_writes_a_redacted_diagnostic(
    pytester: pytest.Pytester, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boom = RuntimeError(f"gateway refused to boot with {SECRET}")
    monkeypatch.setattr(lane, "start_target", _failing_target(boom))
    result = pytester.runpytest(*_ARGS)
    result.assert_outcomes(errors=1)

    diagnostic = (out / "setup_error.txt").read_text()
    assert "RuntimeError" in diagnostic and "gateway refused to boot" in diagnostic
    assert SECRET not in diagnostic and MASK in diagnostic
    summary = (out / "summary.md").read_text()
    assert "| replay | (target setup) | SETUP-ERROR |" in summary
    assert SECRET not in summary
    assert SECRET not in result.stdout.str()


def test_a_target_setup_skip_writes_a_diagnostic(
    pytester: pytest.Pytester, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skip = pytest.skip.Exception("SCREAMINGFACE_TEST_E2E=1 not set")
    monkeypatch.setattr(lane, "start_target", _failing_target(skip))
    pytester.runpytest(*_ARGS).assert_outcomes(skipped=1)

    assert "SCREAMINGFACE_TEST_E2E=1 not set" in (out / "setup_error.txt").read_text()
    assert "| replay | (target setup) | SETUP-SKIP |" in (out / "summary.md").read_text()
