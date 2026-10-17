"""Review fixes of E4b part 3 (signal sources), review P3.

FEATURE: the engine enforces the declaration rules that only the SDK enforced before (contracts
C1, P14), and the member reader logs only the warnings that apply to the spec.
STORY: as a researcher, a hand-written or edited url4 spec gets the same refusals as one the SDK
compiled, and the log does not warn about a signal that no rule reads.
INVARIANT defended: every refusal is ``combine_spec_invalid`` and never echoes a declared name.
A separate module (append-only gate).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import pytest
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import REPLY_ENTROPY_MEAN, CombineError, MemberSources

_ASKED_TOP_5 = "logprobs=true&top_logprobs=5"


def _vote(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "extract": {"op": "last_line@1", "args": {}},
        "normalize": {"op": "text@1", "args": {}},
        "reduce": {"op": "mode@1", "args": {}},
        "select": {"op": "first_holder@1", "args": {}},
    }
    spec.update(overrides)
    return vote_spec(3, **spec)


def _sources(params: str = _ASKED_TOP_5) -> dict[str, Any]:
    """The context ``sources`` of three members: one call each, with ``params``."""
    return {
        f"member_{k}": {f"model_{k}": {"path": f"/openrouter/acme/m{k}", "params": params}}
        for k in range(1, 4)
    }


def _refusal(spec: dict[str, Any]) -> CombineError:
    context = context_text(["A", "A", "B"], sources=_sources())
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context, registry=BUILTIN_OPERATORS)
    return caught.value


# --- P3 #1: at most one entropy source (contracts C1) -------------------------------------------


def test_engine_accepts_one_entropy_source_next_to_a_logprob_source() -> None:
    """C1: one entropy source next to a logprob source is a valid declaration (the control)."""
    spec = _vote(
        signals={
            "unsure": {"source": "entropy", "top_logprobs": 5},
            "sure": {"source": "logprob", "form": "mean"},
        }
    )
    context = context_text(["A", "A", "B"], sources=_sources())
    outcome = run(spec_text(spec), context, registry=BUILTIN_OPERATORS)
    assert outcome.output == "A"


def test_engine_refuses_two_entropy_sources() -> None:
    """C1: a spec declares at most one ``entropy`` source; the message names no declared name."""
    spec = _vote(
        signals={
            "unsure_a": {"source": "entropy", "top_logprobs": 5},
            "unsure_b": {"source": "entropy", "top_logprobs": 5},
        }
    )
    error = _refusal(spec)
    assert error.code == "combine_spec_invalid"
    assert "entropy" in str(error)
    assert "unsure_a" not in str(error)
    assert "unsure_b" not in str(error)


def _entropy_reader(known: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
    """A member reader that knows a mean entropy of 0.5 for every member."""
    return {member: {REPLY_ENTROPY_MEAN: 0.5} for member in known}


def _entropy_values(params: str) -> list[float | None]:
    spec = _vote(signals={"unsure": {"source": "entropy", "top_logprobs": 5}})
    context = context_text(["A", "A", "B"], sources=_sources(params))
    outcome = run(spec_text(spec), context, registry=BUILTIN_OPERATORS, accounting=_entropy_reader)
    return [member.signals["unsure"] for member in outcome.evidence.members]


def test_entropy_value_is_kept_when_the_call_asked_for_the_declared_top_logprobs() -> None:
    """C1/C2: the member call asked for the declared k, so its entropy counts (the control)."""
    assert _entropy_values(_ASKED_TOP_5) == [0.5, 0.5, 0.5]


@pytest.mark.parametrize("params", ["logprobs=true&top_logprobs=3", "logprobs=true"])
def test_entropy_value_is_none_when_the_call_asked_for_another_top_logprobs(
    params: str, caplog: pytest.LogCaptureFixture
) -> None:
    """C1/C2: an entropy over another k (or none) is not the declared signal: None, and one
    count-only warning per step (the LC-E3 style)."""
    with caplog.at_level(logging.WARNING, logger="screamingface_engine.combine.endpoint"):
        assert _entropy_values(params) == [None, None, None]
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        "combine entropy: 3 member(s) asked for a top_logprobs other than the declared one"
    ]
