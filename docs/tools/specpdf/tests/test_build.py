"""Unit tests for the pure parts of the spec PDF builder.

Everything here is logic that silently corrupts a rendered document when it goes wrong: a
section that lands in neither PDF, a table row that loses a cell, a cross-reference that links
into the other part. Rendering itself is checked by looking at the PDF.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402


SOURCE = """---
title: "A document"
ticket: OME-1110
---

# 0. First

Body of nought, see §1.

# 7. Telemetry

Body of seven.

# Appendix A — deltas

Appendix body.
"""


class TestParseSource:
    def test_reads_front_matter(self):
        meta, _ = build.parse_source(SOURCE)
        assert meta["ticket"] == "OME-1110"
        assert meta["title"] == "A document"

    def test_splits_top_level_sections(self):
        _, sections = build.parse_source(SOURCE)
        assert [s.heading for s in sections] == ["0. First", "7. Telemetry", "Appendix A — deltas"]

    def test_body_excludes_the_heading(self):
        _, sections = build.parse_source(SOURCE)
        assert sections[1].body == "Body of seven."

    def test_numbers_and_anchors(self):
        _, sections = build.parse_source(SOURCE)
        assert [s.number for s in sections] == ["0", "7", "A"]
        assert [s.anchor for s in sections] == ["sec-0", "sec-7", "app-a"]

    def test_source_without_front_matter(self):
        meta, sections = build.parse_source("# 1. Only\n\nBody.\n")
        assert meta == {}
        assert len(sections) == 1


class TestClaim:
    PARTS = [
        {"id": "core", "match": ["0.", "7."]},
        {"id": "open-work", "match": ["Appendix A"]},
    ]

    def test_partitions_sections(self):
        _, sections = build.parse_source(SOURCE)
        claimed = build.claim(sections, self.PARTS)
        assert [s.heading for s in claimed["core"]] == ["0. First", "7. Telemetry"]
        assert [s.heading for s in claimed["open-work"]] == ["Appendix A — deltas"]

    def test_unclaimed_section_is_fatal(self):
        """A section no part matches would vanish from both PDFs."""
        _, sections = build.parse_source(SOURCE)
        parts = [{"id": "core", "match": ["0."]}, {"id": "open-work", "match": ["Appendix A"]}]
        with pytest.raises(SystemExit, match="claimed by no part"):
            build.claim(sections, parts)

    def test_doubly_claimed_section_is_fatal(self):
        """A section two parts match would be printed twice."""
        _, sections = build.parse_source(SOURCE)
        parts = [
            {"id": "core", "match": ["0.", "7."]},
            {"id": "open-work", "match": ["7.", "Appendix A"]},
        ]
        with pytest.raises(SystemExit, match="claimed by"):
            build.claim(sections, parts)


class TestTablePipes:
    @pytest.mark.parametrize(
        "line, expected",
        [
            ("| a | `abc_node | http_source` | b |", True),
            ("| a | `abc_node \\| http_source` | b |", False),
            # A pipe *between* two code spans is an ordinary cell separator.
            ("| `url4://`, `URL4-*` | C-I still `abc://`, `ABC-*` |", False),
            ("| plain | text | row |", False),
            ("| `a` | `b` |", False),
        ],
    )
    def test_detects_only_pipes_inside_a_span(self, line, expected):
        assert build.unescaped_pipe_in_code(line) is expected

    def test_check_names_the_offending_line(self):
        source = "intro\n\n| h |\n|---|\n| `a | b` |\n"
        with pytest.raises(SystemExit, match="line 5"):
            build.check_table_pipes(source)

    def test_prose_pipe_is_not_a_table_row(self):
        build.check_table_pipes("A sentence with `a | b` in it.\n")


class TestLinkify:
    def test_links_sections_present_in_this_part(self):
        out = build.linkify_sections("<p>see §7 now</p>", {"7"})
        assert '<a class="xref" href="#sec-7">§7</a>' in out

    def test_leaves_sections_in_the_other_part_as_plain_text(self):
        """A link to a section rendered in the companion PDF would be dead."""
        assert build.linkify_sections("<p>see §11</p>", {"7"}) == "<p>see §11</p>"

    def test_ignores_section_marks_inside_code(self):
        body = "<p><code>Part C §11.2</code> and §7</p>"
        out = build.linkify_sections(body, {"7", "11"})
        assert "<code>Part C §11.2</code>" in out
        assert 'href="#sec-7"' in out

    def test_leaves_dotted_references_alone(self):
        """§29.2.1 is a spec anchor, not a section of this document."""
        assert build.linkify_sections("<p>Part H §29.2.1</p>", {"29"}) == "<p>Part H §29.2.1</p>"


class TestMatrixTables:
    def test_tags_a_table_whose_first_header_is_empty(self):
        html = "<table>\n<thead>\n<tr>\n<th></th>\n<th>A</th>\n</tr>"
        assert 'class="matrix"' in build.tag_matrix_tables(html)

    def test_leaves_an_ordinary_table_alone(self):
        html = "<table>\n<thead>\n<tr>\n<th>Term</th>\n<th>A</th>\n</tr>"
        assert 'class="matrix"' not in build.tag_matrix_tables(html)

    def test_leaves_spec_anchors_alone(self):
        """ "Part C §11" is a spec anchor; linking it to this document's §11 misleads."""
        assert build.linkify_sections("<p>Part C §11</p>", {"11"}) == "<p>Part C §11</p>"

    @pytest.mark.parametrize("part", list("ABCDEFGHI"))
    def test_every_part_letter_is_excluded(self, part):
        body = f"<p>Part {part} §7</p>"
        assert build.linkify_sections(body, {"7"}) == body


class TestDeltaRefs:
    APPENDIX = (
        "# Appendix A\n\n| # | Was |\n|---|---|\n| 1 | landed |\n\n"
        "- **13. Part A §1.4.2 — host vs node.** Text.\n\n# Appendix B\n"
    )

    def test_accepts_resolvable_references(self):
        build.check_delta_refs("See delta 13 and delta 1.\n\n" + self.APPENDIX)

    def test_rejects_a_dangling_reference(self):
        """Markdown renumbers ordered lists, so a delta reference can drift invisibly."""
        with pytest.raises(SystemExit, match="delta\\(s\\) 99"):
            build.check_delta_refs("See delta 99.\n\n" + self.APPENDIX)

    def test_noop_without_an_appendix(self):
        build.check_delta_refs("A document with no appendices, mentioning delta 4.\n")
