"""The C5 Router decision record codec: JOIN's completed record (Unit 5.2).

FEATURE: Router Recipe extension. JOIN publishes the completed `screamingface.router-decision.v1`,
the only Router record outside the Engine; DECIDE's draft is internal (`test_router_decision`).

INVARIANT: the reader is closed. A repeated or unknown key, a wrong type, a non-finite value or an
inconsistent combination is refused, never coerced, and no reader of the completed record accepts
a draft. A record holds labels, numbers, IDs and bounded codes only.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from router_decision_support import (
    DROP,
    EXACT_ALL,
    EXACT_ONE,
    SCORING,
    attempts,
    draft_document,
    failed_draft,
    llm_evidence,
    mutate,
    record_document,
)

from screamingface_engine.router_decision import (
    DECISION_SCHEMA,
    RouterDecisionError,
    parse_router_decision,
    parse_router_draft,
)

# --- the completed record -------------------------------------------------------------------------


def _member(index: int, label: str, model: str) -> dict[str, Any]:
    branch = {"role": "candidate", "index": index, "label": label, "model": model}
    return {**branch, "status": "answered", "code": None, **attempts()}


def _subset_record(synthesis: dict[str, Any], status: str = "answered") -> dict[str, Any]:
    return record_document(
        policy=EXACT_ALL,
        evidence=llm_evidence(["math", "code"], [], "ok"),
        reason="exact",
        selected=[
            {"index": 1, "label": "math", "model": "acme/math"},
            {"index": 0, "label": "code", "model": "acme/coder"},
        ],
        unknown_labels=[],
        classifier_call={"binding": "selector_1", "cost": 0.0001, **attempts()},
        branches=[_member(1, "math", "acme/math"), _member(0, "code", "acme/coder")],
        quorum={"floor": 1, "selected": 2, "answered": 2},
        synthesis=synthesis,
        status=status,
    )


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(record_document(), id="answered-selected"),
        pytest.param(
            record_document(
                evidence={
                    **SCORING,
                    "scores": [{"label": "code", "score": 0.1}, {"label": "chit", "score": 0.8}],
                },
                outcome="default",
                reason="unknown_selected",
                selected=[],
                branches=[
                    {
                        "role": "default",
                        "index": None,
                        "label": None,
                        "model": "acme/general",
                        "status": "answered",
                        "code": None,
                        **attempts(2, None, True),
                    }
                ],
            ),
            id="answered-default",
        ),
        pytest.param(
            record_document(
                evidence={
                    **SCORING,
                    "scores": [{"label": "code", "score": 0.5}, {"label": "chit", "score": 0.5}],
                },
                outcome="no_selection",
                reason="tie",
                selected=[],
                branches=[],
                status="abstained",
            ),
            id="abstained-no-selection",
        ),
        pytest.param(
            record_document(
                branches=[
                    {
                        "role": "candidate",
                        "index": 0,
                        "label": "code",
                        "model": "acme/coder",
                        "status": "failed",
                        "code": "aigateway_http_502",
                        **attempts(1, 0, False),
                    }
                ],
                status="failed",
                failure={"phase": "generate", "code": "aigateway_http_502"},
            ),
            id="failed-generate",
        ),
        pytest.param(
            record_document(
                evidence=None,
                outcome="failed",
                reason=None,
                selected=[],
                unknown_labels=[],
                branches=[],
                status="failed",
                failure={"phase": "classify", "code": "aigateway_http_422"},
            ),
            id="failed-classify",
        ),
        pytest.param(
            record_document(
                revision=None,
                revision_scheme=None,
                policy=None,
                evidence=None,
                outcome="failed",
                reason=None,
                selected=[],
                unknown_labels=[],
                classifier_call=None,
                branches=[],
                status="failed",
                failure={"phase": "admit", "code": "router_definition_invalid"},
            ),
            id="failed-admit",
        ),
        pytest.param(
            _subset_record({"kind": "vote", "status": "answered", "reason": None, "code": None}),
            id="subset-vote",
        ),
        pytest.param(
            _subset_record(
                {
                    "kind": "model",
                    "status": "abstained",
                    "reason": "no_votes",
                    "code": None,
                    **attempts(),
                },
                status="abstained",
            ),
            id="subset-model-abstained",
        ),
    ],
)
def test_a_valid_record_reads_back_unchanged_in_key_order(record: dict[str, Any]) -> None:
    parsed = parse_router_decision(json.dumps(record))

    assert list(parsed.document()) == list(record)
    assert parsed.document() == record


@pytest.mark.parametrize(
    ("base", "change"),
    [
        pytest.param(
            record_document(), mutate(("status",), "abstained"), id="abstained-when-selected"
        ),
        pytest.param(record_document(), mutate(("failure",), DROP), id="failure-key-missing"),
        pytest.param(
            record_document(),
            mutate(("failure",), {"phase": "generate", "code": "x"}),
            id="answered-with-failure",
        ),
        pytest.param(
            record_document(status="failed", failure={"phase": "generate", "code": "x"}),
            mutate(("failure", "permanent"), True),
            id="record-failure-keeps-no-permanence",
        ),
        pytest.param(
            record_document(status="failed", failure={"phase": "default", "code": "x"}),
            mutate(("reason",), "unique_max"),
            id="default-phase-on-a-selection",
        ),
        pytest.param(
            record_document(), mutate(("branches", 0, "code"), "x"), id="answered-branch-with-code"
        ),
        pytest.param(
            record_document(), mutate(("branches", 0, "index"), None), id="candidate-no-index"
        ),
        pytest.param(
            record_document(), mutate(("branches", 0, "role"), "default"), id="default-index"
        ),
        pytest.param(
            record_document(),
            mutate(("branches", 0, "possibly_billed"), False),
            id="billed-false-at-1",
        ),
        pytest.param(
            record_document(),
            mutate(("branches", 0, "engine_attempts"), 0),
            id="zero-engine-attempts",
        ),
        pytest.param(
            record_document(), mutate(("classifier_call", "cost"), float("inf")), id="infinite-cost"
        ),
        pytest.param(
            record_document(), mutate(("classifier_call", "cost"), -1.0), id="negative-cost"
        ),
        pytest.param(
            record_document(),
            mutate(("quorum",), {"floor": 1, "selected": 1, "answered": 1}),
            id="quorum",
        ),
        pytest.param(record_document(), mutate(("selected", 0, "model"), ""), id="empty-model"),
        pytest.param(
            record_document(),
            mutate(("selected",), [{"index": 0, "label": "code"}]),
            id="selected-without-model",
        ),
        pytest.param(
            record_document(
                policy=EXACT_ONE,
                evidence={"source": "regex", "labels": ["code"], "unknown": [], "parse": "ok"},
                reason="exact",
                unknown_labels=[],
            ),
            mutate(("classifier_call",), {"binding": "selector_1", "cost": None, **attempts()}),
            id="regex-classifier-call",
        ),
        pytest.param(
            record_document(),
            mutate(("classifier_call", "binding"), "router_2"),
            id="scores-call-under-another-binding",
        ),
        pytest.param(
            _subset_record({"kind": "vote", "status": "answered", "reason": None, "code": None}),
            mutate(("synthesis", "engine_attempts"), 1),
            id="vote-attempts",
        ),
        pytest.param(
            _subset_record({"kind": "vote", "status": "answered", "reason": None, "code": None}),
            mutate(("quorum", "answered"), 3),
            id="answered-over-selected",
        ),
    ],
)
def test_an_inconsistent_record_is_refused(
    base: dict[str, Any], change: Callable[[dict[str, Any]], None]
) -> None:
    record = copy.deepcopy(base)
    change(record)

    with pytest.raises(RouterDecisionError):
        parse_router_decision(json.dumps(record))


@pytest.mark.parametrize(
    "draft", [draft_document(), failed_draft("input"), failed_draft("decide")], ids=str
)
def test_no_record_reader_accepts_a_draft(draft: dict[str, Any]) -> None:
    with pytest.raises(RouterDecisionError):
        parse_router_decision(json.dumps(draft))
    relabelled = {**draft, "schema": DECISION_SCHEMA}
    with pytest.raises(RouterDecisionError):
        parse_router_decision(json.dumps(relabelled))


def test_no_draft_reader_accepts_a_record() -> None:
    with pytest.raises(RouterDecisionError):
        parse_router_draft(json.dumps(record_document()))
