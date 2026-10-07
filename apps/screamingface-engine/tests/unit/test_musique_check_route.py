"""The check route — where a real Candidate reply becomes the record grading reads.

WHY this file exists: `runtime._check` is the one production site where `extract_reply` meets
an actual Candidate payload. The parser is proven on strings and the envelope on hand-built
records; this proves the two meet: what the check emits is exactly what the envelope accepts,
and the record holds what the reply COMMITTED, never a grade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.musique.case_grade import CHECK_SCHEMA, build_case_grade
from screamingface_engine.benchmarks.musique.prepare import case_records, emit, parse_rows
from screamingface_engine.benchmarks.musique.runtime import _check
from url4.peer.server import Request

_FIXTURE: Path = Path(__file__).parents[1] / "fixtures/musique/dev_two_rows.jsonl"
_FIXTURE_CASES = 2

#: The spec's first reply for `2hop__460946_294723` (gold: Miquette Giraudy, {5, 10}).
_COMMITTED_REPLY = (
    "Paragraph 10 says Green is by Steve Hillage; paragraph 5 names his partner.\n"
    "Supporting paragraphs: 10, 5\n"
    "Answer: Miquette Giraudy"
)
#: The spec's last reply: no committed lines at all.
_SENTENCE_REPLY = "The performer is Steve Hillage, whose partner is Miquette Giraudy."


def _root(tmp_path: Path) -> Path:
    """Prepare the two fixture Cases into ``tmp_path`` with the real Case Preparation."""

    cases, answers = case_records(parse_rows(_FIXTURE.read_bytes(), expected_count=_FIXTURE_CASES))
    emit(tmp_path, cases, answers)
    return tmp_path


def _checked(root: Path, reply: str, case_id: int = 1) -> dict[str, Any]:
    """Run the check route on one completed reply and decode its record."""

    context: str = encode_candidate_invocation(reply, "stop", None)
    request = Request(path="/t", context=context, intent=str(case_id), params={})
    return json.loads(_check(root)(request))


def test_a_committed_reply_records_the_answer_and_the_cited_paragraphs(tmp_path: Path) -> None:
    """Spec reply row 1: the two lines read as `Miquette Giraudy` and {5, 10}."""

    record: dict[str, Any] = _checked(_root(tmp_path), _COMMITTED_REPLY)

    assert record["answer"] == "Miquette Giraudy"
    assert record["support"] == [5, 10]
    assert record["answer_line"] is True
    assert record["support_line"] is True
    assert record["output"] == _COMMITTED_REPLY


def test_a_reply_with_no_committed_lines_is_flagged_not_refused(tmp_path: Path) -> None:
    """Spec F4/F5: the whole reply becomes the answer, the support set is empty, and both
    flags say so; the check never raises on a wrongly formatted reply."""

    record: dict[str, Any] = _checked(_root(tmp_path), _SENTENCE_REPLY)

    assert record["answer"] == _SENTENCE_REPLY
    assert record["support"] == []
    assert record["answer_line"] is False
    assert record["support_line"] is False


def test_an_empty_reply_records_an_empty_answer(tmp_path: Path) -> None:
    """A model that says nothing is graded (and scores 0), not excluded from the mean."""

    record: dict[str, Any] = _checked(_root(tmp_path), "")

    assert record["answer"] == ""
    assert record["support"] == []
    assert record["answer_line"] is False


def test_the_record_carries_no_grade(tmp_path: Path) -> None:
    """INVARIANT: the check records what the reply committed; the answer key is applied once,
    at grading. A score here would be a second place to disagree with the paper's scorer."""

    record: dict[str, Any] = _checked(_root(tmp_path), _COMMITTED_REPLY)

    assert not {"f1", "exact", "support_f1", "score"} & set(record)
    assert record["schema"] == CHECK_SCHEMA
    assert record["case_id"] == 1


def test_the_check_does_not_read_the_grading_material(tmp_path: Path) -> None:
    """Spec F7: a missing answer record is the aggregate's `missing_answer_asset`, decided on
    the shared ladder. The check needs no gold, so it never turns that into a crash here."""

    root: Path = _root(tmp_path)
    (root / "answers" / "1.json").unlink()

    assert _checked(root, _COMMITTED_REPLY)["answer"] == "Miquette Giraudy"


@pytest.mark.parametrize(
    "reply",
    [
        _COMMITTED_REPLY,
        _SENTENCE_REPLY,
        "",
        "Supporting paragraphs: 10\n**Answer:** Giraudy",
        "Answer:\nMiquette Giraudy",
    ],
)
def test_every_record_the_check_emits_passes_the_envelope_validator(
    tmp_path: Path, reply: str
) -> None:
    """The seam between the two halves: `_check` emits, `build_case_grade` validates. A field
    drift between them would otherwise fail only at run time, after inference is paid for."""

    record: dict[str, Any] = _checked(_root(tmp_path), reply)

    assert build_case_grade(1, [record])["attempts"][0] == record
