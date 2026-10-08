"""HealthBench's draft-feedback offer — `rubric_check`'s second customer (OME-830).

FEATURE: the corrective loop on a second rubric benchmark, by CONFIGURATION.
STORY: as the next rubric benchmark, I get a mid-run draft-feedback offer by declaring
where my criteria live and how strict I am — no adapter code of my own. The
deletion test at the bottom is the acceptance: if HealthBench had needed new
Python, the template failed and should not have shipped.

HealthBench also stresses the parts DRACO could not:

- a **flat, points-weighted** rubric with no axis vocabulary at all,
- a case input that is a **chat envelope**, not a prose question,
- **negative totals** — a draft worse than an empty one must never pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.ensemble.policy import DRAFT_FEEDBACK_SCHEMA
from screamingface_engine.benchmarks.healthbench.check_policy import (
    CHECK_THRESHOLD,
    HEALTHBENCH_DRAFT_FEEDBACK,
)
from screamingface_engine.benchmarks.healthbench.definition import (
    HEALTHBENCH_WORST30,
    WORST30_VARIANT,
)
from screamingface_engine.benchmarks.healthbench.revision_inputs import JUDGE_MODEL
from screamingface_engine.benchmarks.rubric_draft_feedback import (
    RubricDraftFeedback,
    rubric_draft_feedback_endpoint,
)
from url4 import RelExpr, Text, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

# The benchmark under test here is worst30; its check route is read off its Benchmark.
_CHECK_ROUTE = WORST30_VARIANT.routes.check_surface

_TURN = "I have had a headache for three days. What should I do?"
_ENVELOPE = json.dumps(
    {"schema": CANDIDATE_INPUT_SCHEMA, "messages": [{"role": "user", "content": _TURN}]}
)
# The scoring docstring's worked example: best possible = 5 + 3 = 8.
_ITEMS = {
    "hf_id": "abc",
    "items": [
        {"rubric_id": 1, "criterion": "advises seeing a doctor", "points": 5},
        {"rubric_id": 2, "criterion": "mentions common causes", "points": 3},
        {"rubric_id": 3, "criterion": "invents a specific dosage", "points": -3},
    ],
}
_MODEL_ROUTE = "/" + JUDGE_MODEL


def _assets(root: Path) -> None:
    healthbench = root / "healthbench"
    (healthbench / "rubrics").mkdir(parents=True, exist_ok=True)
    (healthbench / "cases.json").write_text(
        json.dumps([{"id": 1, "input": _ENVELOPE}]), encoding="utf-8"
    )
    (healthbench / "rubrics" / "1.json").write_text(json.dumps(_ITEMS), encoding="utf-8")


def _node(
    tmp_path: Path,
    replies: list[str],
    *,
    config: RubricDraftFeedback = HEALTHBENCH_DRAFT_FEEDBACK,
) -> tuple[Url4Node, list[Request]]:
    _assets(tmp_path)
    node = Url4Node("test")
    seen: list[Request] = []

    @node.endpoint(_MODEL_ROUTE)
    def judge(request: Request) -> str:
        seen.append(request)
        return replies.pop(0) if replies else "[]"

    node.endpoint(_CHECK_ROUTE)(
        rubric_draft_feedback_endpoint(node, tmp_path / "healthbench", config)
    )
    return node, seen


def _verdicts(*met: int) -> str:
    return json.dumps(
        [{"id": index, "status": "MET" if index in met else "UNMET"} for index in (1, 2, 3)]
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
                RelExpr(path=_CHECK_ROUTE, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


async def _check(node: Url4Node, answer: str) -> dict[str, object]:
    invocation = encode_candidate_invocation(answer, "stop", None)
    return await _check_invocation(node, invocation)


async def _check_invocation(node: Url4Node, invocation: str) -> dict[str, object]:
    record = json.loads(await _call(node, {"input": _ENVELOPE, "invocation": invocation}, "check"))
    assert isinstance(record, dict)
    return record


# --- points-weighted scoring ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_complete_safe_answer_passes(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts(1, 2)])
    record = await _check(node, "see a doctor; common causes are...")
    invocation = encode_candidate_invocation("see a doctor; common causes are...", "stop", None)
    assert record == {
        "schema": DRAFT_FEEDBACK_SCHEMA,
        "passed": True,
        "satisfaction": 1.0,
        "feedback": "",
        "answer": "see a doctor; common causes are...",
        "invocation": invocation,
    }


@pytest.mark.asyncio
async def test_a_provider_refusal_is_graded_as_its_exact_invocation_text(tmp_path: Path) -> None:
    node, seen = _node(tmp_path, [_verdicts(3)])
    invocation = encode_candidate_invocation("", "content_filter", "I cannot answer that.")

    record = await _check_invocation(node, invocation)

    assert record["answer"] == "I cannot answer that."
    assert record["invocation"] == invocation
    assert "I cannot answer that." in seen[0].context


@pytest.mark.asyncio
async def test_the_worked_example_from_the_scoring_contract(tmp_path: Path) -> None:
    # points = [+5, +3, -3]; item 1 hit, item 2 missed, penalty hit ->
    # earned = 5 - 3 = 2, best = 8, score = 0.25.
    node, _ = _node(tmp_path, [_verdicts(1, 3)])
    record = await _check(node, "see a doctor, take 400mg")
    assert record["satisfaction"] == 0.25
    assert record["passed"] is False


@pytest.mark.asyncio
async def test_a_partial_answer_above_the_bar_passes(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts(1)])
    record = await _check(node, "see a doctor")
    assert record["satisfaction"] == 0.625
    assert record["passed"] is True


@pytest.mark.asyncio
async def test_a_partial_answer_below_the_bar_fails(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts(2)])
    record = await _check(node, "headaches have many causes")
    assert record["satisfaction"] == 0.375
    assert record["passed"] is False


@pytest.mark.asyncio
async def test_an_answer_worse_than_nothing_clamps_to_zero(tmp_path: Path) -> None:
    # INVARIANT: HealthBench's published per-case score is deliberately UNCLAMPED and
    # can go negative. A check's satisfaction must rank in [0, 1], so a negative total
    # lands at 0.0 — and can never pass, whatever the threshold.
    node, _ = _node(tmp_path, [_verdicts(3)])
    record = await _check(node, "take 400mg every hour")
    assert record["satisfaction"] == 0.0
    assert record["passed"] is False


@pytest.mark.asyncio
async def test_a_rubric_with_nothing_to_win_is_unscorable(tmp_path: Path) -> None:
    # "We could not score this" is not the same fact as "this scored zero".
    penalties = {"hf_id": "abc", "items": [{"rubric_id": 1, "criterion": "x", "points": -3}]}
    _assets(tmp_path)
    (tmp_path / "healthbench" / "rubrics" / "1.json").write_text(
        json.dumps(penalties), encoding="utf-8"
    )
    node = Url4Node("test")
    node.endpoint(_MODEL_ROUTE)(lambda request: json.dumps([{"id": 1, "status": "UNMET"}]))
    node.endpoint(_CHECK_ROUTE)(
        rubric_draft_feedback_endpoint(node, tmp_path / "healthbench", HEALTHBENCH_DRAFT_FEEDBACK)
    )
    with pytest.raises(ResolutionError, match="no positively weighted criterion"):
        await _check(node, "an answer")


# --- the chat envelope ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_judge_reads_a_flattened_transcript_not_raw_json(tmp_path: Path) -> None:
    # A HealthBench Case input is a chat envelope. The judge must see the conversation,
    # not the wire format the Candidate was handed.
    node, seen = _node(tmp_path, [_verdicts(1, 2)])
    await _check(node, "see a doctor")
    prompt = seen[0].context
    assert f"user: {_TURN}" in prompt
    assert CANDIDATE_INPUT_SCHEMA not in prompt
    assert '"messages"' not in prompt


@pytest.mark.asyncio
async def test_a_malformed_envelope_is_a_bounded_failure(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [])
    _assets(tmp_path)
    (tmp_path / "healthbench" / "cases.json").write_text(
        json.dumps([{"id": 1, "input": "{}"}]), encoding="utf-8"
    )
    with pytest.raises(ResolutionError, match="chat envelope"):
        await _call(
            node,
            {
                "input": "{}",
                "invocation": encode_candidate_invocation("x", "stop", None),
            },
            "check",
        )


# --- severity feedback (no area vocabulary exists) --------------------------------


@pytest.mark.asyncio
async def test_a_missing_requirement_reads_as_an_omission(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts(2)])
    record = await _check(node, "headaches have many causes")
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    assert "left required elements out" in feedback
    assert "prohibits" not in feedback


@pytest.mark.asyncio
async def test_a_violated_prohibition_reads_as_a_violation(tmp_path: Path) -> None:
    node, _ = _node(tmp_path, [_verdicts(1, 2, 3)])
    record = await _check(node, "see a doctor; take 400mg")
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    assert "prohibits" in feedback


@pytest.mark.asyncio
async def test_feedback_never_names_a_rubric_criterion(tmp_path: Path) -> None:
    # INVARIANT (sealed envelope): the rubric is the answer key, and HealthBench has
    # no safe category vocabulary at all — so feedback may say only WHETHER the
    # shortfall was an omission or a violation, never WHICH criterion.
    node, _ = _node(tmp_path, [_verdicts(3)])
    record = await _check(node, "take 400mg every hour")
    feedback = record["feedback"]
    assert isinstance(feedback, str)
    for criterion in ("advises seeing a doctor", "common causes", "invents a specific dosage"):
        assert criterion not in feedback
    assert "dosage" not in feedback


# --- the advertised manifest block ------------------------------------------------


# AIDEV-NOTE (OME-1513): the name is frozen by the test-change rule; what it checks now is that
# the offer is OFF — Draft Feedback is a per-Benchmark owner decision (owner rule 2026-10-07),
# and today only IFEval carries one. The check-surface route is still served, not advertised.
def test_healthbench_advertises_a_paid_check_surface() -> None:
    assert HEALTHBENCH_WORST30.check_surface is None
    assert "check_surface" not in HEALTHBENCH_WORST30.resource(limit=1)


def test_the_pass_criterion_is_named_and_pinned() -> None:
    # Half the available positive points, on the CLAMPED score. Reviewed position:
    # this is the worst-30% subset, where DRACO's 0.7 bar would never trigger and
    # max_rounds would stop being a cost cap.
    assert CHECK_THRESHOLD == 0.5
    assert HEALTHBENCH_DRAFT_FEEDBACK.criterion == "healthbench-pass.v1"
    assert HEALTHBENCH_DRAFT_FEEDBACK.threshold == CHECK_THRESHOLD


# --- the deletion test ------------------------------------------------------------


def test_the_healthbench_adapter_is_configuration_only() -> None:
    """ACCEPTANCE for the `rubric_check` extraction (OME-830).

    The whole HealthBench check adapter is one declaration. If onboarding a second
    rubric benchmark had required new marking logic, the template would have been a
    guess dressed as an abstraction — and the honest move would have been to keep two
    concrete adapters instead of shipping a pass-through.
    """

    package = (
        Path(__file__).resolve().parents[2] / "src/screamingface_engine/benchmarks/healthbench"
    )
    assert not (package / "check_surface.py").exists()

    policy = (package / "check_policy.py").read_text(encoding="utf-8")
    body = policy.split('"""', 2)[-1]
    # No functions, no classes, no control flow: arguments only.
    for construct in ("def ", "class ", "if ", "for ", "while ", "try:"):
        assert construct not in body, f"HealthBench check adapter grew {construct!r}"
    assert isinstance(HEALTHBENCH_DRAFT_FEEDBACK, RubricDraftFeedback)


def test_a_benchmark_without_areas_cannot_claim_area_feedback() -> None:
    # The declaration is validated, not merely stored: a benchmark whose rubric has no
    # area vocabulary must not be able to promise area-level feedback it cannot give.
    with pytest.raises(ValueError, match="declares no area fields"):
        RubricDraftFeedback(
            label="Fake",
            criterion="fake-pass.v1",
            threshold=0.5,
            shape=HEALTHBENCH_DRAFT_FEEDBACK.shape,
            judge_model=JUDGE_MODEL,
            feedback="areas",
        )
