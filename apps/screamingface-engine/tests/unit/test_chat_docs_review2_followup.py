"""RR-S10 follow-up of prd/review-round-2.md (F12): the docs say when the body read limit changes.

FEATURE: OpenAI-compatible Engine API, review round 2, follow-up of unit U-H. A body above
1,000,000 bytes that gets a parse place is read under a new 30 s limit from that place. The docs
state that the limit changes there, so no reader takes the first 30 s rule as the only rule.

STORY: as a developer, I read the large-bodies rule and the README bullet, and I know that the
limit of a large body starts again at its parse place.

public-docs has no test runner, so this Engine unit test reads the page sources from the repo.
It skips when public-docs is not in the checkout.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
GUIDE = DOCS / "src/pages/sf-client/guides/OpenAiApiPage.vue"
README = REPO / "apps/screamingface-engine/README.md"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")

_ITEM = re.compile(r'<li\b[^>]*\bdata-limit="([a-z0-9-]+)"[^>]*>(.*?)</li>', re.DOTALL)


def _plain(fragment: str) -> str:
    """The text of a markup fragment: no tags, no entities, one space for each white space run."""

    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _limit(source: str, key: str) -> str:
    """The plain text of the limit item with this data-limit key."""

    items = {match.group(1): _plain(match.group(2)) for match in _ITEM.finditer(source)}
    assert key in items, f"the limit {key!r} is not on the page"
    return items[key]


def _limit_lines(source: str, key: str) -> list[str]:
    """The raw source lines of the limit item with this data-limit key, from <li> to </li>."""

    lines = source.splitlines()
    start = [i for i, line in enumerate(lines) if f'data-limit="{key}"' in line]
    assert len(start) == 1, f"expected one item with data-limit {key!r}, got {len(start)}"
    end = next(i for i in range(start[0], len(lines)) if "</li>" in lines[i])
    return lines[start[0] : end + 1]


def _readme_bullet(source: str, lead: str) -> str:
    """The plain text of the README bullet that starts with `lead`, up to the next bullet."""

    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(lead)]
    assert len(starts) == 1, f"expected one bullet that starts with {lead!r}, got {len(starts)}"
    body = [lines[starts[0]]]
    for line in lines[starts[0] + 1 :]:
        if line.startswith("- ") or not line.startswith("  "):
            break
        body.append(line)
    return " ".join(" ".join(body).split())


def test_large_body_limit_says_the_limit_changes_at_the_place() -> None:
    """F12: the large-bodies item says that the limit changes at the parse place."""
    item = _limit(GUIDE.read_text(encoding="utf-8"), "large-bodies")
    assert "the limit changes" in item
    assert "from that time" in item
    assert "Each body must arrive in full in 30 seconds from its start, for each size" in item


def test_large_body_item_lines_are_wrapped() -> None:
    """F12: each source line of the large-bodies item is at most 100 characters long."""
    lines = _limit_lines(GUIDE.read_text(encoding="utf-8"), "large-bodies")
    too_long = [line for line in lines if len(line) > 100]
    assert too_long == [], f"these lines are longer than 100 characters: {too_long}"


def test_engine_readme_says_the_limit_changes_at_the_parse_place() -> None:
    """F12: the README body read time bullet says that the limit changes at the parse place."""
    bullet = _readme_bullet(README.read_text(encoding="utf-8"), "- **Body read time.**")
    assert "the limit changes" in bullet
