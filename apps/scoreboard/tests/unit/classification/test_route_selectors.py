"""URL4-spelled selector routes against the verified-release registry (PR #1534 review).

FEATURE: OME-1716 — open-weight credit for verified releases.
STORY: as a submitter running a `:free` or `:batch` route, my board entry is credited exactly
like the gateway route it names, and a hosted-only edition gains nothing from a selector.
"""

import csv
from pathlib import Path

import pytest

from scoreboard.classification.openness import classify_entry, classify_model

# WHY: freeze the audited catalog inputs, not the classifier's own list (same rule as
# test_verified_releases.py), so dropping a registry key cannot drop its test case.
AUDIT = Path(__file__).parents[3] / "docs" / "open-weight-evidence-2026-10-22.csv"
with AUDIT.open() as evidence:
    SELECTOR_ROUTES = [row["route"] for row in csv.DictReader(evidence) if ":" in row["route"]]


def url4_spelling(gateway_route: str) -> str:
    """The route as a submission carries it: the Engine escapes `:` as `~` (OME-873)."""
    return gateway_route.replace(":", "~")


def test_the_audit_holds_the_sixteen_selector_routes_the_review_counted() -> None:
    assert len(SELECTOR_ROUTES) == 16


@pytest.mark.parametrize("route", SELECTOR_ROUTES)
def test_a_selector_release_is_open_in_its_submitted_url4_spelling(route: str) -> None:
    submitted = f"openrouter/{url4_spelling(route)}"
    assert classify_model(submitted) == "open"
    assert classify_entry((submitted,), None) == ("open", ())


@pytest.mark.parametrize("route", SELECTOR_ROUTES)
def test_an_unaudited_selector_on_a_listed_release_stays_unknown(route: str) -> None:
    # INVARIANT: decoding `~` must not widen the exact-match registry. The audit lists each
    # selector route on its own; another selector on the same release proves nothing.
    base = route.split(":", 1)[0]
    assert classify_model(f"openrouter/{base}~unaudited") == "unknown"


HOSTED_QWEN = ("qwen/qwen3.6-plus", "qwen/qwen3.8-max-prime")


@pytest.mark.parametrize("hosted", HOSTED_QWEN)
@pytest.mark.parametrize("selector", ["~free", "~batch", ":free", ":batch", "~anything"])
def test_a_selector_does_not_buy_open_credit_for_a_hosted_qwen_edition(
    hosted: str, selector: str
) -> None:
    # INVARIANT: the hosted-edition check runs on the model before its selector and ahead of
    # the `qwen` owner rule. Otherwise a schema-valid suffix re-opens what the deny list closes.
    route = f"openrouter/{hosted}{selector}"
    assert classify_model(route) == "unknown"
    assert classify_entry((route,), None) == ("closed", (route,))
    assert classify_entry(("openrouter/z-ai/glm-5.3-prime", route), None) == (
        "closed",
        (route,),
    )


def test_a_verified_qwen_release_keeps_the_owner_rule_under_a_selector() -> None:
    assert classify_model("openrouter/qwen/qwen3.8-2.4t-a95b~free") == "open"


def test_a_route_without_a_selector_is_unchanged_by_decoding() -> None:
    assert classify_model("openrouter/z-ai/glm-5.3") == "open"
    assert classify_model("openrouter/anthropic/claude-opus-5.5") == "closed"
