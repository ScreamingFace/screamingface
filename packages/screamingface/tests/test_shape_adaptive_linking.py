"""The public Benchmark seam binds exactly one complete Candidate Recipe."""

from __future__ import annotations

import pytest
from url4 import build, render

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.linking import link_candidate


def _candidate_url4() -> str:
    return compile_candidate(
        sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize("provider/synth")
    ).url4


def test_whole_candidate_text_binding_links_one_complete_recipe() -> None:
    benchmark = "(answer:0.0:/candidate(question)!'$candidate')!'$answer'"

    linked = link_candidate(_candidate_url4(), benchmark)

    assert render(build(linked.url4)) == linked.url4
    assert linked.url4.count("candidate:0.0:") == 1
    assert "/provider/a" in linked.url4
    assert "/provider/b" in linked.url4
    assert "/provider/synth" in linked.url4
    assert "/candidate" in linked.url4


def test_whole_candidate_source_binding_is_detected() -> None:
    benchmark = "(answer:0.0:($candidate)!'go')!'$answer'"

    linked = link_candidate(_candidate_url4(), benchmark)

    assert render(build(linked.url4)) == linked.url4
    assert "$candidate" in linked.url4


@pytest.mark.parametrize(
    "reference",
    [
        "$candidate_member_1",
        "$candidate_members",
        "$candidate_synthesizer",
    ],
)
def test_structural_candidate_bindings_are_rejected(reference: str) -> None:
    benchmark = f"(answer:0.0:/candidate(question)!'{reference}')!'$answer'"

    with pytest.raises(sf.PlanningError, match="unsupported structural Candidate") as caught:
        link_candidate(_candidate_url4(), benchmark)

    assert caught.value.code == "candidate_shape_mismatch"


def test_mixed_whole_and_structural_bindings_are_rejected() -> None:
    benchmark = (
        "(answer:0.0:/candidate(question)!'$candidate', "
        "member:0.0:/candidate(question)!'$candidate_member_1')!'$answer'"
    )

    with pytest.raises(sf.PlanningError, match="unsupported structural Candidate") as caught:
        link_candidate(_candidate_url4(), benchmark)

    assert caught.value.code == "candidate_shape_mismatch"


def test_benchmark_without_candidate_binding_is_rejected() -> None:
    benchmark = "(answer:0.0:/fixed(question)!'answer')!'$answer'"

    with pytest.raises(sf.PlanningError, match="does not invoke the Candidate") as caught:
        link_candidate(_candidate_url4(), benchmark)

    assert caught.value.code == "invalid_benchmark_resource"


def test_similarly_named_plumbing_is_not_a_candidate_binding() -> None:
    benchmark = "(answer:0.0:/fixed(question)!'$candidate_result')!'$answer'"

    with pytest.raises(sf.PlanningError, match="does not invoke the Candidate") as caught:
        link_candidate(_candidate_url4(), benchmark)

    assert caught.value.code == "invalid_benchmark_resource"


def test_rendered_surface_guard_refuses_unbound_candidate_references() -> None:
    from screamingface._evaluation.linking import _require_candidate_references_bound

    # INVARIANT: every $candidate* reference in the SHIPPED artifact resolves to a
    # binding — checked on the rendered surface so it stays representation-independent
    # insurance against walker blindness, failing at plan time instead of after spend.
    _require_candidate_references_bound("(answer:0.0:/x(q)!'$candidate')!'$answer'")
    _require_candidate_references_bound("literal '$$candidate_member_1' stays escaped")

    with pytest.raises(sf.PlanningError, match="does not bind") as caught:
        _require_candidate_references_bound("(answer:0.0:/x(q)!'$candidate_member_1')!''")

    assert caught.value.code == "candidate_shape_mismatch"


def test_the_benchmark_expression_is_parsed_once_for_a_whole_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screamingface._evaluation import linking

    benchmark = "(answer:0.0:/candidate(question)!'$candidate')!'$answer'"
    candidate = _candidate_url4()
    expected = link_candidate(candidate, benchmark).url4

    calls = 0
    real = linking.build

    def counting(value: str) -> object:
        nonlocal calls
        calls += 1
        return real(value)

    monkeypatch.setattr(linking, "build", counting)

    # WHY: the benchmark is loop-invariant across an Evaluation's candidates, and
    # compiler-produced candidate text is already canonical — one parse total.
    prepared = linking._prepare_benchmark(benchmark)
    first = prepared.bind(candidate)
    second = prepared.bind(candidate)

    assert calls == 1
    assert first.url4 == expected
    assert second.url4 == expected
