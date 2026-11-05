"""A paid check surface tells the caller the bill before the run starts (OME-829).

FEATURE: rubric benchmarks (DRACO, HealthBench) check drafts with a judge call.
STORY: as a user pointing a three-round panel at DRACO, I learn the check-call
ceiling at planning time — not from the invoice afterwards. Since OME-845 the
validator RETURNS the disclosure text and the display layer chooses the carrier
(evaluation panel, or the Python warning when no panel renders).
"""

from __future__ import annotations

from typing import Literal

import screamingface as sf
from screamingface._evaluation.benchmark import _BenchmarkResource, _CheckSurface
from screamingface._evaluation.runner import _validate_check_surface
from screamingface.discovery import BenchmarkInfo

_URL4 = "(answer:0.0:/candidate?q=(question)!'$candidate')!'$answer'"


def _resource(cost: Literal["free", "paid"], *, case_count: int = 100) -> _BenchmarkResource:
    return _BenchmarkResource(
        info=BenchmarkInfo(id="draco", revision="r1", case_count=case_count),
        case_count=case_count,
        url4=_URL4,
        check_surface=_CheckSurface(
            check_route="/benchmarks/draco/r1/check-surface/draco-pass.v1",
            feedback_intent="feedback",
            expected_check_cost=cost,
        ),
    )


def test_a_paid_surface_discloses_the_check_ceiling() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=3)
    message = _validate_check_surface((loop,), "draco", _resource("paid", case_count=100))
    assert message is not None
    assert "600 paid check calls" in message
    # 2 members x 3 rounds = 6 checks per case, x 100 cases.
    assert "6 per case" in message
    assert "may retry according to the benchmark's policy" in message


def test_the_ceiling_counts_one_member_for_a_solo_loop() -> None:
    solo = sf.SelfCorrective("prov/a", max_rounds=2)
    message = _validate_check_surface((solo,), "draco", _resource("paid", case_count=10))
    assert message is not None and "20 paid check calls" in message


def test_several_loops_bill_together() -> None:
    loops = (
        sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=2),
        sf.SelfCorrective("prov/c", max_rounds=2),
    )
    message = _validate_check_surface(loops, "draco", _resource("paid", case_count=5))
    # (2x2) + (1x2) = 6 checks per case, x 5 cases.
    assert message is not None and "30 paid check calls" in message


def test_a_free_surface_stays_silent() -> None:
    # INVARIANT: the disclosure is about MONEY, so a deterministic checker must never
    # produce one — a disclosure that cries wolf on IFEval gets ignored and then the
    # DRACO one goes unread too.
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    assert _validate_check_surface((loop,), "ifeval", _resource("free")) is None


def test_a_non_loop_candidate_is_never_billed_for_checks() -> None:
    fusion = sf.Fanout(["prov/a", "prov/b"]) >> sf.Synthesize("prov/s")
    assert _validate_check_surface((fusion,), "draco", _resource("paid")) is None
