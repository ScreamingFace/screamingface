"""IFEval's check-surface adapter — the free deterministic port implementation.

FEATURE: benchmark-independent corrective loop (OME-796 / OME-827).
STORY: as a compiled loop candidate, I can check any draft mid-run knowing only
the case INPUT text — a black-box `$candidate` never sees `$item.id`, so the
port is input-addressed, and the adapter resolves the case behind it.

The record it returns is the sealed-envelope boundary: `passed` (all strict
checks), `satisfaction` (the fraction satisfied — the old `_strict_satisfaction`
hoisted behind the adapter), and `feedback` sanitized per the #528 precedent.
Private grading material (instruction ids, kwargs) must never cross this route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ensemble.policy import DRAFT_FEEDBACK_SCHEMA
from screamingface_engine.benchmarks.ifeval.definition import (
    DRAFT_FEEDBACK_ROUTE,
    IFEVAL,
    install_ifeval,
)
from url4 import RelExpr, Text, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node

_CASE_PROMPT = "Describe tea without commas."


def _assets(root: Path) -> None:
    (root / "instructions").mkdir(parents=True)
    (root / "cases.json").write_text(
        json.dumps([{"id": 1, "input": _CASE_PROMPT}]), encoding="utf-8"
    )
    (root / "instructions" / "1.json").write_text(
        json.dumps(
            {
                "key": 1,
                "prompt": _CASE_PROMPT,
                # Two constraints so satisfaction fractions can differ (1.0, 0.5, 0.0).
                "instruction_id_list": ["punctuation:no_comma", "change_case:english_lowercase"],
                "kwargs": [{}, {}],
            }
        ),
        encoding="utf-8",
    )


def _node(tmp_path: Path) -> Url4Node:
    _assets(tmp_path / "ifeval")
    node = Url4Node("test")
    install_ifeval(node, tmp_path)
    return node


# Answers graded against the two-constraint spec above:
_PASS = "tea is warm and calming"  # no comma + lowercase -> passes both (1.0)
_HALF = "Tea is warm and calming"  # no comma, has capitals -> 0.5
_FAIL = "Tea, warm, calming."  # comma + capitals -> 0.0


async def _call(node: Url4Node, payload: object, intent: str) -> str:
    result = await node.evaluate(
        render(
            expr(
                src(
                    text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                    name="payload",
                    weight=0.0,
                ),
                RelExpr(path=DRAFT_FEEDBACK_ROUTE, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


async def _check(node: Url4Node, answer: str) -> dict[str, object]:
    invocation = encode_candidate_invocation(answer, "stop", None)
    reply = await _call(node, {"input": _CASE_PROMPT, "invocation": invocation}, "check")
    record = json.loads(reply)
    assert isinstance(record, dict)
    return record


@pytest.mark.asyncio
async def test_a_fully_satisfying_answer_passes_with_unit_satisfaction(
    tmp_path: Path,
) -> None:
    node = _node(tmp_path)
    record = await _check(node, _PASS)
    assert record == {
        "schema": DRAFT_FEEDBACK_SCHEMA,
        "passed": True,
        "satisfaction": 1.0,
        "feedback": "",
        "answer": _PASS,
        "invocation": encode_candidate_invocation(_PASS, "stop", None),
    }


@pytest.mark.asyncio
async def test_a_partial_answer_fails_with_a_fractional_satisfaction(
    tmp_path: Path,
) -> None:
    node = _node(tmp_path)
    record = await _check(node, _HALF)
    assert record["passed"] is False
    assert record["satisfaction"] == 0.5
    assert record["answer"] == _HALF
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    assert feedback.startswith("The answer failed these requirements:")


@pytest.mark.asyncio
async def test_a_failing_answer_reports_zero_satisfaction(tmp_path: Path) -> None:
    node = _node(tmp_path)
    record = await _check(node, _FAIL)
    assert record["passed"] is False
    assert record["satisfaction"] == 0.0


@pytest.mark.asyncio
async def test_feedback_never_leaks_private_instruction_identifiers(
    tmp_path: Path,
) -> None:
    # INVARIANT (#528, sealed envelope): instruction ids are private grading
    # material. The port record flows INSIDE a client-compiled expression, so a
    # leak here would put the marking scheme into member prompts.
    node = _node(tmp_path)
    record = await _check(node, _FAIL)
    surface = json.dumps(record)
    assert "punctuation:no_comma" not in surface
    assert "change_case" not in surface


@pytest.mark.asyncio
async def test_the_feedback_intent_extracts_the_sanitized_text(tmp_path: Path) -> None:
    node = _node(tmp_path)
    record = await _check(node, _HALF)
    reply = await _call(node, record, "feedback")
    assert reply == record["feedback"]


@pytest.mark.asyncio
async def test_the_feedback_intent_rejects_a_foreign_record(tmp_path: Path) -> None:
    node = _node(tmp_path)
    with pytest.raises(ResolutionError, match="check-surface record"):
        await _call(node, {"schema": "something.else", "feedback": "x"}, "feedback")


@pytest.mark.asyncio
async def test_an_unknown_case_input_is_a_bounded_failure(tmp_path: Path) -> None:
    node = _node(tmp_path)
    with pytest.raises(ResolutionError, match="no IFEval case"):
        await _call(
            node,
            {
                "input": "an unknown prompt",
                "invocation": encode_candidate_invocation(_PASS, "stop", None),
            },
            "check",
        )


@pytest.mark.asyncio
async def test_a_malformed_payload_is_a_bounded_failure(tmp_path: Path) -> None:
    node = _node(tmp_path)
    with pytest.raises(ResolutionError, match="input and invocation"):
        await _call(
            node,
            {"invocation": encode_candidate_invocation(_PASS, "stop", None)},
            "check",
        )


@pytest.mark.asyncio
async def test_an_unknown_intent_is_rejected(tmp_path: Path) -> None:
    node = _node(tmp_path)
    with pytest.raises(ResolutionError, match="unsupported"):
        await _call(
            node,
            {
                "input": _CASE_PROMPT,
                "invocation": encode_candidate_invocation(_PASS, "stop", None),
            },
            "grade",
        )


# --- the advertised manifest block ------------------------------------------------


def test_ifeval_advertises_its_check_surface() -> None:
    surface = IFEVAL.check_surface
    assert surface is not None
    assert surface.check_route == DRAFT_FEEDBACK_ROUTE
    assert surface.feedback_intent == "feedback"
    assert surface.expected_check_cost == "free"


def test_the_resource_publishes_the_check_surface_block() -> None:
    resource = IFEVAL.resource(limit=1)
    assert resource["check_surface"] == {
        "check_route": DRAFT_FEEDBACK_ROUTE,
        "feedback_intent": "feedback",
        "expected_check_cost": "free",
    }
