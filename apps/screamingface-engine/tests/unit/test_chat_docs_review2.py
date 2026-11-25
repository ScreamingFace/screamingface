"""RR-S19 and RR-S20 of prd/review-round-2.md: the docs pages state the rules of review round 2.

FEATURE: OpenAI-compatible Engine API, review round 2, unit U-H. public-docs has no test runner,
so this Engine unit test reads the page sources from the repo. It skips when public-docs is not
in the checkout.

STORY: as a developer, I read the docs page of the chat endpoint and find the new rules (the
ignored fields, a cache hit of the final step, the result limit, the retry of an input store
outage, the body read limit and the OpenAI retries) before an agent trips over them.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
GUIDE = DOCS / "src/pages/sf-client/guides/OpenAiApiPage.vue"
API_PAGE = DOCS / "src/pages/sf-client/api/ChatPage.vue"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")

_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL)
_ITEM = re.compile(r'<li\b[^>]*\bdata-limit="([a-z0-9-]+)"[^>]*>(.*?)</li>', re.DOTALL)


def _plain(fragment: str) -> str:
    """The text of a markup fragment: no tags, no entities, one space for each white space run."""

    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _rows(source: str) -> list[str]:
    """The plain text of each table row of a page."""

    return [_plain(match.group(1)) for match in _ROW.finditer(source)]


def _row(source: str, first_cell: str) -> str:
    """The one table row whose text starts with `first_cell`."""

    rows = [row for row in _rows(source) if row.startswith(first_cell + " ")]
    assert len(rows) == 1, f"expected one row that starts with {first_cell!r}, got {rows}"
    return rows[0]


def _limit(source: str, key: str) -> str:
    """The plain text of the limit item with this data-limit key."""

    items = {match.group(1): _plain(match.group(2)) for match in _ITEM.finditer(source)}
    assert key in items, f"the limit {key!r} is not on the page"
    return items[key]


@pytest.mark.parametrize("page", [GUIDE, API_PAGE], ids=["guide-page", "api-page"])
def test_page_says_why_the_openai_client_needs_max_retries_zero(page: Path) -> None:
    """RR-S19: each page with an OpenAI client example says why the retries are off."""
    text = _plain(page.read_text(encoding="utf-8"))
    assert "Set max_retries=0 on the OpenAI client." in text
    assert "sends the request two more times by default" in text
    assert "each try is a new paid run of the ensemble" in text


def test_guide_names_the_ignored_fields_of_the_reply() -> None:
    """RR-S12: the reply names the ignored fields, with the limits of the list."""
    source = GUIDE.read_text(encoding="utf-8")
    item = _limit(source, "unknown-fields")
    for phrase in (
        "screamingface.ignored_parameters",
        "sorted",
        "at most 32 names",
        "longer than 64 characters",
        "absent when the Engine ignored no field",
        "stream",
    ):
        assert phrase in item, phrase
    assert "ignored_parameters" in _row(source, "ignored_parameters")


def test_guide_says_that_n_below_one_is_invalid() -> None:
    """RR-S11: n below 1 gets 400 invalid_request; n above 1 stays unsupported_parameter."""
    item = _limit(GUIDE.read_text(encoding="utf-8"), "unsupported-fields")
    assert "n below 1" in item
    assert "400 invalid_request" in item
    assert "400 unsupported_parameter" in item


def test_guide_says_what_final_step_holds_on_a_cache_hit() -> None:
    """RR-S14: on a hit the counts are 0 and final_step.cached is true; keep the last size."""
    source = GUIDE.read_text(encoding="utf-8")
    row = _row(source, "final_step")
    assert "cached" in row
    assert "0" in row
    item = _limit(source, "usage-sum")
    assert "final_step.cached is true" in item
    assert "last known context size" in item


def test_api_page_lists_final_step_cached() -> None:
    """RR-S14: the reply table of the API page has FinalStep.cached."""
    row = _row(API_PAGE.read_text(encoding="utf-8"), "FinalStep")
    assert "cached" in row
    assert "cache hit" in row


def test_guide_error_table_has_the_round_two_rows() -> None:
    """RR-S6, RR-S9, RR-S10: result_too_large, the two cases of chat_input_unavailable, 408."""
    source = GUIDE.read_text(encoding="utf-8")
    too_large = _row(source, "502")
    assert "result_too_large" in too_large
    assert "8,388,608 bytes" in too_large
    transient = _row(source, "503")
    assert "chat_input_unavailable" in transient
    assert "short outage of the input store" in transient
    assert "Retry-After: 5" in transient
    permanent = _row(source, "500")
    assert "chat_input_unavailable" in permanent
    assert "input record is absent" in permanent
    assert "30 seconds" in _row(source, "408")


def test_guide_states_the_total_body_read_limit() -> None:
    """RR-S10: each body has 30 seconds from its start, for each size, else 408."""
    item = _limit(GUIDE.read_text(encoding="utf-8"), "large-bodies")
    assert "Each body must arrive in full in 30 seconds from its start, for each size" in item
    assert "408 request_timeout" in item
