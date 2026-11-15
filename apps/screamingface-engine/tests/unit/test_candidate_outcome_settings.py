"""The outcome stream's limits, as the chart sets them (OME-1785, E5 P1 spec R11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from screamingface_engine.adapters.factory import build_candidate_outcome_stream
from screamingface_engine.candidate_outcomes import DEFAULT_OUTCOMES_MAX_AGE_S
from screamingface_engine.config import Settings


def test_the_defaults_are_the_streams() -> None:
    settings = Settings()

    assert settings.candidate_outcomes_max_age_s == DEFAULT_OUTCOMES_MAX_AGE_S
    assert settings.candidate_outcomes_max_bytes == 64 * 1024**2


def test_the_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_CANDIDATE_OUTCOMES_MAX_AGE_S", "3600")
    monkeypatch.setenv("URL4_CLOUD_CANDIDATE_OUTCOMES_MAX_BYTES", "1048576")

    stream = build_candidate_outcome_stream(Settings())

    assert (stream.config.max_age_s, stream.config.max_bytes) == (3600.0, 1024**2)


@pytest.mark.parametrize("field", ["candidate_outcomes_max_age_s", "candidate_outcomes_max_bytes"])
def test_a_non_positive_limit_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
