"""Check-surface decode + fail-before-spend preflight (OME-796 / OME-828).

FEATURE: `check_surface` in `screamingface.benchmark.v1` — the one manifest
block that makes a benchmark loop-capable.
STORY: as a user pointing a CorrectiveLoop at an MCQ-style benchmark, I get a
PlanningError right after the free benchmark fetch — before any compile, model
preflight, or paid call. That refusal is designed behavior (pass/fail feedback
over a handful of options is an elimination attack), not a gap.
"""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.benchmark import (
    _BenchmarkResource,
    _CheckSurface,
    _decode_benchmark_resource,
)
from screamingface._evaluation.runner import _evaluation_inputs, _validate_check_surface
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import PlanningError

_CHECK_BLOCK = {
    "check_route": "/benchmarks/ifeval/abc123/check-surface",
    "feedback_intent": "feedback",
    "expected_check_cost": "free",
}


def _resource_payload(check_surface: object = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "screamingface.benchmark.v1",
        "id": "ifeval",
        "title": "IFEval",
        "description": "the benchmark",
        "revision": "abc123",
        "case_count": 541,
        "url4": "(answer:0.0:/candidate?q=(question)!'$candidate')!'$answer'",
    }
    if check_surface is not None:
        payload["check_surface"] = check_surface
    return payload


def _decode(payload: dict[str, object]) -> _BenchmarkResource:
    return _decode_benchmark_resource(payload, requested_id="ifeval", requested_limit=None)


# --- manifest decode --------------------------------------------------------------


def test_an_absent_block_decodes_to_no_surface() -> None:
    resource = _decode(_resource_payload())
    assert resource.check_surface is None


def test_the_block_decodes_into_a_typed_surface() -> None:
    resource = _decode(_resource_payload(dict(_CHECK_BLOCK)))
    surface = resource.check_surface
    assert surface == _CheckSurface(
        check_route="/benchmarks/ifeval/abc123/check-surface",
        feedback_intent="feedback",
        expected_check_cost="free",
    )


def test_a_block_with_extra_keys_is_rejected() -> None:
    with pytest.raises(PlanningError, match="check_surface"):
        _decode(_resource_payload({**_CHECK_BLOCK, "surprise": True}))


def test_a_relative_check_route_is_rejected() -> None:
    with pytest.raises(PlanningError, match="absolute route"):
        _decode(_resource_payload({**_CHECK_BLOCK, "check_route": "check-surface"}))


def test_an_unknown_check_cost_is_rejected() -> None:
    with pytest.raises(PlanningError, match="'free' or 'paid'"):
        _decode(_resource_payload({**_CHECK_BLOCK, "expected_check_cost": "cheap"}))


# --- fail-before-spend preflight --------------------------------------------------


def _bare_resource(check_surface: _CheckSurface | None) -> _BenchmarkResource:
    return _BenchmarkResource(
        info=BenchmarkInfo(id="quizbench", revision="r1", case_count=10),
        case_count=10,
        url4="(answer:0.0:/candidate?q=(question)!'$candidate')!'$answer'",
        check_surface=check_surface,
    )


def test_a_loop_on_a_checkless_benchmark_is_refused_by_name() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    with pytest.raises(PlanningError, match="mid-run checking") as caught:
        _validate_check_surface((loop,), "quizbench", _bare_resource(None))
    assert caught.value.code == "check_surface_missing"
    assert caught.value.permanent is True
    details = caught.value.details
    assert isinstance(details, dict)
    assert details["benchmark"] == "quizbench"
    assert details["candidates"] == ["a+b"]


def test_self_corrective_is_held_to_the_same_gate() -> None:
    solo = sf.SelfCorrective("prov/a")
    with pytest.raises(PlanningError, match="mid-run checking"):
        _validate_check_surface((solo,), "quizbench", _bare_resource(None))


def test_non_loop_recipes_never_need_a_check_surface() -> None:
    fusion = sx.Fanout(["prov/a", "prov/b"]) >> sx.Synthesize("prov/s")
    _validate_check_surface((fusion, sf.Model("prov/a")), "quizbench", _bare_resource(None))


def test_a_loop_with_an_advertised_surface_passes_preflight() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    surface = _CheckSurface(
        check_route="/benchmarks/quizbench/r1/check-surface",
        feedback_intent="feedback",
        expected_check_cost="free",
    )
    _validate_check_surface((loop,), "quizbench", _bare_resource(surface))


def test_a_paid_surface_warns_with_the_maximum_check_call_count() -> None:
    loop = sf.CorrectiveLoop(
        ["prov/a", "prov/b", "prov/c"],
        judge="prov/j",
        max_rounds=2,
    )
    surface = _CheckSurface(
        check_route="/benchmarks/quizbench/r1/check-surface",
        feedback_intent="feedback",
        expected_check_cost="paid",
    )

    message = _validate_check_surface((loop,), "quizbench", _bare_resource(surface))
    assert message is not None and "60 paid check calls" in message


def test_corrective_recipes_are_public_evaluation_inputs() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    solo = sf.SelfCorrective("prov/a")

    assert _evaluation_inputs(loop, "ifeval", 1) == (loop,)
    assert _evaluation_inputs([loop, solo], "ifeval", 1) == (loop, solo)
