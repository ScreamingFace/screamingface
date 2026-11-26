"""The C5/C6 outcome, reason, branch and synthesis matrices of the Router codec.

FEATURE: Router Recipe extension. The draft and the completed record carry their evidence, so the
reason they name must be the one C6 gives that evidence; the record's branches, classifier call,
quorum and synthesis must be the ones its outcome and status ran.

INVARIANT: an impossible combination is refused by the reader, never published or coerced.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from router_decision_support import (
    BEST_ONE,
    EXACT_ALL,
    EXACT_ONE,
    attempts,
    draft_document,
    llm_evidence,
    mutate,
    record_document,
)

from screamingface_engine.router_decision import (
    RouterDecisionError,
    parse_router_decision,
    parse_router_draft,
)


def _scores(*rows: tuple[str, float]) -> dict[str, Any]:
    return {
        "source": "scoring",
        "model": "acme/router",
        "contract": "classification-scores-v1",
        "scores": [{"label": label, "score": score} for label, score in rows],
    }


def _fallback(policy: dict[str, Any], evidence: dict[str, Any], reason: str, **changes: Any) -> Any:
    fields = {"outcome": "no_selection", "reason": reason, "selected": [], "unknown_labels": []}
    return draft_document(policy=policy, evidence=evidence, **{**fields, **changes})


_TIE = _scores(("code", 0.5), ("chit", 0.5))
_UNKNOWN_MAX = _scores(("code", 0.1), ("chit", 0.8))
_REGEX_NONE = {"source": "regex", "labels": [], "unknown": [], "parse": "no_match"}


# --- the C6 reason a draft's evidence gives -------------------------------------------------------


@pytest.mark.parametrize(
    "draft",
    [
        pytest.param(_fallback(BEST_ONE, _TIE, "tie", unknown_labels=["chit"]), id="best-tie"),
        pytest.param(
            _fallback(BEST_ONE, _UNKNOWN_MAX, "unknown_selected", unknown_labels=["chit"]),
            id="best-unknown-max",
        ),
        pytest.param(
            _fallback(EXACT_ONE, llm_evidence(["code", "math"], [], "ok"), "multiple_selected"),
            id="exact-one-multiple",
        ),
        pytest.param(
            _fallback(
                EXACT_ONE,
                llm_evidence([], ["x"], "unrecognized"),
                "unknown_selected",
                unknown_labels=["x"],
            ),
            id="exact-one-unknown",
        ),
        pytest.param(
            _fallback(
                EXACT_ALL,
                llm_evidence([], ["x"], "unrecognized"),
                "unknown_only",
                unknown_labels=["x"],
            ),
            id="exact-all-unknown",
        ),
        pytest.param(_fallback(EXACT_ONE, _REGEX_NONE, "empty"), id="exact-no-match"),
        pytest.param(
            _fallback(EXACT_ALL, llm_evidence([], [], "unparsed"), "empty"), id="exact-unparsed"
        ),
        pytest.param(
            draft_document(
                policy=EXACT_ALL,
                evidence=llm_evidence(["math", "code"], [], "ok"),
                reason="exact",
                selected=[1, 0],
                unknown_labels=[],
            ),
            id="exact-all-selects-every-label",
        ),
    ],
)
def test_a_draft_names_the_reason_c6_gives_its_evidence(draft: dict[str, Any]) -> None:
    assert parse_router_draft(json.dumps(draft)).document() == draft


@pytest.mark.parametrize(
    "draft",
    [
        pytest.param(
            _fallback(BEST_ONE, _scores(("code", 0.9), ("chit", 0.1)), "tie"),
            id="best-unique-max-called-a-tie",
        ),
        pytest.param(
            draft_document(evidence=_TIE, unknown_labels=["chit"]), id="best-tie-selected"
        ),
        pytest.param(
            _fallback(BEST_ONE, _UNKNOWN_MAX, "tie", unknown_labels=["chit"]),
            id="best-unknown-max-called-a-tie",
        ),
        pytest.param(
            _fallback(EXACT_ONE, llm_evidence(["code"], [], "ok"), "empty"),
            id="exact-one-label-not-selected",
        ),
        pytest.param(
            _fallback(EXACT_ONE, llm_evidence(["code", "math"], [], "ok"), "unknown_selected"),
            id="exact-one-multiple-called-unknown",
        ),
        pytest.param(
            _fallback(EXACT_ALL, llm_evidence(["code", "math"], [], "ok"), "multiple_selected"),
            id="exact-all-multiple-not-selected",
        ),
        pytest.param(
            _fallback(
                EXACT_ALL,
                llm_evidence([], ["x"], "unrecognized"),
                "unknown_selected",
                unknown_labels=["x"],
            ),
            id="exact-all-unknown-called-unknown-selected",
        ),
        pytest.param(
            _fallback(
                EXACT_ONE,
                llm_evidence([], ["x"], "unrecognized"),
                "unknown_only",
                unknown_labels=["x"],
            ),
            id="exact-one-unknown-called-unknown-only",
        ),
        pytest.param(_fallback(EXACT_ONE, _REGEX_NONE, "unknown_only"), id="no-match-not-empty"),
        pytest.param(
            _fallback(
                EXACT_ONE, llm_evidence([], ["x"], "unparsed"), "empty", unknown_labels=["x"]
            ),
            id="unparsed-keeps-unknown",
        ),
    ],
)
def test_a_draft_whose_reason_contradicts_its_evidence_is_refused(draft: dict[str, Any]) -> None:
    with pytest.raises(RouterDecisionError):
        parse_router_draft(json.dumps(draft))


# --- the record's calls, branches and synthesis ---------------------------------------------------


def _member(index: int, label: str, model: str, code: str | None = None) -> dict[str, Any]:
    status = "answered" if code is None else "failed"
    return {
        "role": "candidate",
        "index": index,
        "label": label,
        "model": model,
        "status": status,
        "code": code,
        **attempts(),
    }


_MEMBERS = [_member(1, "math", "acme/math"), _member(0, "code", "acme/coder")]


def _subset(synthesis: dict[str, Any] | None, status: str, **changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "policy": EXACT_ALL,
        "evidence": llm_evidence(["math", "code"], [], "ok"),
        "reason": "exact",
        "selected": [
            {"index": 1, "label": "math", "model": "acme/math"},
            {"index": 0, "label": "code", "model": "acme/coder"},
        ],
        "unknown_labels": [],
        "classifier_call": {"binding": "selector_1", "cost": None, **attempts()},
        "branches": _MEMBERS,
        "quorum": {"floor": 1, "selected": 2, "answered": 2},
        "synthesis": synthesis,
        "status": status,
    }
    return record_document(**{**fields, **changes})


def _vote(status: str, reason: str | None = None, code: str | None = None) -> dict[str, Any]:
    return {"kind": "vote", "status": status, "reason": reason, "code": code}


_FAILED_GENERATE = record_document(
    status="failed", failure={"phase": "generate", "code": "aigateway_http_502"}
)


@pytest.mark.parametrize(
    ("base", "change"),
    [
        pytest.param(
            _FAILED_GENERATE,
            mutate(("branches", 0), {**record_document()["branches"][0], "status": "failed"}),
            id="failed-branch-without-code",
        ),
        pytest.param(record_document(), mutate(("branches",), []), id="answered-without-branch"),
        pytest.param(
            record_document(),
            mutate(("branches", 0, "index"), 1),
            id="answer-from-an-unselected-candidate",
        ),
        pytest.param(
            record_document(),
            mutate(("branches", 0, "model"), "acme/other"),
            id="answer-from-another-model",
        ),
        pytest.param(
            record_document(),
            mutate(("branches",), record_document()["branches"] * 2),
            id="two-branches-for-select-one",
        ),
        pytest.param(record_document(), mutate(("classifier_call",), None), id="scores-no-call"),
        pytest.param(
            record_document(
                policy=EXACT_ONE,
                evidence=llm_evidence(["code"], [], "ok"),
                reason="exact",
                unknown_labels=[],
            ),
            mutate(("classifier_call",), None),
            id="llm-no-call",
        ),
        pytest.param(
            _FAILED_GENERATE,
            mutate(
                ("branches", 0),
                {
                    **record_document()["branches"][0],
                    "status": "failed",
                    "code": "aigateway_http_503",
                },
            ),
            id="branch-code-is-not-the-failure",
        ),
        pytest.param(
            _FAILED_GENERATE,
            mutate(("branches", 0, "status"), "answered"),
            id="failed-generate-with-answered-branch",
        ),
        pytest.param(
            record_document(
                evidence=None,
                outcome="failed",
                reason=None,
                selected=[],
                unknown_labels=[],
                status="failed",
                failure={"phase": "classify", "code": "aigateway_http_422"},
            ),
            mutate(("status",), "failed"),
            id="failed-classify-with-a-branch",
        ),
        pytest.param(
            _subset(_vote("answered"), "answered"),
            mutate(("quorum", "floor"), 0),
            id="quorum-floor-zero",
        ),
        pytest.param(
            _subset(_vote("answered"), "answered"),
            mutate(("synthesis", "reason"), "no_votes"),
            id="answered-synthesis-with-reason",
        ),
        pytest.param(
            _subset(_vote("abstained", "no_votes"), "abstained"),
            mutate(("synthesis", "reason"), None),
            id="abstained-synthesis-without-reason",
        ),
        pytest.param(
            _subset(
                _vote("failed", code="vote_failed"),
                "failed",
                failure={"phase": "synthesize", "code": "vote_failed"},
            ),
            mutate(("synthesis", "code"), None),
            id="failed-synthesis-without-code",
        ),
        pytest.param(
            _subset(_vote("answered"), "answered"),
            mutate(("synthesis", "code"), "x"),
            id="answered-synthesis-with-code",
        ),
        pytest.param(
            _subset(_vote("failed", code="vote_failed"), "answered"),
            mutate(("router",), "router_1"),
            id="status-is-not-the-synthesis-status",
        ),
        pytest.param(
            _subset(_vote("answered"), "answered"),
            mutate(("quorum", "answered"), 0),
            id="synthesis-below-the-quorum-floor",
        ),
    ],
)
def test_a_record_whose_calls_contradict_its_outcome_is_refused(
    base: dict[str, Any], change: Callable[[dict[str, Any]], None]
) -> None:
    record = copy.deepcopy(base)
    change(record)

    with pytest.raises(RouterDecisionError):
        parse_router_decision(json.dumps(record))


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            record_document(branches=[], status="failed", failure=_FAILED_GENERATE["failure"]),
            id="failed-before-any-attempt",
        ),
        pytest.param(
            _subset(
                _vote("failed", code="vote_failed"),
                "failed",
                failure={"phase": "synthesize", "code": "vote_failed"},
            ),
            id="subset-synthesis-failed",
        ),
        pytest.param(
            _subset(
                None,
                "failed",
                branches=[_MEMBERS[0], _member(0, "code", "acme/coder", "aigateway_http_502")],
                quorum={"floor": 2, "selected": 2, "answered": 1},
                failure={"phase": "synthesize", "code": "quorum_not_met"},
            ),
            id="subset-quorum-not-met",
        ),
    ],
)
def test_a_record_whose_calls_fit_its_outcome_reads_back(record: dict[str, Any]) -> None:
    assert parse_router_decision(json.dumps(record)).document() == record
