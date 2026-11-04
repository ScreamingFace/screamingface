"""The Run registry's settings (OME-1785, E5 P1 spec D2, R5, R6, R7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from screamingface_engine.config import CLIENT_ADMISSION_BUDGET_S, Settings


def test_the_defaults_are_the_specs() -> None:
    settings = Settings()

    assert settings.database_url == ""
    assert settings.run_retention_s == 30 * 86_400
    assert settings.run_pending_grace_s == 1800
    assert settings.run_lost_after_s == 48 * 3600


def test_the_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_DATABASE_URL", "postgres://engine@db:5432/engine")

    assert Settings().database_url == "postgres://engine@db:5432/engine"


@pytest.mark.parametrize("grace", [CLIENT_ADMISSION_BUDGET_S, CLIENT_ADMISSION_BUDGET_S - 1, 0])
def test_a_grace_within_the_clients_admission_budget_is_refused(grace: float) -> None:
    """WHY (spec R5): a Client still waiting for admission must never read as `interrupted`."""
    with pytest.raises(ValidationError):
        Settings(run_pending_grace_s=grace)


@pytest.mark.parametrize("field", ["run_retention_s", "run_lost_after_s"])
def test_a_non_positive_window_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})


@pytest.mark.parametrize("field", ["run_retention_s", "run_pending_grace_s", "run_lost_after_s"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_window_that_is_not_finite_is_refused(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


@pytest.mark.parametrize("lost_after", [1.0, 86_400.0])
def test_lost_after_within_the_streams_retention_is_refused(lost_after: float) -> None:
    # INVARIANT (spec R6): reconcile settles `lost` only once no outcome can still arrive.
    with pytest.raises(ValueError, match="run_lost_after_s"):
        Settings(run_lost_after_s=lost_after)
