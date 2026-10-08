"""DRACO's check-surface adapter — `draco-pass.v1`, the first PAID check port.

FEATURE: benchmark-independent corrective loop on DRACO (OME-829).
STORY: as a compiled `sf.CorrectiveLoop` candidate, I can ask DRACO mid-run
whether a draft is good enough to submit — one judge pass over the case rubric,
scored by the SAME weighted math that grades the benchmark, and answered with
feedback that never names a rubric criterion.

Two things separate this from IFEval's free deterministic port:

1. **It spends.** Every check is a judge call, so the loop's cost is real and the
   manifest declares `expected_check_cost: "paid"`.
2. **`passed` is invented, not intrinsic.** DRACO grades, it does not pass/fail —
   so `draco-pass.v1` names a threshold on the normalized weighted score. That
   name is protocol semantics and rides in the route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco.check_policy import CHECK_THRESHOLD, DRACO_DRAFT_FEEDBACK
from screamingface_engine.benchmarks.draco.definition import (
    CHECK_CRITERION,
    DRACO,
    DRAFT_FEEDBACK_ROUTE,
    JUDGE_MODEL,
)
from screamingface_engine.benchmarks.ensemble.policy import DRAFT_FEEDBACK_SCHEMA
from screamingface_engine.benchmarks.rubric_draft_feedback import (
    CHECK_INSTRUCTIONS,
    rubric_draft_feedback_endpoint,
)
from url4 import RelExpr, Text, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_QUESTION = "Explain why the sky looks blue."
# Distinctive requirement text: the leak test asserts none of it ever reaches feedback.
_CRITERIA = {
    "sections": [
        {
            "id": "Factual Accuracy",
            "criteria": [
                {"id": "c1", "requirement": "MUST cite Rayleigh scattering", "weight": 3},
                {"id": "c2", "requirement": "MUST name the wavelength ordering", "weight": 1},
            ],
        },
        {
            "id": "Presentation",
            "criteria": [
                {"id": "c3", "requirement": "SHOULD open with a summary", "weight": 1},
                {"id": "c4", "requirement": "MUST NOT invent a citation", "weight": -2},
            ],
        },
    ]
}
# denom(positive weights) = 3 + 1 + 1 = 5, so scores land either side of 0.7:
#   c1+c2+c3 met            -> 5/5 = 1.0   (pass)
#   c1+c2 met               -> 4/5 = 0.8   (pass)
#   c1 met                  -> 3/5 = 0.6   (fail)
#   all positives + penalty -> 3/5 = 0.6   (fail)
_MODEL_ROUTE = "/" + JUDGE_MODEL


def _assets(root: Path) -> None:
    draco = root / "draco"
    (draco / "rubrics").mkdir(parents=True)
    (draco / "cases.json").write_text(
        json.dumps([{"id": 1, "input": _QUESTION, "domain": "science"}]), encoding="utf-8"
    )
    (draco / "rubrics" / "1.json").write_text(json.dumps(_CRITERIA), encoding="utf-8")


def _node(
    tmp_path: Path,
    replies: list[str],
) -> tuple[Url4Node, list[Request]]:
    _assets(tmp_path)
    node = Url4Node("test")
    seen: list[Request] = []

    @node.endpoint(_MODEL_ROUTE)
    def judge(request: Request) -> str:
        seen.append(request)
        return replies.pop(0) if replies else "[]"

    node.endpoint(DRAFT_FEEDBACK_ROUTE)(
        rubric_draft_feedback_endpoint(
            node,
            tmp_path / "draco",
            DRACO_DRAFT_FEEDBACK,
        )
    )
    return node, seen


def _verdicts(*met: str) -> str:
    """A judge reply marking exactly `met` criteria as MET (ordinals, 1-based)."""

    order = ["c1", "c2", "c3", "c4"]
    return json.dumps(
        [
            {"id": index, "status": "MET" if name in met else "UNMET"}
            for index, name in enumerate(order, start=1)
        ]
    )


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
    return await _check_invocation(node, invocation)


async def _check_invocation(node: Url4Node, invocation: str) -> dict[str, object]:
    reply = await _call(node, {"input": _QUESTION, "invocation": invocation}, "check")
    record = json.loads(reply)
    assert isinstance(record, dict)
    return record


# --- the port record --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_strong_answer_passes_with_its_weighted_score(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1", "c2", "c3")])
    record = await _check(node, "a good answer")
    invocation = encode_candidate_invocation("a good answer", "stop", None)
    assert record == {
        "schema": DRAFT_FEEDBACK_SCHEMA,
        "passed": True,
        "satisfaction": 1.0,
        "feedback": "",
        "answer": "a good answer",
        "invocation": invocation,
    }


@pytest.mark.asyncio
async def test_a_provider_refusal_is_graded_as_its_exact_invocation_text(tmp_path: Path) -> None:
    node, seen = _node(tmp_path, [_verdicts("c1")])
    invocation = encode_candidate_invocation("", "content_filter", "I cannot answer that.")

    record = await _check_invocation(node, invocation)

    assert record["answer"] == "I cannot answer that."
    assert record["invocation"] == invocation
    assert "I cannot answer that." in seen[0].context


@pytest.mark.asyncio
async def test_a_partial_answer_above_the_threshold_still_passes(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1", "c2")])
    record = await _check(node, "mostly right")
    assert record["satisfaction"] == 0.8
    assert record["passed"] is True


@pytest.mark.asyncio
async def test_an_answer_below_the_threshold_fails_with_its_score(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1")])
    record = await _check(node, "half right")
    assert record["satisfaction"] == 0.6
    assert record["passed"] is False
    assert record["feedback"]


@pytest.mark.asyncio
async def test_a_met_penalty_criterion_subtracts_from_the_score(tmp_path: Path) -> None:
    # INVARIANT: negative-weight criteria are penalties — meeting one costs score.
    # Without the penalty this same answer would be a 1.0 pass.
    node, _ = _node(tmp_path, [_verdicts("c1", "c2", "c3", "c4")])
    record = await _check(node, "good but invented a citation")
    assert record["satisfaction"] == 0.6
    assert record["passed"] is False


@pytest.mark.asyncio
async def test_the_threshold_boundary_passes_at_exactly_the_criterion_value(
    tmp_path: Path,
) -> None:
    # A score exactly at draco-pass.v1's threshold passes (>=, not >).
    assert CHECK_THRESHOLD == 0.7
    node, _ = _node(tmp_path, [_verdicts("c1", "c2")])
    record = await _check(node, "boundary")
    satisfaction = record["satisfaction"]
    assert isinstance(satisfaction, float)
    assert satisfaction >= CHECK_THRESHOLD
    assert record["passed"] is True


# --- the judge call ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_check_is_one_judge_pass_over_the_whole_rubric(tmp_path: Path) -> None:
    # WHY one pass: the canonical protocol judges one criterion per call (5 passes
    # x N criteria). At loop rates that is hundreds of calls per case, so the check
    # is a deliberately cheaper STEERING instrument — the canonical grading still
    # scores the run.
    node, seen = _node(tmp_path, [_verdicts("c1", "c2", "c3")])
    await _check(node, "an answer")
    assert len(seen) == 1
    prompt = seen[0].context
    for requirement in ("Rayleigh scattering", "wavelength ordering", "invent a citation"):
        assert requirement in prompt


@pytest.mark.asyncio
async def test_the_judge_never_sees_criterion_weights(tmp_path: Path) -> None:
    # INVARIANT (official protocol): the judge is blind to weights, so it cannot
    # optimize for score — it only reports MET/UNMET per requirement.
    node, seen = _node(tmp_path, [_verdicts("c1")])
    await _check(node, "an answer")
    prompt = seen[0].context
    assert "weight" not in prompt.lower()
    assert "3" not in prompt.replace("c3", "").replace("[3]", "")


@pytest.mark.asyncio
async def test_the_question_and_answer_are_framed_for_the_judge(tmp_path: Path) -> None:
    node, seen = _node(tmp_path, [_verdicts("c1")])
    await _check(node, "the draft under review")
    prompt = seen[0].context
    assert _QUESTION in prompt
    assert "the draft under review" in prompt
    assert seen[0].intent == CHECK_INSTRUCTIONS


@pytest.mark.asyncio
async def test_an_answer_with_url4_metacharacters_reaches_the_judge_intact(
    tmp_path: Path,
) -> None:
    # WHY: the prompt travels as an env BINDING, never inlined into expression text —
    # quotes, commas and $refs would corrupt a rendered expression.
    nasty = 'It\'s 5, maybe 6 — cost $5 for $candidate, "quoted".'
    node, seen = _node(tmp_path, [_verdicts("c1", "c2")])
    record = await _check(node, nasty)
    assert nasty in seen[0].context
    assert record["answer"] == nasty


@pytest.mark.asyncio
async def test_each_draft_gets_its_own_judge_cache_slot(tmp_path: Path) -> None:
    # INVARIANT: a provider exact-response cache must never serve one draft's verdict
    # for another. The answer is already part of the exact request.
    node, seen = _node(tmp_path, [_verdicts("c1"), _verdicts("c1", "c2", "c3")])
    await _check(node, "first draft")
    await _check(node, "second draft")
    assert seen[0].context != seen[1].context
    assert "first draft" in seen[0].context
    assert "second draft" in seen[1].context


@pytest.mark.asyncio
async def test_the_same_draft_is_checked_deterministically(tmp_path: Path) -> None:
    node, seen = _node(tmp_path, [_verdicts("c1"), _verdicts("c1")])
    await _check(node, "same draft")
    await _check(node, "same draft")
    assert seen[0].context == seen[1].context


@pytest.mark.asyncio
async def test_check_bookkeeping_never_leaks_as_model_parameters(tmp_path: Path) -> None:
    node, seen = _node(tmp_path, [_verdicts("c1")])
    await _check(node, "an answer")
    params = dict(seen[0].params)
    assert "check_salt" not in params
    assert "check_attempt" not in params


# --- judge failure policy ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unparseable_verdict_is_retried_on_a_fresh_cache_slot(
    tmp_path: Path,
) -> None:
    # A failed verdict must never be reused: the retry varies the cache key.
    node, seen = _node(tmp_path, ["not json at all", _verdicts("c1", "c2", "c3")])
    record = await _check(node, "an answer")
    assert record["passed"] is True
    assert len(seen) == 2
    assert seen[0].context != seen[1].context
    assert "<retry_attempt>2</retry_attempt>" not in seen[0].context
    assert "<retry_attempt>2</retry_attempt>" in seen[1].context


@pytest.mark.asyncio
async def test_a_persistently_unusable_judge_fails_the_check(tmp_path: Path) -> None:
    # INVARIANT: an unusable check is an infrastructure failure, never a plausible
    # zero — a silent satisfaction=0.0 would look like a legitimate no-pass round
    # and buy the loop a retry it did not earn.
    node, _ = _node(tmp_path, ["nope", "still nope", "nope again", "and again"])
    with pytest.raises(ResolutionError, match="usable verdict"):
        await _check(node, "an answer")


@pytest.mark.asyncio
async def test_a_verdict_missing_criteria_is_rejected(tmp_path: Path) -> None:
    partial = json.dumps([{"id": 1, "status": "MET"}])
    node, _ = _node(tmp_path, [partial, partial, partial, partial])
    with pytest.raises(ResolutionError, match="usable verdict"):
        await _check(node, "an answer")


@pytest.mark.asyncio
async def test_a_verdict_with_an_unknown_status_is_rejected(tmp_path: Path) -> None:
    bogus = json.dumps([{"id": index, "status": "MAYBE"} for index in range(1, 5)])
    node, _ = _node(tmp_path, [bogus, bogus, bogus, bogus])
    with pytest.raises(ResolutionError, match="usable verdict"):
        await _check(node, "an answer")


@pytest.mark.asyncio
async def test_a_fenced_json_verdict_is_accepted(tmp_path: Path) -> None:
    # Judges wrap JSON in code fences; the canonical verdict parser tolerates it.
    fenced = f"```json\n{_verdicts('c1', 'c2', 'c3')}\n```"
    node, _ = _node(tmp_path, [fenced])
    record = await _check(node, "an answer")
    assert record["passed"] is True


# --- sanitization (the sealed envelope) -------------------------------------------


@pytest.mark.asyncio
async def test_feedback_names_rubric_areas_but_never_criterion_text(
    tmp_path: Path,
) -> None:
    # INVARIANT (#528 shape, sharpened for a rubric benchmark): rubric requirements
    # are the answer key. Feedback rides back into the next round's member prompt,
    # so criterion text crossing this boundary would hand the panel the marking
    # scheme. Only axis names may cross.
    node, _ = _node(tmp_path, [_verdicts("c1")])
    record = await _check(node, "half right")
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    for requirement in (
        "MUST cite Rayleigh scattering",
        "MUST name the wavelength ordering",
        "SHOULD open with a summary",
        "MUST NOT invent a citation",
        "Rayleigh",
        "wavelength",
    ):
        assert requirement not in feedback
    assert "Factual Accuracy" in feedback or "Presentation" in feedback


@pytest.mark.asyncio
async def test_feedback_names_the_axis_of_a_met_penalty(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1", "c2", "c3", "c4")])
    record = await _check(node, "invented a citation")
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    assert "Presentation" in feedback


@pytest.mark.asyncio
async def test_a_passing_check_carries_no_feedback(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1", "c2", "c3")])
    record = await _check(node, "great")
    assert record["feedback"] == ""


@pytest.mark.asyncio
async def test_the_feedback_intent_extracts_the_sanitized_text(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts("c1")])
    record = await _check(node, "half right")
    assert await _call(node, record, "feedback") == record["feedback"]


# --- case resolution + payload contract -------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_input_is_a_bounded_failure(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [])
    with pytest.raises(ResolutionError, match="no DRACO case"):
        await _call(
            node,
            {
                "input": "some other question",
                "invocation": encode_candidate_invocation("x", "stop", None),
            },
            "check",
        )


@pytest.mark.asyncio
async def test_a_malformed_payload_is_a_bounded_failure(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [])
    with pytest.raises(ResolutionError, match="input and invocation"):
        await _call(node, {"invocation": encode_candidate_invocation("x", "stop", None)}, "check")


@pytest.mark.asyncio
async def test_an_invalid_candidate_invocation_is_a_bounded_failure(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [])
    with pytest.raises(ResolutionError, match="Candidate Invocation is invalid"):
        await _call(node, {"input": _QUESTION, "invocation": "not-json"}, "check")


@pytest.mark.asyncio
async def test_an_unknown_intent_is_rejected(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [])
    with pytest.raises(ResolutionError, match="unsupported"):
        await _call(
            node,
            {
                "input": _QUESTION,
                "invocation": encode_candidate_invocation("x", "stop", None),
            },
            "grade",
        )


# --- the advertised manifest block ------------------------------------------------


# AIDEV-NOTE (OME-1513): the name is frozen by the test-change rule; what it checks now is that
# the offer is OFF — Draft Feedback is a per-Benchmark owner decision (owner rule 2026-10-07),
# and today only IFEval carries one. The check-surface route is still served, not advertised.
def test_draco_advertises_a_paid_check_surface() -> None:
    assert DRACO.check_surface is None
    # The route itself still exists and still carries the pass criterion in its address: a
    # different criterion is a different route, visible in every compiled url4.
    assert DRAFT_FEEDBACK_ROUTE.endswith(f"/check-surface/{CHECK_CRITERION}")
    assert DRACO.revision in DRAFT_FEEDBACK_ROUTE


def test_the_resource_publishes_the_check_surface_block() -> None:
    # (frozen name; see the note above) — with no offer, the resource carries NO block, which
    # is what makes the SDK refuse a Corrective Loop before any paid work starts.
    assert "check_surface" not in DRACO.resource(limit=1)


def test_the_check_instructions_are_url4_expression_safe() -> None:
    # INVARIANT: the instructions ship as a rendered intent — a single quote would
    # corrupt the expression's re-parse.
    assert "'" not in CHECK_INSTRUCTIONS
    assert "\n" not in CHECK_INSTRUCTIONS


def test_the_pass_criterion_is_named_and_pinned() -> None:
    # Changing the threshold or the judge instructions changes what "passed" MEANS
    # on every DRACO leaderboard row, so the name carries a version and this test
    # forces the bump to be deliberate.
    assert CHECK_CRITERION == "draco-pass.v1"
    assert CHECK_THRESHOLD == 0.7
