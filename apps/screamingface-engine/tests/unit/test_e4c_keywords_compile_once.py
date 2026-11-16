"""KEYWORDS compiles each rule once per intent and reads the input head once (E4c, OME-1291).

FEATURE: OME-1291 selectors SL-1 - SL-4 after the code review.
STORY: as an operator, a Keywords selector with many rules costs one RE2 compile per rule for the
whole run, not two per rule on every Case, and a lone surrogate in the input head still reads as
U+FFFD.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.world import branch
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_RULES = [{"label": f"l{index}", "pattern": rf"\bword{index}\b"} for index in range(32)]


def _intent(rules: list[dict[str, str]]) -> str:
    spec = {"schema": "screamingface.keywords.v1", "multi": True, "rules": rules}
    return json.dumps({"sel_1": spec, "sel_2": spec})


def _labels(text: str, intent: str) -> dict[str, Any]:
    reply = branch._keywords(
        Request(path=branch.KEYWORDS_ROUTE, context=text, intent=intent, params={})
    )
    return json.loads(reply)


def test_keywords_compiles_each_rule_once_across_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled: list[object] = []
    real = branch.compile_regex

    def counting(args: Any) -> Any:
        compiled.append(args["pattern"])
        return real(args)

    monkeypatch.setattr(branch, "compile_regex", counting)
    branch._parsed_keywords.cache_clear()
    intent = _intent(_RULES)

    first = _labels("word3 and word7", intent)
    second = _labels("only word31", intent)

    assert first["sel_1"]["labels"] == ["l3", "l7"] == first["sel_2"]["labels"]
    assert second["sel_1"]["labels"] == ["l31"]
    assert len(compiled) == len(_RULES) * 2  # once per rule of each selector, for both Cases


def test_keywords_reads_a_lone_surrogate_in_the_head_as_replacement() -> None:
    intent = _intent([{"label": "hit", "pattern": "a�b"}])

    assert _labels("a\ud800b", intent)["sel_1"]["labels"] == ["hit"]


def test_keywords_still_refuses_a_pattern_re2_cannot_run() -> None:
    branch._parsed_keywords.cache_clear()
    intent = _intent([{"label": "bad", "pattern": "(?=x)"}])

    with pytest.raises(ResolutionError, match="sel_1 has a pattern RE2 cannot run"):
        _labels("x", intent)
