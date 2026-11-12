"""A bare signal comparison in a condition is refused (E4c, owner decision 2026-11-12, round 2).

``sf.signal("lp") < 0.7`` is the per-member predicate of ``sf.Filter``. In ``sf.Gate(when=...)`` and
``sf.escalate_if(...)`` the author must write which number the condition reads: ``.chosen()`` (the
chosen member) or ``.mean()`` (the mean over the members). One expression keeps one meaning.
"""

from __future__ import annotations

import pytest

import screamingface as sf

SMALL = "openrouter/openai/gpt-4o-mini"
LARGE = "openrouter/openai/gpt-4.1"


@pytest.mark.parametrize(
    "condition",
    [
        sf.signal("lp") < 0.7,
        sf.signal("lp") <= 0.7,
        sf.signal("lp") > 0.7,
        sf.signal("lp") >= 0.7,
    ],
)
def test_gate_refuses_a_bare_signal(condition: object) -> None:
    with pytest.raises(TypeError, match=r"\.chosen\(\).*\.mean\(\)"):
        sf.Gate(when=condition, then=sf.Vote(), otherwise=LARGE)  # type: ignore[arg-type]


@pytest.mark.parametrize("condition", [sf.signal("lp") < 0.7, sf.signal("lp") >= 0.7])
def test_escalate_if_refuses_a_bare_signal(condition: object) -> None:
    with pytest.raises(TypeError, match=r"\.chosen\(\).*\.mean\(\)"):
        sf.escalate_if(condition)


def test_the_message_names_the_signal_and_the_filter_meaning() -> None:
    with pytest.raises(TypeError) as caught:
        sf.escalate_if(sf.signal("lp") < 0.7)
    message = str(caught.value)
    assert "sf.signal('lp').chosen() < 0.7" in message
    assert "sf.Filter" in message


def test_the_explicit_forms_still_work() -> None:
    panel = sf.Fanout([SMALL], signals={"lp": sf.Logprob("prob")})
    chosen = sf.Cascade(panel >> sf.Vote(), sf.escalate_if(sf.signal("lp").chosen() < 0.7), LARGE)
    mean = panel >> sf.Gate(when=sf.signal("lp").mean() >= 0.7, then=sf.Vote(), otherwise=LARGE)
    assert "chosen()" in repr(chosen)
    assert "mean()" in repr(mean)


def test_filter_keeps_the_bare_per_member_predicate() -> None:
    step = sf.Filter(where=sf.signal("lp") > 0.7)
    assert "signal('lp')" in repr(step)
