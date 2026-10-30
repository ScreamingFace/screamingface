"""Engine half of sf.Judge(..., order="min") (E4b unit 5, JO#1).

FEATURE: judge-order — the engine picks the lowest judge score with no engine change.
STORY: as a benchmark author, I want the member with the lowest judge score to answer, so that a
rubric such as an error count can pick the answer.
INVARIANT: best_holder@1 {"order":"min"} after scores@1 picks the lowest score; the tie rule is
pinned in test_sdk_judge_order_contracts.py.
"""

from combine_flow_support import judge_spec
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS


def test_engine_scores_then_best_holder_min_picks_the_lowest_member() -> None:
    # CHAR: passes today. The engine half of order="min" already exists.
    spec = judge_spec(3, "scores", select_op="best_holder@1", select_args={"order": "min"})
    reply = '{"member_1": 3, "member_2": 0, "member_3": 1}'

    outcome = run(
        spec_text(spec),
        context_text(["alpha", "beta", "gamma"], {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )

    # oracle by hand: min(3, 0, 1) = 0, held only by member_2 -> "beta", no tie
    assert outcome.output == "beta"
    assert outcome.evidence.reducer == "judge"
    assert outcome.evidence.chosen == ["member_2"]
    assert outcome.evidence.tie is False
    assert outcome.evidence.judge is not None
    assert outcome.evidence.judge.returns == "scores"
    assert outcome.evidence.judge.parsed == {"member_1": 3.0, "member_2": 0.0, "member_3": 1.0}
    assert [member.score for member in outcome.evidence.members] == [3.0, 0.0, 1.0]
