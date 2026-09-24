"""Free tests of the paid gate itself — the branch CI green-ness hangs on.

INVARIANT (PR #1035 review, action-required): when the owner PRESSES the paid button
(`SCREAMINGFACE_PAID_REQUIRED=1`, set only by the just recipe and the workflow), an
unavailable stack must FAIL the run, never skip it — a skip exits 0, and a green run
that proved nothing is worse than a red one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import KEY_ENV, PAID_ENV, REQUIRED_ENV, _require_imported_assets, require_paid_stack


def test_gate_skips_loudly_when_opt_in_flag_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default posture: no flag → an ordinary loud skip, so merge-gate runs stay green."""
    monkeypatch.delenv(PAID_ENV, raising=False)
    monkeypatch.delenv(REQUIRED_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match=f"{PAID_ENV}=1 not set"):
        require_paid_stack()


def test_gate_fails_instead_of_skipping_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Button posture: REQUIRED turns the same unavailability into a FAILURE (exit 1)."""
    monkeypatch.delenv(PAID_ENV, raising=False)
    monkeypatch.setenv(REQUIRED_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match=f"{PAID_ENV}=1 not set"):
        require_paid_stack()


def test_missing_key_fails_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured-but-empty key secret must fail the pressed button, not skip it."""
    monkeypatch.setenv(PAID_ENV, "1")
    monkeypatch.setenv(KEY_ENV, "")
    monkeypatch.setenv(REQUIRED_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match=f"{KEY_ENV} not set"):
        require_paid_stack()


def test_missing_assets_fail_when_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty assets (e.g. a failed prepare step) must fail the pressed button too —
    this is the exact path where a broken --list-bundles used to yield a green run."""
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(tmp_path))
    monkeypatch.setenv(REQUIRED_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match="no prepared imported-board assets"):
        _require_imported_assets()


def test_missing_assets_skip_without_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(tmp_path))
    monkeypatch.delenv(REQUIRED_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match="no prepared imported-board assets"):
        _require_imported_assets()
