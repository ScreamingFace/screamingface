"""The Budget state the SDK decodes is the Budget state the Engine writes (OME-1289 E4a, unit 12).

FEATURE: ``data/combine_contract/budget_cases.json`` holds the JSON of six ``BudgetState`` values
built by the real records and charge rule: three usd calls, a cache hit, a token budget, an unpriced
call, an overrun and a refusal.
STORY: as a maintainer, I change a Budget record on one side and a test on the other side fails,
instead of the SDK mirror (``screamingface.budget``) drifting from the Engine silently.
INVARIANT defended: this is a CONTRACT FIXTURE, not an oracle. The scenario inputs are written by
hand; the expected state is whatever the Engine produces today, and the file pins it. The SDK twin
(``packages/screamingface/tests/test_budget_contract.py``) only READS the file. A deliberate change
is made by running this file as a script (``write_fixture()``) and reviewing the JSON diff.
A missing fixture file FAILS here; it is never skipped.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_signal_accounting import _cache, _hit

from screamingface_engine.budget import Budget, BudgetRefusal, BudgetState
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.world.accounting import signal_accounting_from_aigw

FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "budget_cases.json"


def _usd(state: BudgetState, *amounts: float | None, cached: bool = False) -> BudgetState:
    for amount in amounts:
        state = state.apply(
            operation_id=f"op_model_{len(state.charges) + 1}",
            member_id=f"member_{len(state.charges) + 1}",
            stage="model",
            signals=SignalAccounting(cost_usd=amount),
            cached=cached,
        )
    return state


def _start(unit: Any, cap: float) -> BudgetState:
    return BudgetState.start(Budget(unit=unit, cap=cap))


def _usd_three_calls() -> BudgetState:
    return _usd(_start("usd", 0.01), 0.002, 0.003, 0.001)


def _usd_cache_hit() -> BudgetState:
    first = _usd(_start("usd", 0.01), 0.002)
    return first.apply(
        operation_id="op_model_2",
        member_id="member_2",
        stage="model",
        signals=signal_accounting_from_aigw(_hit(), _cache("hit")),
        cached=True,
    )


def _tokens() -> BudgetState:
    state = _start("tokens", 1000.0)
    for stage, tokens in (("model", (120.0, 30.0)), ("judge", (200.0, 45.0))):
        state = state.apply(
            operation_id=f"op_{stage}_1",
            member_id=None,
            stage=stage,  # type: ignore[arg-type]
            signals=SignalAccounting(tokens_in=tokens[0], tokens_out=tokens[1]),
            cached=False,
        )
    return state


def _unpriced() -> BudgetState:
    return _usd(_start("usd", 0.01), 0.002, None)


def _overrun() -> BudgetState:
    return _usd(_start("usd", 0.005), 0.004, 0.003)


def _refused() -> BudgetState:
    state = _usd(_start("usd", 0.01), 0.009)
    refusal = BudgetRefusal(
        operation_id="op_model_2",
        member_id="member_2",
        stage="model",
        estimated=0.02,
        reason="would_exceed_cap",
    )
    return BudgetState(**{**state.__dict__, "refused": [refusal]})


SCENARIOS: dict[str, Callable[[], BudgetState]] = {
    "usd_three_calls": _usd_three_calls,
    "usd_cache_hit": _usd_cache_hit,
    "tokens": _tokens,
    "unpriced": _unpriced,
    "overrun": _overrun,
    "refused": _refused,
}


def canonical_state(state: BudgetState) -> str:
    """The bytes the fixture holds for one state (same encoder, same options)."""
    return json.dumps(state.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def write_fixture() -> None:
    """Regenerate ``budget_cases.json`` from the real records (run this file as a script)."""
    cases = {name: json.loads(canonical_state(build())) for name, build in SCENARIOS.items()}
    FIXTURE.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture() -> dict[str, Any]:
    assert FIXTURE.is_file(), f"missing contract fixture {FIXTURE}; run write_fixture()"
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_engine_state_is_the_fixture_byte_for_byte(name: str) -> None:
    pinned = _fixture()[name]

    assert canonical_state(SCENARIOS[name]()) == json.dumps(
        pinned, ensure_ascii=False, separators=(",", ":")
    )


def test_the_fixture_holds_exactly_the_scenarios() -> None:
    assert sorted(_fixture()) == sorted(SCENARIOS)


if __name__ == "__main__":
    write_fixture()
