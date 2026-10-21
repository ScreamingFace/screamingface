"""A judge on a Fusion with quorum or optional members (OME-1289 E4a x OME-1557).

FEATURE: the judge call of a quorum Fusion reads the same broadcast panel as the combine call, and
its template has a panel form (``judge-template@1 returns=<r> input=panel``) that says so.
STORY: as a researcher, a quorum judge Fusion round-trips through url4 as the same ``sf.Judge``.
INVARIANT defended: a judge's template form must match what its call reads, so a hand-edited url4
cannot change which members the judge is told it sees.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.judge import JUDGE_PANEL_TEMPLATES, JUDGE_TEMPLATES
from screamingface.url4 import _calls

_MEMBERS = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]


def _url4(recipe: sf.Recipe, operators: Any = None) -> str:
    return compile_candidate(recipe, operators=operators or flow_operators()).url4


def _recover(url4: str) -> str:
    return sf.Url4(url4).to_python()


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


def test_a_quorum_judge_reads_the_panel_and_round_trips() -> None:
    judge = sf.Judge("provider/j", rubric=RUBRIC)
    fusion = sf.Fanout(_MEMBERS, quorum=2) >> judge >> sf.ArgMax("score:judge")
    url4 = _url4(fusion, flow_operators())
    root = build(url4)
    assert isinstance(root, Expression)
    judge_call = _calls(root)["judge_1"]

    assert judge_call.context == "{input: '$input', panel: '$panel_1'}"
    assert JUDGE_PANEL_TEMPLATES["scores"].splitlines()[0] == (
        "judge-template@2 returns=scores input=panel"
    )
    assert _url4(_recovered(url4), flow_operators()) == url4
    plain = _url4(
        sf.Fanout(["provider/a", "provider/b"]) >> judge >> sf.ArgMax("score:judge"),
        flow_operators(),
    )
    assert JUDGE_TEMPLATES["scores"].splitlines()[0] in plain
    assert "input=panel" not in plain


def test_a_panel_template_on_a_judge_that_reads_every_member_is_refused() -> None:
    judge = sf.JudgePick("provider/j", rubric=RUBRIC)
    url4 = _url4(sf.Fanout(["provider/a", "provider/b"]) >> judge, flow_operators())
    first, panel_first = (
        JUDGE_TEMPLATES["label"].split("\n", 1)[0],
        JUDGE_PANEL_TEMPLATES["label"].split("\n", 1)[0],
    )
    assert first in url4
    tampered = url4.replace(first, panel_first, 1)

    with pytest.raises(ValueError, match="unsupported judge call"):
        _recover(tampered)


def test_an_outputs_template_on_a_judge_that_reads_a_panel_is_refused() -> None:
    judge = sf.JudgePick("provider/j", rubric=RUBRIC)
    url4 = _url4(sf.Fanout(_MEMBERS, quorum=2) >> judge, flow_operators())
    panel_first = JUDGE_PANEL_TEMPLATES["label"].split("\n", 1)[0]
    assert panel_first in url4
    tampered = url4.replace(panel_first, JUDGE_TEMPLATES["label"].split("\n", 1)[0], 1)

    with pytest.raises(ValueError, match="unsupported judge call"):
        _recover(tampered)


def test_a_quorum_judge_recovers_as_the_same_judge() -> None:
    judge = sf.Judge("provider/j", rubric=RUBRIC)

    source = _recover(
        _url4(sf.Fanout(_MEMBERS, quorum=2) >> judge >> sf.ArgMax("score:judge"), flow_operators())
    )

    assert f">> sf.Judge('provider/j', rubric={RUBRIC!r})" in source
    assert "quorum=2" in source
