"""Our grading == the paper's grading, proved in CI over real CUAD gold spans.

WHY this file exists (review of PR #984): the board claims its numbers are the paper's, and
before this the claim rested on a differential run done once in a scratchpad. That is not
evidence: it could not be re-run from the repo, its row count drifted between runs (2,970 then
2,742 for the same 400 rows), and a transcription typo in `SYSTEM_PROMPT` or a "tidy-up" of
`grading.py` would have moved our F1 off the paper's with every gate green.

The fixture carries gold spans only — the parity test compares GRADERS, which need the spans
and a synthetic reply, never the contract text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _contracteval_reference import (
    abstain_metric,
    check_include,
    confusion_scores,
    get_jaccard,
)

from screamingface_engine.benchmarks.contracteval.grading import (
    is_abstention,
    jaccard,
    verdict,
)

_FIXTURE = Path(__file__).parent / "data" / "contracteval_gold_spans.json"

#: The population the parity claim covers. Asserted, so a silently shrunken fixture — the exact
#: drift that made the scratchpad run unverifiable — fails instead of weakening the proof.
_EXPECTED_ROWS = 120
_EXPECTED_POSITIVE = 90
_EXPECTED_NEGATIVE = 30


def _rows() -> list[dict[str, Any]]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["rows"]


def _replies(gold: list[str]) -> list[str]:
    """Synthetic replies spanning every branch the graders can take."""

    replies = [
        "No related clause.",
        "no related clause",
        "  ```\nNo related clause.\n``` ",
        "After review, no related clause applies here.",
        "",
        "Some unrelated text about shipping terms.",
    ]
    if gold:
        joined = " ".join(gold)
        replies += [
            gold[0],
            joined,
            f"```\n{joined}\n```",
            f"Preamble. {joined} Trailing text.",
            gold[0][: max(1, len(gold[0]) // 2)],
            f"{joined} No related clause.",
        ]
    return replies


def test_the_fixture_still_covers_the_population_it_claims() -> None:
    rows = _rows()
    positive = sum(1 for row in rows if row["gold_spans"])

    assert len(rows) == _EXPECTED_ROWS
    assert positive == _EXPECTED_POSITIVE
    assert len(rows) - positive == _EXPECTED_NEGATIVE


def test_the_fixture_records_its_provenance() -> None:
    """A fixture of someone else's data without provenance is unattributable."""

    provenance = json.loads(_FIXTURE.read_text(encoding="utf-8"))["_provenance"]

    assert provenance["dataset"] == "theatticusproject/cuad-qa"
    assert provenance["revision"] == "d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631"
    assert "CC BY 4.0" in provenance["license"]


def test_verdict_matches_the_reference_on_every_row_and_reply() -> None:
    """PROTOCOL: the metric path's verdict — `check_include` for positives, the substring
    abstention test for negatives (spec F-3)."""

    compared = 0
    for row in _rows():
        gold = row["gold_spans"]
        for reply in _replies(gold):
            compared += 1
            expected = check_include(reply, gold) if gold else abstain_metric(reply)
            assert verdict(reply, gold) is expected, (row["source_id"], reply[:60])
    assert compared >= 1000  # the claim is only as strong as the surface it covers


def test_abstention_matches_the_reference_on_every_row_and_reply() -> None:
    compared = 0
    for row in _rows():
        for reply in _replies(row["gold_spans"]):
            compared += 1
            assert is_abstention(reply) is abstain_metric(reply), reply[:60]
    assert compared >= 1000


def test_jaccard_matches_the_reference_on_every_positive_row() -> None:
    """PROTOCOL (spec F-5): computed over `' '.join(gold)` and positive rows only."""

    compared = 0
    for row in _rows():
        gold = row["gold_spans"]
        if not gold:
            continue
        for reply in _replies(gold):
            compared += 1
            stripped = reply.strip(" \n`")
            assert jaccard(gold, stripped) == pytest.approx(
                get_jaccard(" ".join(gold), stripped), abs=1e-12
            ), (row["source_id"], reply[:60])
    assert compared >= 900


def test_our_f1_and_f2_match_the_reference_wherever_the_reference_is_defined() -> None:
    """The formulas agree on every matrix the reference can score at all."""

    from screamingface_engine.benchmarks.contracteval.aggregate import (
        _confusion_matrix_score,
    )

    for tp, fn, tn, fp in [(3, 1, 2, 2), (5, 2, 4, 1), (1, 4, 6, 3), (7, 1, 1, 1)]:
        expected = confusion_scores(tp=tp, tn=tn, fn=fn, fp=fp)
        got = _confusion_matrix_score(_synthetic_cases(tp, fn, tn, fp))
        assert got.score == pytest.approx(expected["f1"], abs=1e-4), (tp, fn, tn, fp)
        assert got.metrics["f2"] == pytest.approx(expected["f2"], abs=1e-4)
        assert got.metrics["precision"] == pytest.approx(expected["precision"], abs=1e-4)
        assert got.metrics["recall"] == pytest.approx(expected["recall"], abs=1e-4)
        assert got.metrics["accuracy"] == pytest.approx(expected["accuracy"], abs=1e-4)


def test_we_return_zero_where_the_reference_raises() -> None:
    """NAMED DEVIATION (spec §3): asserted, not hidden.

    An always-abstaining model scores no true positive, so P + R == 0 and the reference's
    `2PR/(P+R)` raises. With 70.3% of rows negative that model is realistic, so we return the
    limit 0.0. This test is the record that the difference is deliberate.
    """

    from screamingface_engine.benchmarks.contracteval.aggregate import (
        _confusion_matrix_score,
    )

    with pytest.raises(ZeroDivisionError):
        confusion_scores(tp=0, tn=3, fn=2, fp=0)

    assert _confusion_matrix_score(_synthetic_cases(0, 2, 3, 0)).score == 0.0


def _synthetic_cases(tp: int, fn: int, tn: int, fp: int) -> list[Any]:
    """Cases whose grades place them in exactly the requested confusion-matrix cells."""

    from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult

    def case(case_id: int, *, is_positive: bool, correct: bool) -> Any:
        grade = CaseGrade.model_validate(
            {
                "method": "containment",
                "score": 1.0 if correct else 0.0,
                "metrics": {"is_positive": is_positive, "abstained": False, "jaccard": 0.5},
                "checks": [],
            }
        )
        return CaseResult.model_validate(
            {
                "status": "scored",
                "case_id": case_id,
                "input": "contract",
                "output": "reply",
                "finish_reason": "stop",
                "refusal": None,
                "grade": grade.model_dump(by_alias=True),
                "failures": [],
                "metadata": {},
            }
        )

    cases: list[Any] = []
    next_id = 1
    for _ in range(tp):
        cases.append(case(next_id, is_positive=True, correct=True))
        next_id += 1
    for _ in range(fn):
        cases.append(case(next_id, is_positive=True, correct=False))
        next_id += 1
    for _ in range(tn):
        cases.append(case(next_id, is_positive=False, correct=True))
        next_id += 1
    for _ in range(fp):
        cases.append(case(next_id, is_positive=False, correct=False))
        next_id += 1
    return cases
