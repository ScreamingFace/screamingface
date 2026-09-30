"""PB-18 — the release body holds generated facts only, and every value is escaped (PB-D9).

FEATURE: OME-1307 (E14). INVARIANT under test: nothing a caller typed reaches the body as
markdown: control characters are gone (so no value can start a new line) and every markdown
character is escaped.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from scoreboard.core.publish.release_body import ReleaseFacts, escape_markdown, render_release_body

_PUBLISHED_AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
_LAST_LINE = "Metadata as of 2026-09-29T12:00:00Z. The current metadata is on the scoreboard page."


def _facts(**overrides: Any) -> ReleaseFacts:
    base = ReleaseFacts(
        system_name="a*b_[x](y)",
        system_revision=2,
        benchmark_id="hle",
        benchmark_revision="r1",
        score=0.75,
        reporter="ana",
        authors=["ana", "bruno"],
        paper_url="https://arxiv.org/abs/1",
        scoreboard_url="https://scoreboard.test/v1/scores/abc",
        entry_count=412,
        call_count=420,
        coverage_status="complete",
        archive_sha256="a" * 64,
        published_at=_PUBLISHED_AT,
    )
    return replace(base, **overrides)


def test_escape_markdown_drops_control_characters_and_escapes_every_special() -> None:
    assert escape_markdown("a\nb\rc\x00d\x7fe\tf") == "abcdef"
    assert escape_markdown("a*b_[x](y)") == "a\\*b\\_\\[x\\]\\(y\\)"
    assert escape_markdown("\\`*_{}[]()#+-.!|<>~") == "".join(
        f"\\{c}" for c in "\\`*_{}[]()#+-.!|<>~"
    )
    assert escape_markdown("plain words 123") == "plain words 123"


def test_release_body_has_generated_fields_only_escaped() -> None:
    body = render_release_body(_facts())
    lines = body.splitlines()

    assert "System: a\\*b\\_\\[x\\]\\(y\\)" in lines
    assert "Authors: ana, bruno" in lines
    assert "Reporter: ana" in lines
    assert "Paper: https://arxiv\\.org/abs/1" in lines
    assert "Score: 0\\.75" in lines
    assert f"Archive sha256: {'a' * 64}" in lines
    assert lines[-1] == _LAST_LINE
    # No raw `<` and no unescaped `[` anywhere: nothing can open a tag or a link.
    assert re.search(r"(?<!\\)[<\[]", body) is None


def test_a_paper_url_that_is_not_http_is_left_out() -> None:
    body = render_release_body(_facts(paper_url="javascript:alert(1)"))

    assert "Paper:" not in body
    assert "javascript" not in body
    assert "Paper:" not in render_release_body(_facts(paper_url=None))


def test_a_value_cannot_start_a_new_markdown_line() -> None:
    body = render_release_body(_facts(system_name="x\n# Heading\n![i](http://evil)"))

    assert "\n# Heading" not in body
    assert "System: x\\# Heading\\!\\[i\\]\\(http://evil\\)" in body.splitlines()


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("system_name", "System:"),
        ("system_revision", "System revision:"),
        ("benchmark_revision", "Benchmark revision:"),
        ("reporter", "Reporter:"),
        ("authors", "Authors:"),
    ],
)
def test_an_unset_optional_fact_has_no_line(field: str, label: str) -> None:
    body = render_release_body(_facts(**{field: None}))

    assert label not in body


def test_a_zero_fact_is_still_shown() -> None:
    # WHY: a score of 0.0 or an empty cache (0 entries) is a fact, not a missing one.
    lines = render_release_body(_facts(score=0.0, entry_count=0, call_count=0)).splitlines()

    assert "Score: 0\\.0" in lines
    assert "Cache entries: 0" in lines
    assert "Cache calls: 0" in lines
