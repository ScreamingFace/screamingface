"""sf.Verbalized: the SDK refuses a bad pattern, compiles ignore_case and rebuilds from url4.

FEATURE: ``sf.Verbalized(pattern)`` reads the number that a member states in its text (E4b part 3,
unit 2; VB#4, VB#7 and VB#11 of the verbalized PRD).
STORY: as a benchmark author, I write signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")} and
the SDK refuses a pattern that the Engine would refuse, before any spend.
INVARIANT defended: the SDK pattern rules are the Engine's rules (regex@1 plus exactly one group);
``ignore_case`` is written only when set (one spelling per declaration); a Fusion with a verbalized
source rebuilds from url4 with the same pattern and flag.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_contract import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

MEMBERS = ["provider/a", "provider/b", "provider/c"]
CONF_PATTERN = "Confidence: ([0-9]+)"


# --- VB#4 (SDK half): a bad pattern or a group count other than one is refused ---------------


def test_verbalized_refuses_a_bad_pattern_or_a_group_count_other_than_one() -> None:
    # Positive first: a valid one-group pattern builds, so the refusals below are about the rules.
    assert sf.Verbalized(CONF_PATTERN)
    assert sf.Verbalized("(?P<n>[0-9]+)")
    assert sf.Verbalized(CONF_PATTERN) == sf.Verbalized(CONF_PATTERN)

    with pytest.raises(ValueError, match="exactly one capture group"):
        sf.Verbalized("Confidence: [0-9]+")
    with pytest.raises(ValueError) as two_groups:
        sf.Verbalized("ZQ(a)(b)")
    assert "ZQ" not in str(two_groups.value)
    for bad in ("(", "a" * 257, "", "(a)\\1"):
        with pytest.raises(ValueError):
            sf.Verbalized(bad)

    with pytest.raises(TypeError):
        sf.Verbalized(5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sf.Verbalized(CONF_PATTERN, ignore_case="yes")  # type: ignore[arg-type]


# --- VB#7 (SDK half): ignore_case is written only when it is set ------------------------------


def test_verbalized_ignore_case_compiles_into_the_spec() -> None:
    assert sf.Verbalized(CONF_PATTERN, ignore_case=True)._spec() == {
        "source": "verbalized",
        "pattern": CONF_PATTERN,
        "ignore_case": True,
    }
    assert sf.Verbalized(CONF_PATTERN)._spec() == {"source": "verbalized", "pattern": CONF_PATTERN}
    assert repr(sf.Verbalized(CONF_PATTERN, ignore_case=True)) == (
        "Verbalized('Confidence: ([0-9]+)', ignore_case=True)"
    )


# --- VB#11: a Fusion with a verbalized source rebuilds from url4 ------------------------------


def test_verbalized_fusion_rebuilds_from_url4() -> None:
    pattern = r"Confidence:\s*([0-9]+)"
    fusion = sf.Fanout(
        MEMBERS, signals={"conf": sf.Verbalized(pattern, ignore_case=True)}
    ) >> sf.ArgMax("conf")
    url4 = compile_candidate(fusion, operators=engine_operators()).url4
    code = sf.Url4(url4).to_python()
    assert r"signals={'conf': sf.Verbalized('Confidence:\\s*([0-9]+)', ignore_case=True)}," in code

    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    rebuilt = namespace["candidate"]
    assert rebuilt.signals["conf"] == sf.Verbalized(pattern, ignore_case=True)
    assert compile_candidate(rebuilt, operators=engine_operators()).url4 == url4
