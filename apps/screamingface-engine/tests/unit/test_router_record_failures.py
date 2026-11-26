"""A failed C5 record: where it failed and which classifier call it names (C5, C8; Unit 5.2).

FEATURE: Router Recipe extension. A failed outcome means no policy result: the occurrence failed at
`input`, `admit`, `classify` or `decide` (C5 `outcome`); a failure after DECIDE keeps the decision
it was executing. A failed record that keeps no evidence still names only its own policy's
classifier call: the scoring call under the record's own `router_N` for `best`, a `selector_N`
call for `exact`. The call is `null` when the classifier did not run (C5 `classifier_call`), as for
`{"not_run": true}` beside an accepted ADMIT (C4), a `decide` failure.

INVARIANT: the reader refuses an impossible record, never repairs it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from router_decision_support import BEST_ONE, EXACT_ONE, attempts, record_document

from screamingface_engine.router_decision import RouterDecisionError, parse_router_decision

_SCORING_CALL = {"binding": "router_1", "cost": None, **attempts()}
_SELECTOR_CALL = {"binding": "selector_1", "cost": 0.0001, **attempts()}


def _failed(
    phase: str, policy: dict[str, Any] = BEST_ONE, call: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A record that failed at ``phase`` with no evidence, naming ``call`` as its classifier's."""
    return record_document(
        policy=policy,
        evidence=None,
        outcome="failed",
        reason=None,
        selected=[],
        unknown_labels=[],
        classifier_call=call,
        branches=[],
        status="failed",
        failure={"phase": phase, "code": "router_evidence_invalid"},
    )


def _refused(record: dict[str, Any]) -> None:
    with pytest.raises(RouterDecisionError):
        parse_router_decision(json.dumps(record))


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(_failed("classify"), id="best-classify-no-attempt"),
        pytest.param(_failed("classify", call=_SCORING_CALL), id="best-classify-attempted"),
        pytest.param(_failed("decide", call=_SCORING_CALL), id="best-decide-invalid-scores"),
        pytest.param(_failed("decide"), id="best-decide-classifier-not-run"),
        pytest.param(_failed("classify", EXACT_ONE), id="exact-classify-no-attempt"),
        pytest.param(_failed("classify", EXACT_ONE, _SELECTOR_CALL), id="exact-classify-attempted"),
        pytest.param(_failed("decide", EXACT_ONE), id="exact-decide-classifier-not-run"),
        pytest.param(_failed("decide", EXACT_ONE, _SELECTOR_CALL), id="exact-decide-answered"),
    ],
)
def test_a_failed_record_reads_back_with_its_own_classifier_call_or_none(
    record: dict[str, Any],
) -> None:
    # WHY null stays legal at decide (C4, C5): `{"not_run": true}` beside an accepted ADMIT is
    # `router_evidence_invalid`, and the classifier never ran, so there is no call to name.
    assert parse_router_decision(json.dumps(record)).document() == record


@pytest.mark.parametrize("phase", ["generate", "default", "synthesize"])
@pytest.mark.parametrize("call", [None, _SCORING_CALL], ids=["no-call", "scoring-call"])
def test_a_failed_outcome_never_fails_after_decide(phase: str, call: dict[str, Any] | None) -> None:
    # INVARIANT (C5): a failure at `generate`, `default` or `synthesize` keeps the decision it
    # executed; `outcome="failed"` is for input, admit, classify and decide only.
    _refused(_failed(phase, call=call))


@pytest.mark.parametrize("phase", ["classify", "decide"])
@pytest.mark.parametrize(
    ("policy", "binding"),
    [
        pytest.param(BEST_ONE, "model_99", id="best-candidate-binding"),
        pytest.param(BEST_ONE, "router_2", id="best-another-router"),
        pytest.param(BEST_ONE, "selector_1", id="best-selector-binding"),
        pytest.param(EXACT_ONE, "router_1", id="exact-scoring-binding"),
        pytest.param(EXACT_ONE, "model_1", id="exact-candidate-binding"),
        pytest.param(EXACT_ONE, "synthesis_1", id="exact-synthesizer-binding"),
    ],
)
def test_a_failed_record_without_evidence_names_only_its_policys_classifier_call(
    phase: str, policy: dict[str, Any], binding: str
) -> None:
    _refused(_failed(phase, policy, {**_SCORING_CALL, "binding": binding}))


@pytest.mark.parametrize("phase", ["input", "admit"])
def test_nothing_ran_before_admit_accepted(phase: str) -> None:
    record = _failed(phase, call=_SCORING_CALL)
    record.update(revision=None, revision_scheme=None, policy=None)

    _refused(record)
    record["classifier_call"] = None
    assert parse_router_decision(json.dumps(record)).document() == record
