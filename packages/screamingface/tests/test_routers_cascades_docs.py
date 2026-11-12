"""The README and the CHANGELOG describe routers, cascades and the budget (E4c, docs).

FEATURE: OME-1291 docs PRD rows #2 - #4, #8 - #15, #18 - #21. A researcher reads the SDK README
section "Choose whether a model runs" to learn what routing, a cascade and orchestration mean
here, and copies one recipe per paper family. Each recipe compiles offline to the url4 that the
Engine runs (``test_e4c_docs_fixtures.py``). ``_section`` flattens the whitespace, so a re-wrap
of the prose does not break a test.
STORY: as a reader who copies a recipe, the README code is the code the Engine proves, and the
README tells me what each branch costs and what it cannot do.

INVARIANT: these tests never reach the network. A code block is scanned for network markers
before it runs, and it runs only to build recipes and compile them to url4 bytes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from _combine_contract import requires_engine_app
from test_e4c_docs_fixtures import RECIPES, compile_url4, read_fixture
from test_evidence_completeness_docs import _section
from test_show_signals_docs import _headings_between, _unreleased

import screamingface as sf

_PACKAGE = Path(__file__).resolve().parents[1]
_REPO = _PACKAGE.parents[1]
_README = _PACKAGE / "README.md"
_NOTEBOOKS = _PACKAGE / "examples"
_HEADING = "### Choose whether a model runs"
_CONSISTENCY = "### Consistency samples"
_INSTALL = "## Install"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
_E4C = "(E4c, `OME-1291`)"
# DC-12: a docs block with one of these could reach a hosted service or start a login.
NETWORK_MARKERS = (
    "sf.Client(",
    "sf.AsyncClient(",
    "sf.evaluate(",
    ".evaluate(",
    ".connect(",
    "login",
    "https://",
    "http://",
)
# DC-11: the words that describe E4c as future work.
_FUTURE = ("E4c will", "until E4c", "E4c removes", "E4c can", "comes with E4c")


def refuse_network_markers(code: str, where: str) -> None:
    """Fail before ``exec`` when a docs code block names a network marker (DC-12)."""

    found = [marker for marker in NETWORK_MARKERS if marker in code]
    assert not found, f"{where} names network markers {found}: docs blocks run offline only"


def first_difference(written: str, fixture: str) -> int:
    """The offset of the first byte where the two url4 texts differ (DC-13)."""

    pairs = zip(written, fixture, strict=False)
    return next((at for at, (a, b) in enumerate(pairs) if a != b), min(len(written), len(fixture)))


def check_recipe_bytes(name: str, written: str, fixture: str) -> None:
    """The README recipe compiles to its fixture, or the message names it and the offset."""

    assert written == fixture, (
        f"README recipe {name} differs from gate_contract/{name}.url4 at byte "
        f"{first_difference(written, fixture)}: move the README and the fixture together"
    )


def _raw_section() -> str:
    text = _README.read_text(encoding="utf-8")
    assert _HEADING in text, f"README.md has no {_HEADING!r} section"
    rest = text[text.index(_HEADING) + len(_HEADING) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _code() -> str:
    blocks = _CODE.findall(_raw_section())
    assert len(blocks) == 1, "the section has one python code block"
    return blocks[0]


def _recipes() -> dict[str, Any]:
    code = _code()
    refuse_network_markers(code, _HEADING)
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # the README code is ours; it builds recipes and makes no call
    return {name: value for name, value in namespace.items() if re.fullmatch(r"d\d+_\w+", name)}


# --- offline guard and recipe bytes (#2 - #4, #13) ---------------------------------------------


@pytest.mark.parametrize("marker", NETWORK_MARKERS)
def test_docs_blocks_with_network_markers_are_refused_before_exec(marker: str) -> None:
    # #2 (DC-12)
    with pytest.raises(AssertionError, match=re.escape(marker)):
        refuse_network_markers(f"x = 1\n{marker}\n", "a block")
    refuse_network_markers(_code(), _HEADING)


@requires_engine_app
@pytest.mark.parametrize("name", list(RECIPES))
def test_readme_router_recipes_compile_to_the_engine_fixtures(name: str) -> None:
    # #3 (DC-3, DC-4)
    written = _recipes()[name]
    assert isinstance(written, sf.Recipe), name
    check_recipe_bytes(name, compile_url4(written), read_fixture(f"{name}.url4"))


@requires_engine_app
def test_stale_recipe_bytes_name_the_recipe_and_offset() -> None:
    # #4 (DC-13)
    fixture = read_fixture("d4_cope_cascade.url4")
    stale = fixture[:40] + ("X" if fixture[40] != "X" else "Y") + fixture[41:]
    with pytest.raises(AssertionError) as caught:
        check_recipe_bytes("d4_cope_cascade", stale, fixture)
    assert "README recipe d4_cope_cascade" in str(caught.value)
    assert "at byte 40" in str(caught.value)


def test_readme_recipe_set_equals_the_table() -> None:
    # #13 (DC-17): a new recipe without a fixture, or a fixture without a recipe, fails.
    assert list(_recipes()) == list(RECIPES)


# --- the section prose (#8 - #12, #14, #20, #21) -----------------------------------------------


def test_section_sits_after_consistency_samples_before_install() -> None:
    headings = _headings_between(_CONSISTENCY, _INSTALL)
    assert headings == [_CONSISTENCY, _HEADING]


def test_section_defines_routing_cascade_orchestration() -> None:
    # #8 (DC-1)
    section = _section(_HEADING)
    for phrase in (
        "**Routing**: a `sf.Gate` decides before any answer exists",
        "(`sf.budget.remaining()`)",
        "**Cascade**: a `sf.Gate` decides after an answer exists",
        "the next tier answers the original question, not the previous answer",
        "**Orchestration**: multi-step controllers, debate and agent loops",
        "(E4d, E10c)",
        "a branch that is not selected makes zero model calls",
        "the report says that it was not selected and why",
    ):
        assert phrase in section, phrase


def test_section_says_gate_is_the_only_branch_construct() -> None:
    # #9 (DC-2)
    section = _section(_HEADING)
    for phrase in (
        "`sf.Gate` is the only branch construct",
        "`sf.abstain()` or `sf.fail()`",
        "`sf.Cascade(t1, sf.escalate_if(...), t2)` is a short form of nested Gates",
        "An N-way choice is nested Gates",
        "is a short form of nested Gates: its `repr`",
    ):
        assert phrase in section, phrase
    assert "Gate(" in repr(RECIPES["d4_cope_cascade"]())


def test_section_states_the_outcomes_and_their_codes() -> None:
    # #10 (DC-5, DC-6)
    section = _section(_HEADING)
    for phrase in (
        "abstains with `gate_not_met`",
        "scored decline",
        "abstains with `budget_refused`",
        "fails with the code `fail_closed`. It is a failure, never an abstain",
        "costs nothing",
    ):
        assert phrase in section, phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "An escalated Case pays for 2 + 5 samples, not 2 + 3 (OME-1630",  # a
        "A cascade decides per full answer. It does not escalate per step or per token",  # b
        'A guard that fires runs no model. A `sf.LLMClassifier` after it shows "not run"',  # c
        "A call with an unknown cost counts as $0 against a USD cap, and the report warns",  # d
        "The cap is for one Case, and the SDK writes it one time, on the candidate",  # e
        "Nothing escalates unless a line says so",  # f (2026-11-12)
        "A tier whose number is missing (for example, a reply with no log-probability) fails the"
        " Case with the code `signal_missing`",  # f
    ],
)
def test_section_states_each_limit(phrase: str) -> None:
    # #11 (DC-7 a - f)
    assert phrase in _section(_HEADING)


def test_section_lists_what_is_not_in_the_toolkit() -> None:
    # #12 (DC-8)
    section = _section(_HEADING)
    tail = section[section.index("Not in this toolkit:") :]
    for phrase in (
        "(Clusters)",
        "parallel first-success race",
        "(E4a)",
        "(E4b)",
        "Debate (E4d)",
        "(E10c, E10d, E10e)",
        "Early exit inside the token loop",
        "Training a router",
    ):
        assert phrase in tail, phrase


def test_section_has_no_forward_reference_to_skipping() -> None:
    # #14 (DC-18)
    section = _section(_HEADING)
    for word in ("E4c", " will ", "comes with", "later"):
        assert word not in section, word
    for word in ("Branches", "`not_selected`", "`budget_refused`"):
        assert word in section, word


def test_definitions_match_the_gate_docstring() -> None:
    # #20 (DC-19): the code says the same as the README.
    doc = " ".join((sf.Gate.__doc__ or "").split())
    assert "Routing decides before any answer exists" in doc
    assert "a cascade decides after an answer, from a number on it" in doc
    section = _section(_HEADING)
    assert "decides before any answer exists" in section
    assert "decides after an answer exists. It reads a number on that answer" in section


def test_recipe_comments_claim_the_decision_shape_only() -> None:
    # #21 (DC-20)
    section = _section(_HEADING)
    assert "A recipe gives the decision shape of that family only" in section
    assert "it does not reproduce the numbers of a paper" in section
    comments = [line for line in _code().splitlines() if line.lstrip().startswith("#")]
    assert len(comments) >= len(RECIPES) - 1
    for comment in comments:
        for claim in ("reproduce", "accuracy", "%", "same results", "matches the paper"):
            assert claim not in comment.lower(), comment


# --- the rewritten sentences, the Examples list and the CHANGELOG (#15, #18) -------------------


def test_examples_list_names_notebook_19() -> None:
    # #18 (DC-21)
    text = _README.read_text(encoding="utf-8")
    examples = text[text.index("\n## Examples\n") :]
    assert "[`examples/20_routers_cascades.ipynb`](examples/20_routers_cascades.ipynb)" in examples
    assert (_NOTEBOOKS / "20_routers_cascades.ipynb").exists()


def _bullets(heading: str) -> list[str]:
    body = _unreleased().split(f"\n{heading}\n", 1)[1].split("\n### ", 1)[0]
    return [entry.strip() for entry in body.split("\n* ")[1:]]


def test_changelog_unreleased_has_the_breaking_and_feature_bullets_first() -> None:
    # #15 (DC-9): the E4c bullets lead their lists (E4b precedent ea90188c1).
    breaking = _bullets("### Breaking changes")
    assert [_E4C in entry for entry in breaking[:3]] == [True, True, False]
    assert "`sf.Gate` is the one branch construct" in breaking[0]
    assert "The E4b limits are gone" in breaking[0]
    assert "runs only on the Cases where the gate takes it" in breaking[1]
    assert "operation list changes" in breaking[1]

    features = _bullets("### Features")
    count = sum(1 for entry in features if _E4C in entry)
    assert count == 10  # 2026-11-12: + escalate_if/unanswered, abstain()/fail(), bare signal
    assert all(_E4C in entry for entry in features[:count])
    text = " ".join(features[:count])
    for token in (
        "`sf.RegexClassifier(",
        "`sf.LLMClassifier(",
        "`sf.Cascade(",
        "skip a `sf.Fanout` member with a Gate",
        "`then=sf.fail()`",
        "`sf.escalate_if(sf.unanswered())`",
        "`sf.WithBudget(",
        "sf.budget.remaining()",
        '"Branches"',
    ):
        assert token in text, token
    words = features[count - 1]
    for token in (
        "`fail_closed`",
        "`signal_missing`",
        "`quorum_not_met`",
        "`budget_refused`",
        "`OME-1233`",
    ):
        assert token in words, token


def test_no_docstring_or_message_names_e4c_as_future_work() -> None:
    # #19 (DC-11)
    roots = (
        _PACKAGE / "src" / "screamingface",
        _REPO / "apps" / "screamingface-engine" / "src" / "screamingface_engine",
    )
    found = [
        f"{path.relative_to(_REPO)}: {phrase}"
        for root in roots
        if root.exists()
        for path in sorted(root.rglob("*.py"))
        for phrase in _FUTURE
        if phrase in path.read_text(encoding="utf-8")
    ]
    assert found == []
