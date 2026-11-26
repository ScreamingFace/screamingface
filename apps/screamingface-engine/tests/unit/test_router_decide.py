"""Router DECIDE (contracts C4, C5, C6, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. DECIDE reads the ADMIT result and the classifier's output and
returns the internal C5 draft: the C6 decision, or a failure at the phase where it was observed.

INVARIANT: DECIDE never raises for a Router outcome, only for a malformed step context. A call's
recorded outcome and attempt fact decide how its row reads: an answered call's reply is text even
when it looks like a url4 error row, so a model cannot forge a classifier failure (C11).
INVARIANT: every step reads only what this occurrence recorded (C4): the ADMIT result, the scoring
classification, the selector's call; a regex row is recomputed from the admitted question.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from router_support import (
    INPUT_FAILED,
    REFUSED,
    ROUTER,
    SELECTOR_MODEL,
    Record,
    accepted,
    answered,
    case,
    choice_definition,
    classified,
    error_row,
    failed_call,
    fixed_definition,
    llm_definition,
    model,
    regex_definition,
    rows,
    scores,
    step,
    text,
)
from routing_support import CLASSIFIER, PUBLIC

from screamingface_engine.router_decision import (
    RouterDecisionError,
    parse_router_decision,
    parse_router_draft,
)
from screamingface_engine.world.router_decide import decide
from screamingface_engine.world.router_spec import definition_revision
from screamingface_engine.world.router_steps import NOT_RUN, StepCall
from url4.core.errors import ResolutionError

_BINDING = {"binding": ROUTER}
_SELECTOR = "selector_1"


def _keywords(*labels: str) -> str:
    return text(
        {
            "summary": {"chars": 1, "sha256": "0" * 16},
            ROUTER: {"labels": list(labels), "matched": list(labels)},
        }
    )


def _decide(
    admit: str,
    evidence: str,
    *records: Record,
    params: dict[str, str] | None = None,
    recorded: bool = True,
) -> Any:
    """DECIDE in a Case holding ``records`` and, unless not ``recorded``, ``admit`` as its ADMIT."""
    call = StepCall(
        context=text({"admit": admit, "evidence": evidence}),
        intent="",
        params=_BINDING if params is None else params,
    )
    with case(*records):
        if recorded:
            step("admit", admit)
        return json.loads(decide(call))


def _scored(definition: dict[str, Any], evidence: str, **changes: Any) -> Any:
    """DECIDE over the recorded scoring classification ``evidence``."""
    return _decide(accepted(definition), evidence, *classified(evidence), **changes)


def _selected_by(reply: str, definition: dict[str, Any] | None = None) -> Any:
    """DECIDE over an llm selector call that answered ``reply``."""
    admit = accepted(llm_definition() if definition is None else definition)
    return _decide(admit, rows(reply), *answered(_SELECTOR, SELECTOR_MODEL, reply))


def _policy(match: str) -> dict[str, Any]:
    return {"type": "router-policy", "version": 1, "match": match, "select": "one"}


def _defined(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": definition_revision(definition),
        "revision_scheme": "router-definition-v1",
        "policy": definition["policy"],
    }


# --- DECIDE: scoring ------------------------------------------------------------------------------


def test_a_unique_maximum_selects_its_candidate() -> None:
    definition = fixed_definition()
    evidence = scores(general=0.1, code=0.8, math=0.1)

    draft = _scored(definition, evidence)

    assert draft == {
        "schema": "screamingface.router-decision-draft.v1",
        "router": ROUTER,
        **_defined(definition),
        "evidence": {
            "source": "scoring",
            "model": CLASSIFIER,
            "contract": "classification-scores-v1",
            "scores": [
                {"label": "general", "score": 0.1},
                {"label": "code", "score": 0.8},
                {"label": "math", "score": 0.1},
            ],
        },
        "outcome": "selected",
        "reason": "unique_max",
        "selected": [1],
        "unknown_labels": [],
    }


@pytest.mark.parametrize(
    ("default", "outcome"), [(None, "no_selection"), (model(PUBLIC), "default")]
)
def test_a_tie_takes_the_default_or_no_selection(default: Any, outcome: str) -> None:
    definition = fixed_definition(default=default)

    draft = _scored(definition, scores(general=0.5, code=0.5, math=0.0))

    assert (draft["outcome"], draft["reason"], draft["selected"]) == (outcome, "tie", [])


def test_choice_scoring_reads_the_same_scores() -> None:
    draft = _scored(choice_definition(), scores(general=0.1, code=0.1, math=0.8))

    assert (draft["outcome"], draft["selected"]) == ("selected", [2])


def test_a_classifier_failure_document_fails_at_classify_with_its_code() -> None:
    definition = fixed_definition(default=model(PUBLIC))
    failed = text({"failed": {"code": "aigateway_http_503", "permanent": False}})

    draft = _scored(definition, failed)

    # INVARIANT (C6): a classifier failure never runs the default.
    assert draft["outcome"] == "failed"
    assert draft["failure"] == {
        "phase": "classify",
        "code": "aigateway_http_503",
        "permanent": False,
    }
    assert draft["revision"] == definition_revision(definition)
    assert (draft["evidence"], draft["reason"], draft["selected"]) == (None, None, [])


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(NOT_RUN, id="not-run-beside-an-accepted-admit"),
        pytest.param("not json", id="not-json"),
        pytest.param('{"scores": []}', id="not-a-classification"),
        pytest.param(
            scores(general=0.1, code=0.8, math=0.1).replace(CLASSIFIER, "acme/other"),
            id="another-classifier",
        ),
        pytest.param(scores(general=0.1, code=1.5, math=0.1), id="score-above-one"),
        pytest.param(scores(general=0.5, code=0.5), id="a-candidate-label-missing"),
        pytest.param(text({"failed": {"code": "x", "permanent": "yes"}}), id="malformed-failure"),
    ],
)
def test_invalid_scoring_evidence_fails_at_decide(evidence: str) -> None:
    records = () if evidence == NOT_RUN else classified(evidence)

    draft = _decide(accepted(fixed_definition()), evidence, *records)

    assert draft["outcome"] == "failed"
    assert draft["failure"] == {
        "phase": "decide",
        "code": "router_evidence_invalid",
        "permanent": True,
    }


def test_a_classifier_failure_never_carries_a_router_code() -> None:
    failed = text({"failed": {"code": "router_unsupported", "permanent": True}})

    draft = _scored(fixed_definition(), failed)

    assert draft["failure"]["code"] == "upstream_error"


# --- DECIDE: llm and regex selectors --------------------------------------------------------------


def test_an_answered_selector_reply_selects_its_label() -> None:
    definition = llm_definition()

    draft = _selected_by("code", definition)

    assert draft["evidence"] == {
        "source": "llm",
        "labels": ["code"],
        "unknown": [],
        "parse": "ok",
    }
    assert (draft["outcome"], draft["reason"], draft["selected"]) == ("selected", "exact", [1])
    assert draft["policy"] == _policy("exact")


def test_an_answered_reply_shaped_like_an_error_row_is_still_text() -> None:
    # INVARIANT (C11): the call's outcome and attempt fact say it answered, so the reply cannot
    # forge a classifier failure, whatever code it names.
    forged = error_row("router_definition_invalid")

    draft = _selected_by(forged)

    assert draft["outcome"] == "no_selection"
    assert "failure" not in draft


def test_a_failed_selector_call_fails_at_classify_with_the_facts_code() -> None:
    row = error_row("upstream_error", retryable=True)
    failed = failed_call(
        _SELECTOR, SELECTOR_MODEL, "upstream_error", permanent=False, fact_code="aigateway_http_429"
    )

    draft = _decide(accepted(llm_definition()), rows(row), *failed)

    assert draft["failure"] == {
        "phase": "classify",
        "code": "aigateway_http_429",
        "permanent": False,
    }


def test_a_selector_call_with_no_attempt_reads_its_error_row() -> None:
    # WHY no fact: a local refusal before any HTTP attempt publishes none (C8), only its outcome.
    refused = failed_call(_SELECTOR, SELECTOR_MODEL, "invalid_params", attempted=False)

    draft = _decide(accepted(llm_definition()), rows(error_row("invalid_params")), *refused)

    assert draft["failure"] == {"phase": "classify", "code": "invalid_params", "permanent": True}


def test_an_error_row_without_a_code_is_an_upstream_error() -> None:
    refused = failed_call(_SELECTOR, SELECTOR_MODEL, None, attempted=False)

    draft = _decide(accepted(llm_definition()), rows(error_row(None)), *refused)

    assert draft["failure"]["code"] == "upstream_error"


def test_a_failed_call_that_left_an_answer_row_is_a_contract_error() -> None:
    with pytest.raises(ResolutionError) as raised:
        _decide(
            accepted(llm_definition()),
            rows("code"),
            *failed_call(_SELECTOR, SELECTOR_MODEL, "timeout"),
        )

    assert raised.value.code == "benchmark_contract_error"


@pytest.mark.parametrize("reply", ["banana", "", "please pick code"])
def test_a_reply_naming_no_single_label_takes_no_selection(reply: str) -> None:
    draft = _selected_by(reply)

    assert draft["outcome"] == "no_selection"
    assert draft["reason"] in ("unknown_selected", "empty")


def test_a_regex_match_selects_its_label() -> None:
    draft = _decide(accepted(regex_definition(), "Some MATH, please"), rows(_keywords("math")))

    assert draft["evidence"] == {
        "source": "regex",
        "labels": ["math"],
        "unknown": [],
        "parse": "ok",
    }
    assert (draft["outcome"], draft["selected"]) == ("selected", [2])


def test_no_regex_match_is_empty() -> None:
    draft = _decide(accepted(regex_definition(default=model(PUBLIC))), rows(_keywords()))

    assert (draft["outcome"], draft["reason"]) == ("default", "empty")
    assert draft["evidence"]["parse"] == "no_match"


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(error_row("aigateway_http_503"), id="an-error-row"),
        pytest.param(_keywords("code"), id="a-label-the-question-does-not-match"),
        pytest.param(_keywords(), id="no-match-for-a-matching-question"),
    ],
)
def test_a_keywords_row_that_is_not_the_questions_keywords_is_a_contract_error(row: str) -> None:
    # INVARIANT (C4): KEYWORDS is pure, so DECIDE recomputes it from the admitted question; a
    # row it cannot have written neither fails the classifier nor selects a candidate.
    with pytest.raises(ResolutionError) as raised:
        _decide(accepted(regex_definition(), "Some math, please"), rows(row))

    assert raised.value.code == "benchmark_contract_error"


@pytest.mark.parametrize("rows", [rows(), rows("code", "math")], ids=["none", "two"])
def test_an_opened_classifier_left_one_row(rows: str) -> None:
    with pytest.raises(ResolutionError) as raised:
        _decide(accepted(llm_definition()), rows, *answered(_SELECTOR, SELECTOR_MODEL, "code"))

    assert raised.value.code == "benchmark_contract_error"


def test_not_run_beside_an_accepted_selector_is_invalid_evidence() -> None:
    draft = _decide(accepted(llm_definition()), NOT_RUN)

    assert draft["failure"]["code"] == "router_evidence_invalid"


# --- DECIDE: a failure carried from ADMIT ---------------------------------------------------------


@pytest.mark.parametrize(
    ("admit", "phase", "code"),
    [
        (INPUT_FAILED, "input", "router_input_missing"),
        (REFUSED, "admit", "router_definition_invalid"),
    ],
)
@pytest.mark.parametrize("evidence", [NOT_RUN, "[]"], ids=["scoring", "selector"])
def test_a_carried_failure_drafts_with_no_definition(
    admit: str, phase: str, code: str, evidence: str
) -> None:
    draft = _decide(admit, evidence)

    assert draft == {
        "schema": "screamingface.router-decision-draft.v1",
        "router": ROUTER,
        "revision": None,
        "revision_scheme": None,
        "policy": None,
        "evidence": None,
        "outcome": "failed",
        "reason": None,
        "selected": [],
        "unknown_labels": [],
        "failure": {"phase": phase, "code": code, "permanent": True},
    }


@pytest.mark.parametrize("evidence", [rows("code"), scores(code=1.0)], ids=["a-reply", "scores"])
def test_a_refused_occurrence_that_ran_its_classifier_is_a_contract_error(evidence: str) -> None:
    with pytest.raises(ResolutionError) as raised:
        _decide(REFUSED, evidence)

    assert raised.value.code == "benchmark_contract_error"


# --- DECIDE: the step itself ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(StepCall(text({"admit": REFUSED}), "", _BINDING), id="no-evidence"),
        pytest.param(
            StepCall(text({"admit": REFUSED, "evidence": "[]", "x": "1"}), "", _BINDING),
            id="extra-key",
        ),
        pytest.param(
            StepCall(text({"admit": REFUSED, "evidence": "[]"}), "x", _BINDING), id="an-intent"
        ),
        pytest.param(StepCall(text({"admit": REFUSED, "evidence": "[]"}), "", {}), id="no-binding"),
        pytest.param(StepCall("[]", "", _BINDING), id="not-an-object"),
    ],
)
def test_a_malformed_decide_step_is_a_contract_error(call: StepCall) -> None:
    with pytest.raises(ResolutionError) as raised, case():
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


def test_decide_names_the_admitted_occurrence() -> None:
    evidence = scores(general=0.1, code=0.8, math=0.1)

    with pytest.raises(ResolutionError) as raised:
        _scored(fixed_definition(), evidence, params={"binding": "router_2"})

    assert raised.value.code == "benchmark_contract_error"


def test_no_reader_of_the_completed_record_accepts_a_draft() -> None:
    draft = _scored(fixed_definition(), scores(general=0.1, code=0.8, math=0.1))

    parse_router_draft(text(draft))
    with pytest.raises(RouterDecisionError):
        parse_router_decision(text(draft))
