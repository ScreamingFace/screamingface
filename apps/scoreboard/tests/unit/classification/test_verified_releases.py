"""Regression cases from the independently checked October 22 weight-release audit."""

import csv
from pathlib import Path

import pytest

from scoreboard.classification.openness import classify_entry, classify_model

# WHY: freeze the audited catalog inputs, not the classifier's own list. Importing
# the implementation's keys would let deleting an entry also delete its test case.
AUDIT = Path(__file__).parents[3] / "docs" / "open-weight-evidence-2026-10-22.csv"
with AUDIT.open() as evidence:
    VERIFIED_ROUTES = [row["route"] for row in csv.DictReader(evidence)]


@pytest.mark.parametrize("route", VERIFIED_ROUTES)
def test_audited_releases_are_open_directly_and_through_openrouter(route: str) -> None:
    assert classify_model(route) == "open"
    assert classify_model(f"openrouter/{route}") == "open"
    assert classify_entry((f"openrouter/{route}",), None) == ("open", ())


@pytest.mark.parametrize("route", VERIFIED_ROUTES)
def test_weight_release_evidence_does_not_extend_to_an_unverified_variant(route: str) -> None:
    assert classify_model(f"openrouter/{route}-unreleased") == "unknown"
    _, name = route.split("/", 1)
    assert classify_model(f"openrouter/unverified-vendor/{name}") == "unknown"


@pytest.mark.parametrize(
    "route",
    [
        "z-ai/glm-5-turbo",
        "z-ai/glm-5v-turbo",
        "z-ai/glm-5.4",
        "z-ai/glm-5.3:unverified",
        "minimax/minimax-m3.1-flash:free",
        "minimax/minimax-m2-her",
        "meta/muse-spark-1.3",
        "nvidia/switchyard",
        "openrouter/auto",
        "inference-net/schematron-v2-small",
        "x-ai/grok-4.7",
    ],
)
def test_related_or_routed_models_do_not_inherit_weight_evidence(route: str) -> None:
    assert classify_model(f"openrouter/{route}") == "unknown"


@pytest.mark.parametrize("route", ["qwen/qwen3.6-plus", "qwen/qwen3.8-max-prime"])
def test_unverified_hosted_qwen_routes_override_the_vendor_heuristic(route: str) -> None:
    hosted = f"openrouter/{route}"
    assert classify_model(hosted) == "unknown"
    assert classify_entry(("openrouter/z-ai/glm-5.3-prime", hosted), None) == (
        "closed",
        (hosted,),
    )
    assert classify_entry((hosted,), "open") == ("open", ())


def test_accelerated_glm_is_open_but_musique_trio_still_requires_verified_qwen() -> None:
    prime = "openrouter/z-ai/glm-5.3-prime"
    qwen = "openrouter/qwen/qwen3.8-max-prime"
    assert classify_entry((prime,), None) == ("open", ())
    assert classify_entry((prime, "openrouter/mistralai/mistral-large-4-0", qwen), None) == (
        "closed",
        (qwen,),
    )


def test_multiple_verified_vendors_preserve_mixed_and_override_rules() -> None:
    routes = ("openrouter/minimax/minimax-m2.5", "openrouter/cohere/command-a-plus")
    assert classify_entry(routes, None) == ("open", ())
    assert classify_entry((*routes, "openrouter/anthropic/claude-fable-5.1"), None) == (
        "closed",
        (),
    )
    assert classify_entry(routes, "closed") == ("closed", ())


def test_verified_open_qwen_release_stays_open() -> None:
    assert classify_model("openrouter/qwen/qwen3.8-2.4t-a95b") == "open"
