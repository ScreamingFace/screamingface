"""Drift guard for the url4 fixtures of the E4c spec-gap rows, and the SDK half of SL-25 (E4c).

FEATURE: OME-1291 guards GU-13 (row 14), lazy-fallback LF-22 (row 21), selectors SL-25 (row 25).
The Engine world runs ``gate_contract/{guard_floor_refused,consistency_*}.url4``
verbatim on a fake gateway (``apps/screamingface-engine/tests/unit/test_e4c_spec_gaps.py``).
STORY: as a researcher, a floor guard the budget refuses never falls to the router, the
consistency samples of a gated vote run on every Case, and a Thai pattern compiles unchanged.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_e4c_spec_gap_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from _combine_contract import ENGINE_APP, engine_operators, requires_engine_app
from test_e4c_gate_replay import _replayed

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

GATE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "gate_contract"
_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]


def guard_floor_refused() -> object:
    """GU-13: the floor wants a specialist panel the budget refuses; otherwise is a router."""
    clf = sf.LabelModel("prov/clf", labels=["safe", "medical"])
    topic = sf.Keywords([("math", r"(?i)\bintegral\b")])
    router = sf.Gate(when=sf.label(topic) == "math", then="prov/math", otherwise="prov/general")
    specialists = sf.Fanout(["prov/med_a", "prov/med_b"]) >> sf.Vote()
    floor = sf.Gate(
        when=sf.label(clf) == "medical",
        then=sf.Estimate(specialists, usd=0.01),
        otherwise=router,
    )
    return sf.Budgeted(floor, usd=0.0015)


def _consistency_vote(otherwise: object) -> object:
    return sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=5)}, name="vote") >> sf.Gate(
        when=sf.signal("cons").mean() >= 0.8,
        then=sf.Vote(),
        otherwise=otherwise,  # type: ignore[arg-type]
    )


def consistency_escalates() -> object:
    """LF-22: a gated vote over a Fanout with sf.Consistency(n=5); only the large model is lazy."""
    return _consistency_vote("prov/large")


def consistency_judge() -> object:
    """LF-22: the same gated vote with a lazy judge fallback; only the judge call is gated."""
    return _consistency_vote(sf.JudgePick("prov/judge", rubric="Pick the best answer."))


def consistency_writer() -> object:
    """LF-22: the same gated vote with a lazy writer fallback; only the writer call is gated."""
    return _consistency_vote(sf.Synthesize("prov/writer"))


def _url4(build: Callable[[], object]) -> Callable[[], str]:
    return lambda: compile_candidate(build(), operators=engine_operators()).url4  # type: ignore[arg-type]


BUILDERS: dict[str, Callable[[], str]] = {
    "guard_floor_refused.url4": _url4(guard_floor_refused),
    "consistency_escalates.url4": _url4(consistency_escalates),
    "consistency_judge.url4": _url4(consistency_judge),
    "consistency_writer.url4": _url4(consistency_writer),
}


def write_fixture(name: str) -> None:
    GATE_CONTRACT.mkdir(parents=True, exist_ok=True)
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (GATE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_spec_gap_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    fixture = GATE_CONTRACT / name
    assert fixture.exists(), f"gate_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()


# --- LF-22: the E4b fallback forms beside sf.Consistency -----------------------------------------


_SAMPLES_READ = re.compile(
    r"binding=(synthesis_\d+)[^(]*\(\{input: [^{]*outputs: \{[^}]*\}, (samples: \{[^}]*\})"
)


@pytest.mark.parametrize("build", [consistency_judge, consistency_writer], ids=["judge", "writer"])
def test_consistency_samples_run_under_a_lazy_judge_fallback(build: Callable[[], object]) -> None:
    url4 = compile_candidate(build(), operators=engine_operators()).url4  # type: ignore[arg-type]
    reads = dict(_SAMPLES_READ.findall(url4))

    # LF-22: 3 members x 5 samples, compiled once outside the block; call #1 and the gated
    # call #2 read the same sample panels beside the member answers.
    assert url4.count("&seed=") == 15
    assert sorted(reads) == ["synthesis_1", "synthesis_2"]
    assert reads["synthesis_1"] == reads["synthesis_2"]


@pytest.mark.parametrize("build", [consistency_judge, consistency_writer], ids=["judge", "writer"])
def test_a_consistency_fallback_replays_to_the_compiled_candidate(
    build: Callable[[], object],
) -> None:
    compiled = compile_candidate(build(), operators=engine_operators())  # type: ignore[arg-type]

    replayed = _replayed(compiled.url4)

    assert [op.id for op in compiled.operations].count("op_model_4") == 1
    assert replayed.models == compiled.models
    assert replayed.operations == compiled.operations
    assert replayed.members == compiled.members


# --- SL-25: a Unicode pattern, ASCII labels -------------------------------------------------------


def test_unicode_pattern_matches_thai_question_compiles_unchanged() -> None:
    # SL#25 / SL-25: RE2 owns the pattern; the SDK passes \p{Thai} through, Python re never sees it.
    thai = sf.Keywords([("thai", r"\p{Thai}")])
    recipe = sf.Gate(when=sf.label(thai) == "thai", then="prov/th", otherwise="prov/en")

    url4 = compile_candidate(recipe, operators=engine_operators()).url4

    # WHY four backslashes: JSON escapes the one backslash, and the url4 string escapes both.
    assert r'"pattern":"\\\\p{Thai}"' in url4


def test_a_thai_label_is_refused_by_the_label_rule() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Keywords: a label is 1 to 32 characters"):
        sf.Keywords([("ไทย", r"\p{Thai}")])
