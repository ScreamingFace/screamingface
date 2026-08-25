"""Contract tests for the bless tool's pure seams (OME-964).

These run in the DEFAULT test lane — no docker, no subprocesses, no dump. They pin
the data transforms `fixtures/slice_snapshot.py` stands on, because a bless that
silently mis-parses one COPY row or mis-matches one case would freeze a WRONG
golden and every later CI replay would defend the wrong number:

- COPY text escaping round-trips (the dump's rows survive parse → re-emit),
- a pg_dump COPY block parses to exactly its data rows, never the surrounding SQL,
- captured candidate bodies match archive cases exactly once — ambiguity and
  absence both refuse loudly instead of guessing,
- an authored golden conforms to ``GoldenReport`` with DERIVED counters and a
  canonical decimal score, so ``load_golden`` can never refuse a blessed file.
"""

from __future__ import annotations

import gzip
import json

import pytest
from fixtures.slice_snapshot import (
    author_golden,
    copy_escape,
    copy_unescape,
    index_payloads_by_content,
    iter_copy_rows,
    match_case_question,
    snapshot_gzip,
    splice_copy_line,
)
from harness.goldens import GOLDEN_SCHEMA, GoldenReport

# -- COPY escaping ------------------------------------------------------------------


def test_copy_escape_round_trips_the_dump_alphabet() -> None:
    # Rejects any drift in the escape table because a single mis-escaped byte
    # changes the stored response and therefore the judge's graded answer.
    payload = "line1\nline2\ttabbed\rcr and a literal backslash-n: \\n plus \\ alone"
    assert copy_unescape(copy_escape(payload)) == payload


def test_copy_escape_spells_pg_text_format() -> None:
    # The exact spellings pg's text COPY uses — the loader parses these bytes.
    assert copy_escape("a\tb\nc\\d") == "a\\tb\\nc\\\\d"


# -- COPY block parsing -------------------------------------------------------------

_COPY_BLOCK = """\
--
-- PostgreSQL database dump
--
SET client_encoding = 'UTF8';

COPY public.request_cache_entries (id, key_hash, response_json) FROM stdin;
row-1\taaaa\t{"answer": "first\\nline"}
row-2\tbbbb\t{"answer": "second"}
\\.

-- trailing SQL the parser must never treat as data
"""


def test_iter_copy_rows_yields_data_rows_only() -> None:
    # The slice is rebuilt from these rows; swallowing the terminator or the
    # surrounding SQL would corrupt the committed snapshot.
    rows = list(iter_copy_rows(_COPY_BLOCK.splitlines()))
    assert [row[0] for row in rows] == ["row-1", "row-2"]
    assert copy_unescape(rows[0][2]) == '{"answer": "first\nline"}'


def test_iter_copy_rows_refuses_a_dump_without_a_copy_block() -> None:
    with pytest.raises(ValueError, match="COPY block"):
        list(iter_copy_rows(["SET client_encoding = 'UTF8';"]))


def test_iter_copy_rows_refuses_a_truncated_copy_block() -> None:
    # A dump cut off mid-transfer ends while the block is still open. Yielding the
    # partial rows silently would bless a PARTIAL fixture whose replay half-misses;
    # the parser must refuse instead (owner review finding, OME-964).
    truncated = [
        "COPY public.request_cache_entries (id, key_hash) FROM stdin;",
        "row-1\taaaa",
        # no \. terminator — the stream ends here
    ]
    with pytest.raises(ValueError, match="truncated"):
        list(iter_copy_rows(truncated))


# -- case matching ------------------------------------------------------------------


def test_match_case_question_prefers_exact_equality() -> None:
    questions = {"What is DiD?", "What is DiD? Explain fully."}
    assert match_case_question("What is DiD?", questions) == "What is DiD?"


def test_match_case_question_accepts_unique_containment() -> None:
    # The engine may wrap the question in a template; the archive question must
    # still be found inside the rendered user text — but only when unique.
    questions = {"the staggered adoption critique"}
    rendered = "Answer accurately.\n\nthe staggered adoption critique\n\nCite sources."
    assert match_case_question(rendered, questions) == "the staggered adoption critique"


def test_match_case_question_refuses_ambiguity_and_absence() -> None:
    # Guessing here would attach the WRONG archived answer to a case and the
    # judge rows would silently miss — a frozen wrong golden, not an error.
    with pytest.raises(ValueError, match="ambiguous"):
        match_case_question("ab", {"a", "b"})
    with pytest.raises(ValueError, match="no archived case"):
        match_case_question("unrelated text", {"a-question"})


# -- payload indexing ---------------------------------------------------------------


def _payload(content: str) -> str:
    return json.dumps(
        {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "model": "openrouter/google/gemini-3-flash-preview",
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }
    )


def test_index_payloads_by_content_maps_answer_text_to_verbatim_payload() -> None:
    payloads = [_payload("answer A"), _payload("answer B")]
    index = index_payloads_by_content(payloads)
    assert index["answer A"] == payloads[0]


def test_index_payloads_by_content_refuses_duplicate_answers() -> None:
    # Two cases sharing one answer text could not be told apart when re-keying.
    with pytest.raises(ValueError, match="duplicate"):
        index_payloads_by_content([_payload("same"), _payload("same")])


# -- splice rows --------------------------------------------------------------------


def test_splice_copy_line_round_trips_through_the_copy_alphabet() -> None:
    payload = _payload("two\nlines\tand a tab")
    line = splice_copy_line(
        key_hash="c" * 64, model="openrouter/google/gemini-3-flash-preview", payload=payload
    )
    columns = line.split("\t")
    # id, key_hash, prompt_hash, provider, model, response_json,
    # response_size_bytes, created_at, updated_at, expires_at, last_hit_at, hit_count
    assert len(columns) == 12
    assert columns[1] == columns[2] == "c" * 64  # prompt_hash IS the key_hash
    assert copy_unescape(columns[5]) == payload
    assert columns[6] == str(len(payload.encode("utf-8")))


def test_splice_copy_line_is_deterministic() -> None:
    # Same inputs, same bytes — a re-bless from identical sources must not churn
    # the committed fixture.
    a = splice_copy_line(key_hash="d" * 64, model="m", payload=_payload("x"))
    b = splice_copy_line(key_hash="d" * 64, model="m", payload=_payload("x"))
    assert a == b


def test_snapshot_gzip_is_reproducible() -> None:
    text = "COPY public.request_cache_entries (id) FROM stdin;\nrow\n\\.\n"
    assert snapshot_gzip(text) == snapshot_gzip(text)
    with gzip.open(__import__("io").BytesIO(snapshot_gzip(text)), "rt") as archive:
        assert archive.read() == text


# -- golden authorship --------------------------------------------------------------


def test_author_golden_conforms_and_derives_counters() -> None:
    golden = author_golden(
        board="draco-3pass",
        revision="b8c8afd8f9dddca0",
        model="openrouter/google/gemini-3-flash-preview",
        limit=None,
        rendered_url4="url4://example/expression",
        final_score=0.5,
        case_statuses={"1": "scored", "2": "refused"},
    )
    # ``load_golden`` must accept every blessed file — validate through the SAME
    # model the test lane loads with, counters derived, score canonicalized.
    report = GoldenReport.model_validate(golden)
    assert golden["schema"] == GOLDEN_SCHEMA
    assert report.case_count == 2
    assert report.gradeable_count == 1
    assert report.final_score == "0.5"
    assert report.models == ("openrouter/google/gemini-3-flash-preview",)
    assert len(report.expression_sha) == 64


def test_author_golden_keeps_a_scoreless_run_null() -> None:
    golden = author_golden(
        board="draco-3pass",
        revision="b8c8afd8f9dddca0",
        model="m",
        limit=1,
        rendered_url4="expr",
        final_score=None,
        case_statuses={"1": "failed"},
    )
    assert golden["final_score"] is None
    assert GoldenReport.model_validate(golden).gradeable_count == 0
