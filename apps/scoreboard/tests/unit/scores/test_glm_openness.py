"""OME-1716: published GLM weights count without trusting unverified variants."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scoreboard.classification.openness import classify_entry, classify_model
from scoreboard.scores.frontier import (
    FrontierMember,
    HistoryRow,
    compute_frontier_openness,
    replay_frontier,
)
from scoreboard.scores.pareto import ParetoEntry

GLM = "openrouter/z-ai/glm-5.3"
OPEN_ENSEMBLE = (
    "openrouter/deepseek/deepseek-v4-pro-0813",
    "openrouter/qwen/qwen3.8-2.4t-a95b",
    GLM,
)


@pytest.mark.parametrize(
    "route",
    [GLM, "z-ai/glm-5.3", "openrouter/Z-AI/GLM-5.3", "Z-AI/GLM-5.3"],
)
def test_verified_glm_weights_are_open(route: str) -> None:
    assert classify_model(route) == "open"
    assert classify_entry((route,), None) == ("open", ())


@pytest.mark.parametrize(
    "route",
    [
        "openrouter/z-ai/glm-5.4-prime",
        "openrouter/z-ai/glm-5.4-flash",
        "openrouter/z-ai/glm-5.30",
        "openrouter/z-ai/glm-5.4",
        "openrouter/z-ai/not-glm-5.3",
        "openrouter/z-ai/glm-5.3/private",
        "openrouter/other/glm-5.3",
        "glm-5.3",
    ],
)
def test_unverified_glm_routes_remain_unknown(route: str) -> None:
    assert classify_model(route) == "unknown"
    assert classify_entry((GLM, route), None) == ("closed", (route,))


def test_glm_name_does_not_override_a_different_owner() -> None:
    assert classify_model("openrouter/openai/glm-5.3") == "closed"


def test_verified_all_open_ensemble_is_open() -> None:
    assert classify_entry(OPEN_ENSEMBLE, None) == ("open", ())


def test_glm_does_not_open_a_mixed_ensemble() -> None:
    models = (*OPEN_ENSEMBLE, "openrouter/anthropic/claude-fable-5.1")
    assert classify_entry(models, None) == ("closed", ())


def test_operator_override_still_closes_verified_glm() -> None:
    assert classify_entry(OPEN_ENSEMBLE, "closed") == ("closed", ())


def test_glm_correction_reaches_frontier_and_history_without_a_new_revision() -> None:
    # STORY: five non-dominated entries, three with downloadable weights. The old
    # registry counted only two; the same stored inputs must now give 60%.
    models = [
        (OPEN_ENSEMBLE[0],),
        (OPEN_ENSEMBLE[1],),
        (GLM,),
        ("openrouter/anthropic/claude-fable-5.1",),
        ("openrouter/x-ai/grok-4.7",),
    ]
    entries = [
        ParetoEntry(str(i), str(i), "existing-revision", 0.5 + i / 10, Decimal(i + 1))
        for i in range(len(models))
    ]
    at = datetime(2026, 10, 21, tzinfo=UTC)
    history = [HistoryRow(e.source_id, e.spec_id, e.score, e.run_cost_usd, at) for e in entries]
    members = {str(i): FrontierMember(str(i), routes, None) for i, routes in enumerate(models)}

    result = compute_frontier_openness(entries, replay_frontier(history), members, pinned=True)

    assert result.frontier_size == 5
    assert (result.open_count, result.closed_count) == (3, 2)
    assert result.open_share == 0.6
    assert result.unrecognised_models == ["openrouter/x-ai/grok-4.7"]
    assert len(result.trend) == 1
    assert result.trend[0].at == at
    assert result.trend[0].open_share == 0.6
    assert (result.trend[0].open_count, result.trend[0].closed_count) == (3, 2)
