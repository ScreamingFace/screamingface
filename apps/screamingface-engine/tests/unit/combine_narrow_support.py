"""Specs and contexts of the narrow-step scenarios (E4b map-reduce surface, unit 1). Test-only.

Each builder returns a spec over the built-in operators with the optional ``narrow`` key (narrow.md
§2): one or more narrow steps (``filter@1`` + ``kept@1``, ``by_signal@1`` + ``top_k@1``,
``scores@1`` judge + ``top_k@1``) before the main step. The member texts are small JSON objects or
short lines. Every expected value in the tests is computed by hand from these texts, never copied
from the code's output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from combine_support import run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome


def step(op: str, **args: Any) -> dict[str, Any]:
    return {"op": op, "args": dict(args)}


def narrow_item(
    reduce: Mapping[str, Any],
    select: Mapping[str, Any],
    *,
    extract: Mapping[str, Any] | None = None,
    normalize: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One narrow step with all four keys, as the SDK writes it (narrow.md §2)."""
    return {
        "extract": None if extract is None else dict(extract),
        "normalize": None if normalize is None else dict(normalize),
        "reduce": dict(reduce),
        "select": dict(select),
    }


def keep_where(key: str, cmp: str, value: float) -> dict[str, Any]:
    """``sf.Filter(where=sf.signal(key) <cmp> value)``: filter@1 threshold + kept@1."""
    return narrow_item(step("filter@1", key=key, cmp=cmp, value=value), step("kept@1"))


def keep_matching(pattern: str, *, extract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``sf.Filter(where=sf.matches(pattern))``: filter@1 pattern + kept@1."""
    return narrow_item(step("filter@1", pattern=pattern), step("kept@1"), extract=extract)


def top_by(key: str, k: int, order: str = "max") -> dict[str, Any]:
    """``sf.Rank(k, by=key)``: by_signal@1 + top_k@1."""
    return narrow_item(step("by_signal@1", key=key, order=order), step("top_k@1", k=k, order=order))


def top_by_judge(k: int) -> dict[str, Any]:
    """``sf.Rank(k, by="score:judge")``: scores@1 (source judge) + top_k@1."""
    return narrow_item(step("scores@1", source="judge"), step("top_k@1", k=k))


def _members(count: int) -> list[str]:
    return [f"member_{index}" for index in range(1, count + 1)]


def base_spec(count: int, **keys: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "schema": "screamingface.combine-spec.v1",
        "members": _members(count),
        "weights": None,
    }
    spec.update(keys)
    return spec


def mean_spec(count: int, narrow: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """``... >> sf.Mean(over="field:answer")``: json_field answer, numeric, mean@1, value@1."""
    spec = base_spec(
        count,
        reducer="mean",
        extract=step("json_field@1", path="answer"),
        normalize=step("numeric@1"),
        reduce=step("mean@1"),
        select=step("value@1"),
    )
    if narrow is not None:
        spec["narrow"] = [dict(item) for item in narrow]
    return spec


def vote_spec(
    count: int,
    narrow: Sequence[Mapping[str, Any]] | None,
    *,
    extract: Mapping[str, Any] | None = None,
    **keys: Any,
) -> dict[str, Any]:
    """``... >> sf.Vote(...)``: extract (``field:answer`` by default), text@1, mode@1,
    first_holder@1; ``keys`` replace any spec key (weights, reduce, select, gate, signals)."""
    spec = base_spec(
        count,
        reducer="vote",
        extract=step("json_field@1", path="answer") if extract is None else dict(extract),
        normalize=step("text@1"),
        reduce=step("mode@1"),
        select=step("first_holder@1"),
    )
    spec.update(keys)
    if narrow is not None:
        spec["narrow"] = [dict(item) for item in narrow]
    return spec


def rank_spec(
    count: int, narrow: Sequence[Mapping[str, Any]] | None, *, key: str, k: int
) -> dict[str, Any]:
    """``... >> sf.Rank(k, by=key) >> writer``: the main step hands on the selection envelope."""
    spec = base_spec(
        count,
        reducer="rank",
        extract=None,
        normalize=None,
        reduce=step("by_signal@1", key=key, order="max"),
        select=step("top_k@1", k=k, order="max"),
    )
    if narrow is not None:
        spec["narrow"] = [dict(item) for item in narrow]
    return spec


def argmax_judge_spec(count: int, narrow: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """``... >> sf.ArgMax("score:judge")``: scores@1 (judge) + max_score@1 (reducer judge)."""
    spec = base_spec(
        count,
        reducer="judge",
        extract=None,
        normalize=None,
        reduce=step("scores@1", source="judge"),
        select=step("max_score@1"),
    )
    if narrow is not None:
        spec["narrow"] = [dict(item) for item in narrow]
    return spec


def json_text(**fields: Any) -> str:
    return json.dumps(fields, separators=(",", ":"))


def context(
    outputs: Sequence[str],
    *,
    judge: Mapping[str, float] | None = None,
    panel: Mapping[int, str] | None = None,
) -> str:
    """A combine context: ``outputs`` member_1.., or a quorum ``panel``; ``judge`` scores."""
    body: dict[str, Any] = {"input": "q"}
    if panel is None:
        body["outputs"] = {f"member_{k}": text for k, text in enumerate(outputs, start=1)}
    else:
        body["panel"] = json.dumps(
            [
                {"source_position": k, "source_name": f"member_{k}", "result": text}
                for k, text in panel.items()
            ]
        )
    if judge is not None:
        body["signals"] = {"judge": json.dumps(dict(judge))}
    return json.dumps(body)


def outcome(spec: Mapping[str, Any], context_text: str) -> CombineOutcome:
    """Run the pure combine core with the built-in operators."""
    return run(spec_text(spec), context_text, registry=BUILTIN_OPERATORS)


def wire(result: CombineOutcome) -> dict[str, Any]:
    """The evidence as the envelope writes it (by alias, absent keys left out)."""
    return result.evidence.model_dump(mode="json", by_alias=True)


def rows(result: CombineOutcome) -> list[tuple[str, str | None]]:
    """``(status, reason)`` of each member record, in author order."""
    return [(row.status, row.reason) for row in result.evidence.members]


# --- the scenarios of narrow.md §7 (each one a hand-checked case) --------------------------------

# Filter then mean (NR-4): confidence > 0.7 keeps member_1 and member_3; member_4 has no confidence.
FILTER_MEAN_OUTPUTS = [
    json_text(answer=10, confidence=0.9),
    json_text(answer=100, confidence=0.2),
    json_text(answer=20, confidence=0.8),
    json_text(answer=7),
]


def filter_mean() -> CombineOutcome:
    spec = mean_spec(4, [keep_where("field:confidence", "gt", 0.7)])
    return outcome(spec, context(FILTER_MEAN_OUTPUTS))


# Rank then vote (NR-5): all five vote B 3-2, the top two by confidence vote A 2-0.
RANK_VOTE_OUTPUTS = [
    json_text(answer="A", confidence=0.9),
    json_text(answer="A", confidence=0.8),
    json_text(answer="B", confidence=0.1),
    json_text(answer="B", confidence=0.2),
    json_text(answer="B", confidence=0.3),
]


def rank_vote() -> CombineOutcome:
    return outcome(vote_spec(5, [top_by("field:confidence", 2)]), context(RANK_VOTE_OUTPUTS))


# Filter then rank then the envelope (NR-6): confidence >= 0.5 drops member_2 (score 9), and the
# main top 2 by score among the rest is member_3 (5) then member_4 (3).
FILTER_RANK_OUTPUTS = [
    json_text(confidence=0.9, score=1),
    json_text(confidence=0.4, score=9),
    json_text(confidence=0.6, score=5),
    json_text(confidence=0.7, score=3),
]


def filter_rank_envelope() -> CombineOutcome:
    spec = rank_spec(4, [keep_where("field:confidence", "ge", 0.5)], key="field:score", k=2)
    return outcome(spec, context(FILTER_RANK_OUTPUTS))


AGREEMENT_GATE: dict[str, Any] = {
    "observe": "agreement",
    "cmp": ">=",
    "threshold": 0.5,
    "otherwise": "abstain",
}


def narrow_no_votes() -> CombineOutcome:
    """A narrow abstain (NR-7): no member has a confidence above 0.95; the gate does not run."""
    spec = vote_spec(5, [keep_where("field:confidence", "gt", 0.95)], gate=AGREEMENT_GATE)
    return outcome(spec, context(RANK_VOTE_OUTPUTS))


def narrow_cut_not_met() -> CombineOutcome:
    """A narrow abstain (NR-7): the filter keeps two members, the top 3 needs three. The third
    narrow step never runs, so it has no record."""
    spec = vote_spec(
        5,
        [
            keep_where("field:confidence", "gt", 0.5),
            top_by("field:confidence", 3),
            keep_where("field:confidence", "lt", 1.0),
        ],
    )
    return outcome(spec, context(RANK_VOTE_OUTPUTS))


# A narrow no_signal (NR-8): member_2 has no score (left out at step 1), member_3 has no
# confidence (left out at step 2); member_4 is the third by confidence (not selected).
NO_SIGNAL_OUTPUTS = [
    json_text(answer="A", confidence=0.9, score=1),
    json_text(answer="B", confidence=0.8),
    json_text(answer="A", score=2),
    json_text(answer="B", confidence=0.3, score=3),
    json_text(answer="A", confidence=0.5, score=4),
]


def narrow_no_signal() -> CombineOutcome:
    spec = vote_spec(5, [keep_where("field:score", "ge", 0), top_by("field:confidence", 2)])
    return outcome(spec, context(NO_SIGNAL_OUTPUTS))


# A judge read by a narrow rank and by the main vote weights (NR-9). Weighted by the judge, all
# four give C (8 + 7 = 15); the top two by the judge are member_2 (B, 9) and member_3 (C, 8).
JUDGE_VOTE_OUTPUTS = ["A", "B", "C", "C"]
JUDGE_VOTE_SCORES = {"member_1": 2, "member_2": 9, "member_3": 8, "member_4": 7}


def judge_rank_weighted_vote() -> CombineOutcome:
    spec = vote_spec(
        4,
        [top_by_judge(2)],
        extract=step("last_line@1"),
        reduce=step("weighted_mode@1"),
        weights={"signal": "score:judge"},
    )
    return outcome(spec, context(JUDGE_VOTE_OUTPUTS, judge=JUDGE_VOTE_SCORES))


# The judged set (NR-10b): the judge scores all four members; the filter drops member_2, the
# judge's best. A judge rank or a judge pick after the filter reads the other three only.
JUDGED_OUTPUTS = [
    json_text(answer="A", confidence=0.9),
    json_text(answer="B", confidence=0.1),
    json_text(answer="C", confidence=0.8),
    json_text(answer="D", confidence=0.7),
]
JUDGED_SCORES = {"member_1": 5, "member_2": 10, "member_3": 6, "member_4": 1}


def judge_rank_after_filter() -> CombineOutcome:
    spec = vote_spec(4, [keep_where("field:confidence", "gt", 0.5), top_by_judge(1)])
    return outcome(spec, context(JUDGED_OUTPUTS, judge=JUDGED_SCORES))


def judge_argmax_after_filter() -> CombineOutcome:
    spec = argmax_judge_spec(4, [keep_where("field:confidence", "gt", 0.5)])
    return outcome(spec, context(JUDGED_OUTPUTS, judge=JUDGED_SCORES))


# An abstain-fallback gate after a narrow step (NR-10): the mean of conf over all four is 0.5
# (below 0.6); over the two that pass the filter it is (0.75 + 0.875) / 2 = 0.8125.
GATE_OUTPUTS = ["conf 0.75\nA", "conf 0.125\nB", "conf 0.875\nA", "conf 0.25\nB"]
CONF_SIGNAL: dict[str, Any] = {"conf": {"source": "verbalized", "pattern": "conf ([0-9.]+)"}}
MEAN_GATE: dict[str, Any] = {
    "observe": "mean:conf",
    "cmp": ">=",
    "threshold": 0.6,
    "otherwise": "abstain",
}


def gate_after_narrow() -> CombineOutcome:
    spec = vote_spec(
        4,
        [keep_where("conf", "gt", 0.5)],
        extract=step("last_line@1"),
        signals=CONF_SIGNAL,
        gate=MEAN_GATE,
    )
    return outcome(spec, context(GATE_OUTPUTS))


__all__ = [
    "AGREEMENT_GATE",
    "CONF_SIGNAL",
    "FILTER_MEAN_OUTPUTS",
    "FILTER_RANK_OUTPUTS",
    "GATE_OUTPUTS",
    "JUDGED_OUTPUTS",
    "JUDGED_SCORES",
    "JUDGE_VOTE_OUTPUTS",
    "JUDGE_VOTE_SCORES",
    "MEAN_GATE",
    "NO_SIGNAL_OUTPUTS",
    "RANK_VOTE_OUTPUTS",
    "argmax_judge_spec",
    "base_spec",
    "context",
    "filter_mean",
    "filter_rank_envelope",
    "gate_after_narrow",
    "json_text",
    "judge_argmax_after_filter",
    "judge_rank_after_filter",
    "judge_rank_weighted_vote",
    "keep_matching",
    "keep_where",
    "mean_spec",
    "narrow_cut_not_met",
    "narrow_item",
    "narrow_no_signal",
    "narrow_no_votes",
    "outcome",
    "rank_spec",
    "rank_vote",
    "rows",
    "step",
    "top_by",
    "top_by_judge",
    "vote_spec",
    "wire",
]
