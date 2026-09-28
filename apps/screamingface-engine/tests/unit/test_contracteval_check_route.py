"""The check route — where a real candidate reply becomes a graded record.

WHY this file exists (review of PR #984): `runtime._check` is the ONE production site where
`grading.verdict` / `is_abstention` / `jaccard` meet an actual candidate payload and turn into
the CHECK_SCHEMA record the confusion matrix reads. Every other test built that record by hand,
so `grading.py` and the reducer were each proven against a fixture and never against each other
through production code. Two things were unpinned as a result:

  * that an empty reply yields `correct=False` / `abstained=False` — the spec D-5 case, where a
    model that says nothing is scored wrong rather than excluded;
  * that `_check`'s output actually satisfies `bind_case_evaluation`'s own validator. A field
    drift there fails only at runtime, after inference has been paid for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.contracteval.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.contracteval.prepare import emit
from screamingface_engine.benchmarks.contracteval.runtime import _check
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_GOLD = "This Agreement is governed by Delaware law."


def _root(tmp_path: Path, *, spans: list[str] | None = None) -> Path:
    row = {
        "id": "Doc__Governing Law",
        "title": "Doc",
        "context": f"1. Governing Law. {_GOLD}",
        "question": "Which state's law governs?",
        "answers": {"text": list(spans or []), "answer_start": [0] * len(spans or [])},
    }
    emit([row], tmp_path)
    return tmp_path


def _checked(root: Path, reply: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    handler = _check(root)
    context = encode_candidate_invocation(reply, finish_reason, None)
    return json.loads(handler(Request(path="/t", context=context, intent="1", params={})))


class TestPositiveRow:
    def test_a_verbatim_quote_is_correct(self, tmp_path: Path) -> None:
        record = _checked(_root(tmp_path, spans=[_GOLD]), f"The clause reads: {_GOLD}")

        assert record["correct"] is True
        assert record["is_positive"] is True
        assert record["abstained"] is False

    def test_a_paraphrase_is_wrong(self, tmp_path: Path) -> None:
        """The whole protocol in one assertion: sharing meaning is not quoting."""

        record = _checked(_root(tmp_path, spans=[_GOLD]), "Delaware law governs this agreement.")

        assert record["correct"] is False
        assert record["abstained"] is False

    def test_an_empty_reply_is_wrong_and_is_NOT_an_abstention(self, tmp_path: Path) -> None:
        """PROTOCOL (spec D-5): a model that says nothing has answered badly, not refused.

        `abstained=False` matters as much as `correct=False`: an empty reply counted as an
        abstention would earn a true negative on negative rows and dilute the laziness rate.
        """

        record = _checked(_root(tmp_path, spans=[_GOLD]), "")

        assert record["correct"] is False
        assert record["abstained"] is False

    def test_abstaining_on_a_row_that_HAS_a_clause_is_the_laziness_case(
        self, tmp_path: Path
    ) -> None:
        record = _checked(_root(tmp_path, spans=[_GOLD]), "No related clause.")

        assert record["correct"] is False
        assert record["abstained"] is True
        assert record["is_positive"] is True


class TestNegativeRow:
    def test_abstaining_is_correct(self, tmp_path: Path) -> None:
        record = _checked(_root(tmp_path, spans=[]), "No related clause.")

        assert record["correct"] is True
        assert record["is_positive"] is False
        assert record["abstained"] is True

    def test_answering_is_wrong(self, tmp_path: Path) -> None:
        record = _checked(_root(tmp_path, spans=[]), "Section 4 covers termination.")

        assert record["correct"] is False
        assert record["abstained"] is False

    def test_jaccard_is_still_computed_and_the_population_rule_is_the_aggregate_s(
        self, tmp_path: Path
    ) -> None:
        """The record stays a plain fact about the reply; positive-rows-only (spec F-5) is the
        REDUCER's rule, so `_check` must not pre-filter it away."""

        record = _checked(_root(tmp_path, spans=[]), "Section 4 covers termination.")

        assert "jaccard" in record
        assert isinstance(record["jaccard"], float)


class TestEnvelopeContract:
    def test_the_records_check_passes_the_envelope_validator(self, tmp_path: Path) -> None:
        """The seam the review named: `_check` emits, `bind_case_evaluation` validates. Field
        drift between them fails only at runtime today — after inference is paid for."""

        for spans, reply in [
            ([_GOLD], f"Quote: {_GOLD}"),
            ([_GOLD], "No related clause."),
            ([], "No related clause."),
            ([], "Something irrelevant."),
            ([_GOLD], ""),
        ]:
            record = _checked(_root(tmp_path / f"c{len(reply)}{len(spans)}", spans=spans), reply)
            bound = bind_case_evaluation(1, [record])

            assert bound["attempts"][0]["schema"] == CHECK_SCHEMA

    def test_a_missing_answer_key_refuses_before_grading(self, tmp_path: Path) -> None:
        root = _root(tmp_path, spans=[_GOLD])
        (root / "answers" / "1.json").unlink()

        with pytest.raises(ResolutionError, match="missing or invalid"):
            _checked(root, "anything")
