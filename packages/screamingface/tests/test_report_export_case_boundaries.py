"""Complete Case chunks keep export work bounded without scalar-by-scalar encoding."""

from __future__ import annotations

import json

import pytest
from test_report_panel import candidate, report

from screamingface._report_export import iter_report_json
from screamingface.case_result import CaseResult


def test_complete_case_is_encoded_before_the_next_case_is_materialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = report(candidate("first", 1.0), candidate("second", 0.5))
    expected = json.dumps(source.to_dict(), ensure_ascii=False, separators=(",", ":"))
    first_case = json.dumps(
        source.candidates[0].cases[0].to_dict(), ensure_ascii=False, separators=(",", ":")
    )
    materialized: list[CaseResult] = []
    original = CaseResult.to_dict

    def record(case: CaseResult) -> dict[str, object]:
        materialized.append(case)
        return original(case)

    monkeypatch.setattr(CaseResult, "to_dict", record)
    chunks = iter_report_json(source)
    assert materialized == []
    consumed: list[str] = []
    for chunk in chunks:
        consumed.append(chunk)
        if chunk == first_case:
            break
    else:
        pytest.fail("serializer split the complete Case into scalar chunks")
    # INVARIANT: encoding one Case must neither build the next Case nor retain all Cases.
    assert materialized == [source.candidates[0].cases[0]]
    assert "".join(consumed) + "".join(chunks) == expected
    assert materialized == [candidate.cases[0] for candidate in source.candidates]
