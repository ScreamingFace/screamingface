"""Corrective-loop compilation — one whole `$candidate`, manifest routes only.

FEATURE: benchmark-independent corrective loop (OME-796 / OME-828).
STORY: as the transport contract's client half, the compiled loop references
the manifest's check route and the versioned generic ensemble routes — and
binds into a benchmark as ONE ordinary `$candidate`, exactly like a Fusion.
"""

from __future__ import annotations

import json

import pytest
from url4 import Expression, build, render

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.corrective import (
    ANSWER_ROUTE,
    CORRECTIVE_FLOW,
    CORRECTIVE_PROTOCOL_REVISION,
    GATE_ROUTE,
    JUDGE_FEEDBACK_INSTRUCTION,
    MEMBER_ROUTE,
    RESULT_ROUTE,
    RETRY_INSTRUCTION,
    ROLE_ROUTE,
    SELECT_ROUTE,
    SELF_FEEDBACK_INSTRUCTION,
    TIE_BREAK_INSTRUCTION,
)
from screamingface._evaluation.topology import _topology_from_expression
from screamingface.errors import PlanningError

_CHECK_ROUTE = "/benchmarks/ifeval/abc123/check-surface"
_SURFACE = _CheckSurface(
    check_route=_CHECK_ROUTE,
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _loop(max_rounds: int = 3) -> sf.CorrectiveLoop:
    return sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=max_rounds)


def test_the_loop_compiles_to_one_canonical_expression() -> None:
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    assert compiled.kind == "corrective_loop"
    # INVARIANT (transport contract): the compiled url4 is canonical — what we
    # render is byte-identical to what re-rendering the parsed tree produces.
    assert render(build(compiled.url4)) == compiled.url4


def test_check_calls_use_the_manifest_route_never_a_hardcoded_path() -> None:
    surface = _CheckSurface(
        check_route="/benchmarks/other/zzz999/check-surface",
        feedback_intent="feedback",
        expected_check_cost="free",
    )
    compiled = compile_candidate(_loop(), check_surface=surface)
    # 2 members x 3 rounds = 6 mid-run check CALLS, all against the advertised
    # route (the 7th mention is the topology rider's check_route identity field).
    assert compiled.url4.count("/benchmarks/other/zzz999/check-surface(") == 6
    assert compiled.url4.count("/benchmarks/other/zzz999/check-surface") == 7
    assert "ifeval" not in compiled.url4


def test_the_generic_ensemble_routes_are_versioned_wire_constants() -> None:
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    url4 = compiled.url4
    # Per round: 1 tie gate + 1 continue gate (none after the last round).
    assert url4.count(f"{GATE_ROUTE}(") == 5
    assert url4.count(f"{SELECT_ROUTE}(") == 3
    # The collapse chain: one answer call per non-final round.
    assert url4.count(f"{ANSWER_ROUTE}(") == 2
    assert url4.count(f"{MEMBER_ROUTE}(") == 6
    assert url4.count(f"{ROLE_ROUTE}(") == 5
    assert url4.count(f"{RESULT_ROUTE}(") == 1
    assert "/ensemble/corrective/v1/" in url4


def test_nested_recipe_input_is_reserved_for_the_invocation_scope() -> None:
    compiled = compile_candidate(_loop(max_rounds=2), check_surface=_SURFACE)
    # Enclosing scopes do not own this reserved name. MEMBER_ROUTE/ROLE_ROUTE
    # bind it to the invocation's current-round context before executing the
    # nested Recipe.
    assert "/prov/a($_sf_recipe_input)" in compiled.url4
    assert "/prov/b($_sf_recipe_input)" in compiled.url4
    assert "/prov/j($_sf_recipe_input)" in compiled.url4


def test_round_budget_is_written_into_every_gate_intent() -> None:
    compiled = compile_candidate(_loop(max_rounds=2), check_surface=_SURFACE)
    assert "continue:1:2" in compiled.url4
    assert "tie:1:2" in compiled.url4
    assert "tie:2:2" in compiled.url4
    # The final round buys no continuation — bounded retries are structural.
    assert "continue:2:2" not in compiled.url4


def test_member_and_judge_prompts_carry_the_protocol_prose() -> None:
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    assert RETRY_INSTRUCTION in compiled.url4
    assert JUDGE_FEEDBACK_INSTRUCTION in compiled.url4
    assert TIE_BREAK_INSTRUCTION in compiled.url4
    assert SELF_FEEDBACK_INSTRUCTION not in compiled.url4


def test_client_owned_protocol_prose_stays_safe_and_revisioned() -> None:
    for prose in (
        RETRY_INSTRUCTION,
        SELF_FEEDBACK_INSTRUCTION,
        JUDGE_FEEDBACK_INSTRUCTION,
        TIE_BREAK_INSTRUCTION,
    ):
        assert "'" not in prose
        assert "," not in prose
    assert "STOPS" in CORRECTIVE_FLOW
    assert "verbatim" in CORRECTIVE_FLOW


def test_solo_compiles_self_coaching_instead_of_a_judge() -> None:
    compiled = compile_candidate(sf.SelfCorrective("prov/a"), check_surface=_SURFACE)
    assert compiled.kind == "self_corrective"
    assert SELF_FEEDBACK_INSTRUCTION in compiled.url4
    assert JUDGE_FEEDBACK_INSTRUCTION not in compiled.url4
    assert TIE_BREAK_INSTRUCTION not in compiled.url4
    assert render(build(compiled.url4)) == compiled.url4


def test_a_single_round_loop_has_no_continuation_machinery() -> None:
    compiled = compile_candidate(_loop(max_rounds=1), check_surface=_SURFACE)
    assert "continue:" not in compiled.url4
    assert f"{ANSWER_ROUTE}(" not in compiled.url4
    assert compiled.url4.count(f"{SELECT_ROUTE}(") == 1


def test_models_cover_members_and_judge() -> None:
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    assert compiled.models == ("prov/a", "prov/b", "prov/j")


def test_member_projections_describe_the_round_one_panel() -> None:
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    assert [member.name for member in compiled.members] == ["a", "b"]


def test_member_labels_extend_beyond_the_retired_lanl_ceiling() -> None:
    compiled = compile_candidate(
        sf.CorrectiveLoop(
            ["prov/a", "prov/b", "prov/c", "prov/d", "prov/e"],
            judge="prov/j",
            max_rounds=1,
        ),
        check_surface=_SURFACE,
    )

    assert "loop_member_1_e" in compiled.url4
    assert "loop_check_1_e" in compiled.url4
    assert compiled.url4.count(f"{MEMBER_ROUTE}(") == 5


def test_member_labels_remain_unique_after_z() -> None:
    compiled = compile_candidate(
        sf.CorrectiveLoop(
            [f"prov/member-{index}" for index in range(27)],
            judge="prov/j",
            max_rounds=1,
        ),
        check_surface=_SURFACE,
    )

    assert "loop_member_1_z" in compiled.url4
    assert "loop_member_1_aa" in compiled.url4
    assert compiled.url4.count(f"{MEMBER_ROUTE}(") == 27


def test_compiling_without_a_check_surface_fails_before_rendering() -> None:
    with pytest.raises(PlanningError, match="mid-run checking") as caught:
        compile_candidate(_loop(), check_surface=None)
    assert caught.value.code == "check_surface_missing"
    assert caught.value.permanent is True


def test_the_topology_rider_carries_the_loop_identity() -> None:
    # INVARIANT (leaderboard identity): a client-compiled loop has no
    # separate Benchmark identity or revision — the topology rider IS how a run record
    # self-identifies: kind, members, judge, cost cap, the check route
    # compiled against (carrying the benchmark revision), and the loop
    # protocol revision.
    compiled = compile_candidate(_loop(), check_surface=_SURFACE)
    expression = build(compiled.url4)
    assert isinstance(expression, Expression)
    topology = _topology_from_expression(expression)
    assert topology.kind == "corrective_loop"
    assert topology.max_rounds == 3
    assert topology.check_route == _CHECK_ROUTE
    assert topology.protocol == CORRECTIVE_PROTOCOL_REVISION
    assert [member.name for member in topology.members] == ["a", "b"]
    assert topology.judge is not None
    assert topology.judge.name == "j"


def test_the_topology_rider_round_trips_through_encode_and_decode() -> None:
    for recipe in (_loop(), sf.SelfCorrective("prov/a", max_rounds=2)):
        compiled = compile_candidate(recipe, check_surface=_SURFACE)
        expression = build(compiled.url4)
        assert isinstance(expression, Expression)
        topology = _topology_from_expression(expression)
        from screamingface._evaluation.topology import _encode_topology

        encoded = _encode_topology(topology)
        assert json.loads(encoded)["schema"] == "screamingface.recipe.v1"


def test_the_check_context_threads_input_and_draft() -> None:
    compiled = compile_candidate(_loop(max_rounds=1), check_surface=_SURFACE)
    assert "{input: '$input', invocation: '$loop_member_1_a'}" in compiled.url4
    assert "{input: '$input', invocation: '$loop_member_1_b'}" in compiled.url4


def test_retry_prompts_thread_own_previous_answer_and_coaching() -> None:
    compiled = compile_candidate(_loop(max_rounds=2), check_surface=_SURFACE)
    # Each member retries ITS OWN draft, not a teammate's.
    assert "$loop_check_1_a.answer" in compiled.url4
    assert "$loop_check_1_b.answer" in compiled.url4


def test_coach_verdicts_carry_only_answer_and_feedback_per_member() -> None:
    # INVARIANT (OME-1168 — replayability + role isolation): the coach prompt is
    # a pure function of case input + member answer/feedback texts. The round's
    # Candidate Invocation envelopes (accounting/usage token counts, provider and
    # model identity) must never render into a judge-role body — live token
    # counts differ from replay's cache-hit zeros, so an envelope in the prompt
    # makes a recorded run unreplayable.
    compiled = compile_candidate(_loop(max_rounds=2), check_surface=_SURFACE)
    assert (
        "verdicts: {a: {answer: '$loop_check_1_a.answer', "
        "feedback: '$loop_check_1_a.feedback'}, "
        "b: {answer: '$loop_check_1_b.answer', "
        "feedback: '$loop_check_1_b.feedback'}}"
    ) in compiled.url4
    assert "verdicts: '$loop_round_1'" not in compiled.url4


def test_the_round_object_still_feeds_gate_and_select_verbatim() -> None:
    # INVARIANT: the verbatim-selection path is untouched — tie gate, continue
    # gate, and select still consume the FULL round object (whose records carry
    # the envelope the SELECT endpoint returns verbatim). Exactly those three
    # consumers reference round 1; the coach is no longer one of them.
    compiled = compile_candidate(_loop(max_rounds=2), check_surface=_SURFACE)
    assert compiled.url4.count("$loop_round_1") == 3


def test_protocol_revision_moved_with_the_coach_verdict_shape() -> None:
    # WHY pin the retired hash: the revision must move whenever the Client-
    # rendered prompt shape changes; OME-1168 reshaped the coach verdicts, so
    # the pre-change revision is retired for good.
    assert CORRECTIVE_PROTOCOL_REVISION != "284c47e50ca0ba4f"
