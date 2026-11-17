# pyright: reportMissingImports=false
# WHY file-level: the grading module imports inspect_ai (through judge_redraw), absent in the
# extra-less typecheck install.
"""FutureX-Past levels 3-4: Futurex-Eval's rules, re-implemented, against a scripted judge.

Reference: github.com/Futurex-ai/Futurex-Eval at 2626f7a297cd87c73a45408e23af8d838f5b60e5
(``eval.py``, ``llm_judge_level_34.py``, ``metric_router.py``, ``utils.py``). It has no licence,
so the rules are ours in code and the judge prompts are ours in wording (spec §4).

The judge here is a script: these tests prove which question is asked when, and what each
answer is turned into. They do not prove what a real judge would answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable  # noqa: E402
from screamingface_engine_inspect.local_tasks.futurex_past import grading as g  # noqa: E402

_QUESTION: str = "Who will rank 1 to 3?"


class _Judge:
    """Answers each ask from a script, in order, and keeps (purpose, prompt) per call. A reply
    its parser cannot read raises as the redraw helper does once its budget is spent."""

    def __init__(self, *replies: str) -> None:
        self.replies: list[str] = list(replies)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, prompt: str, parse: Callable[[str], Any], purpose: str) -> Any:
        self.calls.append((purpose, prompt))
        verdict: Any = parse(self.replies.pop(0))
        if verdict is None:
            raise JudgeReplyUnparseable(f"no parseable reply for {purpose}", redraws=2)
        return verdict

    @property
    def purposes(self) -> list[str]:
        return [purpose for purpose, _ in self.calls]


def _grade(judge: _Judge, gold: list[Any], box: str | None, question: str = _QUESTION) -> g.Graded:
    return asyncio.run(g.grade_level_34(judge, question, gold, box))


_ROUTE_B: str = '{"metric": "legacy_type_b", "reason": "a ranking"}'
_ROUTE_SET: str = '```json\n{"metric": "unordered_set", "reason": "order is irrelevant"}\n```'
_ROUTE_A: str = 'Sure: {"metric": "legacy_type_a", "reason": "labels"}'


# ── utils.py: number parsing ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("6923.23", 6923.23),
        ("6,923.23", 6923.23),
        ("-1.5", -1.5),
        ("$115", 115.0),
        ("115%", 115.0),
        ("about 115", None),  # an inner space: not a bare number
        ("Beijing", None),
        ("", None),
    ],
)
def test_a_bare_number_is_read_by_the_official_to_float_rules(
    text: str, number: float | None
) -> None:
    assert g.to_float(text) == number


# ── the gold, as estimate_score_level_3_4 normalises it ──────────────────────────────────────


@pytest.mark.parametrize(
    ("gold", "normalised"),
    [
        (["1846.0"], [1846.0]),
        ([5], [5.0]),
        (["Beijing"], ["Beijing"]),
        (["\\text{Beijing}"], ["Beijing"]),
        (["A", "B"], ["A", "B"]),  # several items: never turned into numbers
        ([True], [True]),
    ],
)
def test_the_gold_is_unwrapped_and_a_lone_number_string_becomes_a_float(
    gold: list[Any], normalised: list[Any]
) -> None:
    assert g.normalize_gold(gold) == normalised


# ── routing (metric_router.py) ───────────────────────────────────────────────────────────────


def test_every_level_3_4_question_is_routed_once_by_the_judge() -> None:
    """Official ``route_metric`` routes EVERY level-3/4 question, one cached route each."""

    judge = _Judge(_ROUTE_B, "\\boxed{Yes}")

    graded: g.Graded = _grade(judge, ["Beijing"], "北京")

    assert judge.purposes == ["route", "match"]
    assert graded.route == "legacy_type_b"
    assert '"Beijing"' in judge.calls[0][1] and _QUESTION in judge.calls[0][1]


def test_a_yes_no_prompt_with_a_non_boolean_key_skips_the_router() -> None:
    """``detect_contract_conflict``: the prompt demands Yes/No but the key is not boolean, so
    the route stays the level's default and no router call is made."""

    judge = _Judge("\\boxed{Yes}")
    question: str = "Answer \\boxed{Yes} or \\boxed{No}: will it be Beijing?"

    graded: g.Graded = _grade(judge, ["Beijing"], "Beijing", question=question)

    assert judge.purposes == ["match"]
    assert graded.route == "legacy_type_b"


def test_an_unreadable_route_falls_back_to_the_level_default() -> None:
    """``route_metric``'s fallback: after its retries the route is ``legacy_type_b``."""

    judge = _Judge("I am not sure.", "\\boxed{Yes}")

    graded: g.Graded = _grade(judge, ["Beijing"], "Beijing")

    assert graded.route == "legacy_type_b" and graded.route_fallback is True
    assert graded.score == 1.0


@pytest.mark.parametrize(
    ("reply", "route"),
    [
        (_ROUTE_B, "legacy_type_b"),
        (_ROUTE_SET, "unordered_set"),
        (_ROUTE_A, "legacy_type_a"),
        ('{"metric": "something_else"}', None),
        ("no json here", None),
    ],
)
def test_the_route_is_read_from_the_judges_json(reply: str, route: str | None) -> None:
    assert g.parse_route(reply) == route


def test_a_labels_route_scores_by_the_level_1_2_rule_with_no_further_call() -> None:
    judge = _Judge(_ROUTE_A)

    graded: g.Graded = _grade(judge, ["C", "P"], "C")

    assert judge.purposes == ["route"]
    assert graded.score == pytest.approx(2 / 3)


# ── one number (judge_number_overall, sigma = 5% of the key) ─────────────────────────────────


def test_a_bare_number_is_scored_against_sigma_five_percent_with_no_judge_call() -> None:
    judge = _Judge(_ROUTE_B)

    graded: g.Graded = _grade(judge, [200.0], "205")

    # sigma = 0.05 * 200 = 10; 1 - (5/10)^2 = 0.75
    assert judge.purposes == ["route"]
    assert graded.score == pytest.approx(0.75)


@pytest.mark.parametrize(
    ("gold", "predicted", "score"),
    [
        (200.0, 200.0, 1.0),
        (200.0, 210.0, 0.0),  # exactly one sigma off
        (200.0, 260.0, 0.0),  # clamped at 0, never negative
        (0.0, 0.005, pytest.approx(0.75)),  # a zero key uses sigma 0.01
        (-200.0, -205.0, pytest.approx(0.75)),  # a negative key: the square takes the sign
    ],
)
def test_the_number_score_is_one_minus_the_squared_error_in_sigmas(
    gold: float, predicted: float, score: float
) -> None:
    assert g.number_score(predicted, gold) == score


def test_a_number_in_prose_is_extracted_by_the_judge() -> None:
    judge = _Judge(_ROUTE_B, "The number is \\boxed{205}.")

    graded: g.Graded = _grade(judge, ["200"], "\\text{roughly 205 points}")

    assert judge.purposes == ["route", "number"]
    assert "roughly 205 points" in judge.calls[1][1]
    assert graded.score == pytest.approx(0.75)


def test_a_reply_the_judge_finds_no_number_in_scores_zero() -> None:
    judge = _Judge(_ROUTE_B, "\\boxed{None}")

    graded: g.Graded = _grade(judge, [200.0], "no idea")

    assert graded.score == 0.0


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        ("\\boxed{205}", g.ExtractedNumber(205.0)),
        ("\\boxed{none}", g.ExtractedNumber(None)),
        ("\\boxed{about 5}", g.ExtractedNumber(None)),
        ("205", None),
    ],
)
def test_the_extracted_number_is_read_from_the_judges_box(
    reply: str, verdict: g.ExtractedNumber | None
) -> None:
    assert g.parse_number(reply) == verdict


# ── one string (judge_str_match) ─────────────────────────────────────────────────────────────


def test_a_string_key_is_matched_by_the_judge_on_the_first_comma_piece() -> None:
    """Official: the prediction is split on commas and ``model_prediction[0]`` is judged."""

    judge = _Judge(_ROUTE_B, "\\boxed{No}")

    graded: g.Graded = _grade(judge, ["Washington"], "Seattle, Washington")

    assert graded.score == 0.0
    assert "Seattle" in judge.calls[1][1] and "Seattle, Washington" not in judge.calls[1][1]


@pytest.mark.parametrize(
    ("reply", "match"), [("\\boxed{Yes}", True), ("\\boxed{No}", False), ("YES they match", True)]
)
def test_a_match_is_any_yes_in_the_judges_reply(reply: str, match: bool) -> None:
    """Official ``'yes' in ans.lower()``: any reply decides, so a match is never redrawn."""

    assert g.parse_match(reply) is match


# ── several items, ranked (judge_rank_overall) ──────────────────────────────────────────────


def test_option_letters_in_another_order_score_one_with_no_judge_call() -> None:
    """The official shortcut for multi-choice lists: sorted option tokens equal → 1.0."""

    judge = _Judge(_ROUTE_B)

    graded: g.Graded = _grade(judge, ["A", "C", "B"], "B, A, C")

    assert judge.purposes == ["route"]
    assert graded.score == 1.0


def test_a_ranking_the_judge_accepts_scores_one() -> None:
    judge = _Judge(_ROUTE_B, "Position by position they match. \\boxed{Yes}")

    graded: g.Graded = _grade(judge, ["Fritz", "Cobolli", "Jodar"], "Fritz, Cobolli, Jodar")

    assert judge.purposes == ["route", "rank"]
    assert graded.score == 1.0


def test_a_ranking_the_judge_rejects_scores_point_eight_times_the_overlap() -> None:
    judge = _Judge(_ROUTE_B, "\\boxed{No}", "Two overlap: \\boxed{2}")

    graded: g.Graded = _grade(judge, ["Fritz", "Cobolli", "Jodar"], "Cobolli, Fritz, Zverev")

    assert judge.purposes == ["route", "rank", "rank_overlap"]
    assert graded.score == pytest.approx(0.8 * 2 / 3)


def test_an_overlap_count_above_the_key_length_is_capped() -> None:
    """NAMED DEVIATION: the official code does not cap the count, so a judge that overcounts
    could score above 1; a Case score stays in [0, 1]."""

    judge = _Judge(_ROUTE_B, "\\boxed{No}", "\\boxed{5}")

    graded: g.Graded = _grade(judge, ["A1", "B1", "C1"], "x, y, z")

    assert graded.score == pytest.approx(0.8)


def test_an_unreadable_overlap_count_fails_the_case_by_name() -> None:
    """NAMED DEVIATION: the official worker scores an exception 0.0; here the Case fails as
    ``judge_reply_invalid`` and leaves Coverage, the repo rule for an unreadable judge."""

    judge = _Judge(_ROUTE_B, "\\boxed{No}", "several")

    with pytest.raises(JudgeReplyUnparseable):
        _grade(judge, ["A1", "B1", "C1"], "x, y, z")


# ── several items, unordered (judge_unordered_set_overall) ──────────────────────────────────


def test_the_same_set_in_another_case_and_order_scores_one_with_no_count() -> None:
    judge = _Judge(_ROUTE_SET)

    graded: g.Graded = _grade(judge, ["T1", "AG.AL"], "ag.al, t1, T1")

    assert judge.purposes == ["route"]
    assert graded.route == "unordered_set" and graded.score == 1.0


@pytest.mark.parametrize(
    ("count", "box", "score"),
    [
        ("\\boxed{2}", "Anyone's Legend, T1", 1.0),  # m = k = |prediction|
        ("\\boxed{1}", "Anyone's Legend, T1", pytest.approx(0.4)),
        ("\\boxed{2}", "Anyone's Legend, T1, G2", pytest.approx(0.8)),  # one extra: not full
        ("\\boxed{9}", "Anyone's Legend, T1", 1.0),  # capped at k and |prediction|
    ],
)
def test_an_unordered_set_scores_matches_over_the_key(count: str, box: str, score: float) -> None:
    judge = _Judge(_ROUTE_SET, count)

    graded: g.Graded = _grade(judge, ["AG.AL", "T1"], box)

    assert judge.purposes == ["route", "set_overlap"]
    assert graded.score == score


# ── no answer ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("box", [None, "", " , "])
def test_a_reply_with_no_answer_scores_zero_and_asks_the_judge_nothing(box: str | None) -> None:
    """A missing prediction scores 0 in the official roll-up; there is nothing to judge."""

    judge = _Judge()

    graded: g.Graded = _grade(judge, ["Beijing"], box)

    assert judge.calls == []
    assert (graded.score, graded.route) == (0.0, "no_answer")


# ── the prompts carry what the official prompts carry ───────────────────────────────────────


def test_each_judge_prompt_carries_the_question_or_items_it_compares() -> None:
    """Our wording (the reference has no licence), the official inputs: the router sees the
    question and the key; the rank and overlap prompts see the question, both lists."""

    assert _QUESTION in g.router_prompt(_QUESTION, ["A", "B"])
    rank: str = g.rank_prompt(_QUESTION, ["x", "y"], ["A", "B"])
    assert all(part in rank for part in (_QUESTION, "['x', 'y']", "['A', 'B']"))
    assert "Beijing" in g.match_prompt("北京", "Beijing")
    assert "roughly 5" in g.number_prompt("roughly 5")
    assert all(p in g.set_overlap_prompt(_QUESTION, ["x"], ["A"]) for p in ("['x']", "['A']"))


# ── review findings (sf-code-review, fidelity audit U1-U4) ──────────────────────────────────


def test_a_latex_thousands_separator_is_read_as_a_comma() -> None:
    """``\\boxed{1{,}234}`` is 1234, not 1: read by rule, with no judge call."""

    judge = _Judge(_ROUTE_B)

    graded: g.Graded = _grade(judge, [1234.0], "1{,}234")

    assert judge.purposes == ["route"]
    assert graded.score == 1.0


def test_a_number_in_prose_reaches_the_judge_as_its_first_comma_piece() -> None:
    """Futurex-Eval judges ``model_prediction[0]``, the first comma piece (fidelity U2)."""

    judge = _Judge(_ROUTE_B, "\\boxed{249.41}")

    graded: g.Graded = _grade(judge, [249.41], "about 249.41, or 498.82")

    assert judge.purposes == ["route", "number"]
    assert "about 249.41" in judge.calls[1][1] and "498.82" not in judge.calls[1][1]
    assert graded.score == 1.0


def test_option_letters_reach_the_rank_judge_sorted_as_upstream_sorts_them() -> None:
    """``judge_rank_overall`` sorts both letter lists before asking (fidelity U3)."""

    judge = _Judge(_ROUTE_B, "\\boxed{No}", "\\boxed{1}")

    _grade(judge, ["X", "B", "C"], "L, C, B")

    assert "['B', 'C', 'L']" in judge.calls[1][1] and "['B', 'C', 'X']" in judge.calls[1][1]


@pytest.mark.parametrize(
    "reply",
    [
        '{"metric": "legacy_type_a", "reason": "labels"} because the options are fixed',
        '```json\n{"metric": "legacy_type_a"}\n```\nExtra words',
    ],
)
def test_a_route_followed_by_prose_is_unreadable_as_upstream_reads_it(reply: str) -> None:
    """Upstream ``_parse_route`` calls ``json.loads`` on the whole reply when it opens with
    ``{`` (fidelity U4); trailing prose makes it unreadable, and the route falls back."""

    assert g.parse_route(reply) is None


@pytest.mark.parametrize(
    ("box", "unwrapped"),
    [
        ("\\text{A, B}", "A, B"),
        ("\\text { Beijing }", "Beijing"),
        # each option wrapped on its own: the first \text{ closes early, so no whole unwrap
        ("\\text{A}, \\text{B}", "\\text{A}, \\text{B}"),
        ("\\text{A} and \\text{B}", "\\text{A} and \\text{B}"),
        ("\\text{a {b} c}", "a {b} c"),
        ("plain", "plain"),
        (None, None),
    ],
)
def test_only_a_wrapper_that_closes_at_the_end_is_removed(
    box: str | None, unwrapped: str | None
) -> None:
    """Balanced, not greedy (fidelity audit U7): ``\\text{A}, \\text{B}`` is two wrapped options."""

    assert g.unwrap_text(box) == unwrapped


@pytest.mark.parametrize(
    ("box", "tokens"),
    [
        ("\\text{A}, \\text{B}", ["A", "B"]),
        ("\\text{A, B}", ["A", "B"]),
        ("T1, \\text{AG.AL}", ["T1", "AG.AL"]),
    ],
)
def test_the_reply_tokens_lose_their_wrappers_whole_or_one_by_one(
    box: str, tokens: list[str]
) -> None:
    """Futurex-Eval's extractor takes "the content inside the braces"; the rule reads both a
    wrapped box and options wrapped one by one."""

    assert g.reply_tokens(box) == tokens


def test_options_wrapped_one_by_one_are_an_unordered_set_match() -> None:
    judge = _Judge(_ROUTE_SET)

    graded: g.Graded = _grade(judge, ["T1", "AG.AL"], "\\text{AG.AL}, \\text{T1}")

    assert judge.purposes == ["route"]
    assert graded.score == 1.0
