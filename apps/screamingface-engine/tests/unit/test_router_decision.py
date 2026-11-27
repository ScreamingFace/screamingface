"""The C5 Router decision draft codec: DECIDE's internal draft (Unit 5.2).

FEATURE: Router Recipe extension. DECIDE returns the internal draft
`screamingface.router-decision-draft.v1`; JOIN publishes the completed
`screamingface.router-decision.v1` (`test_router_decision_record`). Only the completed record
exists outside the Engine.

INVARIANT: the reader is closed. A repeated or unknown key, a wrong type, a non-finite value or an
inconsistent combination is refused, never coerced. A draft holds labels, numbers, IDs and bounded
codes only.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from router_decision_support import (
    BEST_ONE,
    DROP,
    EXACT_ALL,
    EXACT_ONE,
    REVISION,
    SCORING,
    draft_document,
    failed_draft,
    llm_evidence,
    mutate,
)

from screamingface_engine.router_decision import (
    RouterDecisionError,
    parse_router_draft,
)

_TIED = {**SCORING, "scores": [{"label": "code", "score": 0.5}, {"label": "chit", "score": 0.5}]}
"""Scores whose maximum is shared, so C6 gives `tie`."""

# --- the draft ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "draft",
    [
        pytest.param(draft_document(), id="selected-scoring"),
        pytest.param(
            draft_document(
                evidence=_TIED,
                outcome="default",
                reason="tie",
                selected=[],
                unknown_labels=["chit"],
            ),
            id="tie",
        ),
        pytest.param(
            draft_document(
                policy=EXACT_ALL,
                evidence=llm_evidence([], [], "unparsed"),
                outcome="no_selection",
                reason="empty",
                selected=[],
                unknown_labels=[],
            ),
            id="llm-unparsed-no-selection",
        ),
        pytest.param(
            draft_document(
                policy=EXACT_ALL,
                evidence=llm_evidence(["math", "code"], ["poetry"], "unrecognized"),
                reason="exact",
                selected=[2, 0],
                unknown_labels=["poetry"],
            ),
            id="llm-subset-keeps-reply-order-and-unknown",
        ),
        pytest.param(
            draft_document(
                policy=EXACT_ONE,
                evidence={"source": "regex", "labels": [], "unknown": [], "parse": "no_match"},
                outcome="default",
                reason="empty",
                selected=[],
                unknown_labels=[],
            ),
            id="regex-no-match",
        ),
        *(
            pytest.param(failed_draft(phase), id=f"failed-{phase}")
            for phase in ("input", "admit", "classify", "decide")
        ),
    ],
)
def test_a_valid_draft_reads_back_unchanged_in_key_order(draft: dict[str, Any]) -> None:
    parsed = parse_router_draft(json.dumps(draft))

    assert list(parsed.document()) == list(draft)
    assert parsed.document() == draft


@pytest.mark.parametrize(
    ("base", "change"),
    [
        pytest.param(draft_document(), mutate(("extra",), 1), id="unknown-key"),
        pytest.param(draft_document(), mutate(("reason",), DROP), id="missing-key"),
        pytest.param(
            draft_document(), mutate(("failure",), None), id="failure-null-when-not-failed"
        ),
        pytest.param(failed_draft("classify"), mutate(("failure",), DROP), id="no-failure"),
        pytest.param(failed_draft("admit"), mutate(("revision",), REVISION), id="admit-echo"),
        pytest.param(failed_draft("input"), mutate(("policy",), BEST_ONE), id="input-echo"),
        pytest.param(failed_draft("classify"), mutate(("revision",), None), id="classify-null"),
        pytest.param(failed_draft("decide"), mutate(("evidence",), SCORING), id="failed-evidence"),
        pytest.param(failed_draft("decide"), mutate(("reason",), "tie"), id="failed-reason"),
        pytest.param(failed_draft("decide"), mutate(("selected",), [0]), id="failed-selected"),
        pytest.param(
            failed_draft("decide"), mutate(("failure", "permanent"), "true"), id="permanent-text"
        ),
        pytest.param(failed_draft("decide"), mutate(("failure", "code"), "Bad"), id="code-case"),
        pytest.param(
            failed_draft("decide"), mutate(("failure", "code"), "x" * 65), id="code-too-long"
        ),
        pytest.param(
            failed_draft("decide"), mutate(("failure", "phase"), "generate"), id="record-phase"
        ),
        pytest.param(draft_document(), mutate(("reason",), None), id="reason-null"),
        pytest.param(draft_document(), mutate(("reason",), "tie"), id="selected-with-tie"),
        pytest.param(draft_document(), mutate(("selected",), []), id="selected-empty"),
        pytest.param(draft_document(), mutate(("selected",), [0, 1]), id="two-for-select-one"),
        pytest.param(draft_document(), mutate(("selected",), [-1]), id="negative-index"),
        pytest.param(draft_document(), mutate(("selected",), [True]), id="boolean-index"),
        pytest.param(draft_document(), mutate(("evidence",), None), id="success-without-evidence"),
        pytest.param(
            draft_document(),
            mutate(("evidence",), llm_evidence(["code"], [], "ok")),
            id="selector-for-best",
        ),
        pytest.param(
            draft_document(), mutate(("evidence", "scores", 0, "score"), 1.5), id="score-high"
        ),
        pytest.param(
            draft_document(), mutate(("evidence", "scores", 0, "score"), True), id="score-bool"
        ),
        pytest.param(
            draft_document(),
            mutate(("evidence", "scores", 1, "label"), "code"),
            id="score-duplicate",
        ),
        pytest.param(
            draft_document(), mutate(("unknown_labels",), ["poetry"]), id="unknown-not-returned"
        ),
        pytest.param(
            draft_document(),
            mutate(("outcome",), "default"),
            id="default-with-selection-and-unique-max",
        ),
        pytest.param(
            draft_document(outcome="default", reason="tie", selected=[], unknown_labels=[]),
            mutate(("reason",), "exact"),
            id="default-with-exact",
        ),
    ],
)
def test_an_inconsistent_draft_is_refused(
    base: dict[str, Any], change: Callable[[dict[str, Any]], None]
) -> None:
    draft = copy.deepcopy(base)
    change(draft)

    with pytest.raises(RouterDecisionError):
        parse_router_draft(json.dumps(draft))


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(llm_evidence(["code", "code"], [], "ok"), id="repeated-label"),
        pytest.param(llm_evidence(["code"], ["x", "x"], "unrecognized"), id="repeated-unknown"),
        pytest.param(llm_evidence(["code"], ["x"], "ok"), id="ok-with-unknown"),
        pytest.param(llm_evidence(["code"], [], "unrecognized"), id="unrecognized-without-unknown"),
        pytest.param(llm_evidence([], [], "no_match"), id="llm-no-match"),
        pytest.param(llm_evidence(["code"], [], "unparsed"), id="unparsed-with-label"),
        pytest.param(llm_evidence(["code"], ["x" * 65], "unrecognized"), id="unknown-too-long"),
        pytest.param(
            llm_evidence([], [f"t{n}" for n in range(33)], "unrecognized"),
            id="thirty-three-unknown",
        ),
        pytest.param(
            {"source": "regex", "labels": ["code"], "unknown": ["x"], "parse": "ok"},
            id="regex-unknown",
        ),
        pytest.param(
            {"source": "regex", "labels": [], "unknown": [], "parse": "unparsed"},
            id="regex-unparsed",
        ),
    ],
)
def test_selector_evidence_is_one_its_source_can_produce(evidence: dict[str, Any]) -> None:
    draft = draft_document(
        policy=EXACT_ALL,
        evidence=evidence,
        reason="exact",
        selected=[0],
        unknown_labels=evidence["unknown"],
    )

    with pytest.raises(RouterDecisionError):
        parse_router_draft(json.dumps(draft))


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            json.dumps(draft_document())[:-1] + ', "router": "router_2"}', id="repeated-key"
        ),
        pytest.param(json.dumps(draft_document()).replace("0.9", "NaN"), id="nan"),
        pytest.param(json.dumps(draft_document()).replace("0.9", "1e999"), id="overflow"),
        pytest.param("[]", id="not-an-object"),
        pytest.param("{", id="not-json"),
    ],
)
def test_a_draft_that_is_not_strict_json_is_refused(text: str) -> None:
    with pytest.raises(RouterDecisionError):
        parse_router_draft(text)


def test_a_refusal_names_a_field_never_a_value() -> None:
    draft = draft_document(router="router_secret_value")

    with pytest.raises(RouterDecisionError) as caught:
        parse_router_draft(json.dumps(draft))

    assert "router" in str(caught.value)
    assert "secret" not in str(caught.value)
