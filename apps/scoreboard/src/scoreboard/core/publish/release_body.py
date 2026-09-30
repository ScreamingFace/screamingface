"""The GitHub release body (PB-H3, PB-D9): generated facts only, every value escaped.

FEATURE: OME-1307 (E14). INVARIANT: pure, standard library only. The body holds facts the
scoreboard generated or stored, never model output, url4 text, or a request or response body.
INVARIANT: every value passes through `escape_markdown`, so a value that a caller typed (a system
name, an author, a paper url) cannot open a heading, a link, an image or a tag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

_MD_SPECIAL = set("\\`*_{}[]()#+-.!|<>~")
_ALLOWED_PAPER_SCHEMES = ("https://", "http://")


def escape_markdown(text: str) -> str:
    """Remove every control character (newlines too) and DEL, then escape every markdown char.

    WHY drop control characters first: with no newline, a value cannot start a new line, so it
    cannot start a heading or a list item either. The escape handles the rest.
    """
    kept = "".join(char for char in text if ord(char) >= 32 and ord(char) != 127)
    return "".join(f"\\{char}" if char in _MD_SPECIAL else char for char in kept)


@dataclass(frozen=True, slots=True)
class ReleaseFacts:
    system_name: str | None
    system_revision: int | None
    benchmark_id: str
    benchmark_revision: str | None
    score: float
    reporter: str | None  # already in the published local-part form
    authors: list[str] | None  # already in the published form
    paper_url: str | None
    scoreboard_url: str  # f"{public_base_url}/v1/scores/{score_id}"
    entry_count: int
    call_count: int
    coverage_status: str
    archive_sha256: str
    published_at: datetime


def _lines(facts: ReleaseFacts) -> list[tuple[str, object | None]]:
    paper = facts.paper_url if (facts.paper_url or "").startswith(_ALLOWED_PAPER_SCHEMES) else None
    return [
        ("System", facts.system_name),
        ("System revision", facts.system_revision),
        ("Benchmark", facts.benchmark_id),
        ("Benchmark revision", facts.benchmark_revision),
        ("Score", facts.score),
        ("Reporter", facts.reporter),
        ("Authors", ", ".join(facts.authors) if facts.authors else None),
        ("Paper", paper),
        ("Scoreboard", facts.scoreboard_url),
        ("Cache entries", facts.entry_count),
        ("Cache calls", facts.call_count),
        ("Coverage", facts.coverage_status),
        ("Archive sha256", facts.archive_sha256),
    ]


def render_release_body(facts: ReleaseFacts) -> str:
    """One `Label: value` line per set fact, then the fixed "Metadata as of" line.

    `paper_url` is shown only when it starts with `https://` or `http://`, and as escaped text (no
    link markup). A fact that is None has no line.
    """
    body = [
        f"{label}: {escape_markdown(str(value))}"
        for label, value in _lines(facts)
        if value is not None
    ]
    stamp = facts.published_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body.append(f"Metadata as of {stamp}. The current metadata is on the scoreboard page.")
    return "\n".join(body)
