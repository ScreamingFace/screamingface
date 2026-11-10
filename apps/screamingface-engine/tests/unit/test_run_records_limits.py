"""`RunSpec` refuses what its database columns cannot hold (OME-1785, E5 P1).

WHY here and not in the store: a value too long for its column fails on Postgres and is silently
kept on SQLite, so the one rule both databases share has to come first.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine.runs.records import (
    MAX_BENCHMARK_LENGTH,
    MAX_CANDIDATE_NAME_LENGTH,
    MAX_CANDIDATES,
    MAX_CASE_COUNT,
    MAX_CLIENT_KEY_LENGTH,
    MAX_CLIENT_VERSION_LENGTH,
    RunSpec,
)


def _spec(**overrides: Any) -> RunSpec:
    values: dict[str, Any] = {
        "client_key": "key",
        "benchmark": "gsm8k",
        "case_count": 1,
        "candidates": ("alpha",),
        "client_version": "1.0",
    }
    return RunSpec(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_key": "k" * MAX_CLIENT_KEY_LENGTH},
        {"benchmark": "b" * MAX_BENCHMARK_LENGTH},
        {"client_version": "v" * MAX_CLIENT_VERSION_LENGTH},
        {"candidates": ("n" * MAX_CANDIDATE_NAME_LENGTH,)},
        {"candidates": tuple(f"c{index}" for index in range(MAX_CANDIDATES))},
        {"case_count": MAX_CASE_COUNT},
    ],
)
def test_the_largest_values_the_columns_hold_are_accepted(overrides: dict[str, Any]) -> None:
    _spec(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_key": "k" * (MAX_CLIENT_KEY_LENGTH + 1)},
        {"benchmark": "b" * (MAX_BENCHMARK_LENGTH + 1)},
        {"client_version": "v" * (MAX_CLIENT_VERSION_LENGTH + 1)},
        {"candidates": ("n" * (MAX_CANDIDATE_NAME_LENGTH + 1),)},
        {"candidates": tuple(f"c{index}" for index in range(MAX_CANDIDATES + 1))},
        {"case_count": MAX_CASE_COUNT + 1},
    ],
)
def test_a_value_too_large_for_its_column_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _spec(**overrides)


def test_lengths_count_the_stripped_value() -> None:
    """INVARIANT: what was validated is what is stored, and the store keeps the stripped form."""
    assert (
        _spec(benchmark=" " + "b" * MAX_BENCHMARK_LENGTH + " ").benchmark
        == "b" * MAX_BENCHMARK_LENGTH
    )
