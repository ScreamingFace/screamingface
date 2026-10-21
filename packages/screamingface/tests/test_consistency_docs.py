"""The README and the CHANGELOG describe E4b part 7, consistency samples (unit 7, docs).

FEATURE: a benchmark author reads the SDK README to learn how to declare ``sf.Consistency``, what
the number means, what it costs, what happens when an extra call fails, and how the report shows
it (ans:Q3, ans:Q4). The rows are DC#1 to DC#5 of
docs/spec/2026-10-16-e4b-consistency/prd/docs.md. The README code block must compile to the two
consistency url4 fixtures; the drift guard ``test_consistency_contract_fixtures.py`` keeps each
fixture byte-equal to its SDK builder, so the README code is the code that the tests prove.
``_section`` flattens the whitespace, so a re-wrap of the README prose does not break a test.
Part 6 builds in parallel and also adds a README section before ``## Install`` and a CHANGELOG
bullet after the part 5 bullet, so these tests check the order, never a fixed index (contracts
C8).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app
from test_consistency_contract_fixtures import BUILDERS
from test_evidence_completeness_docs import _section
from test_show_signals_docs import (
    _COUNTED_TOKENS,
    _first_features_bullets,
    _headings_between,
    _unreleased,
)

import screamingface as sf
from screamingface import report as sf_report
from screamingface._evaluation.candidate import compile_candidate

_README = Path(__file__).resolve().parents[1] / "README.md"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
_SIGNALS = "### Signal sources"
_GATE = "### Gate the majority"
_FUSION = "### Fusion as a named recipe"
_CONSISTENCY = "### Consistency samples"
_INSTALL = "## Install"
_BROWSE = "### Browse completed Case results"
_COMBINE = "### Combine steps in the report"
_ACCOUNTING = "### Completed accounting breakdown"
_PART_7 = "E4b part 7"
# The README name of each recipe -> the url4 fixture of unit 4 (consistency-api F1, F2).
_RECIPES = {
    "c1_pick_most_consistent": "consistency_pick_candidate.url4",
    "c2_median_consistency": "consistency_median_candidate.url4",
}
# Verbatim sentences of PRD docs §2.1.
_COST = (
    "Each member makes n more calls on every Case: a `sf.Fanout` of M members makes M × n extra"
    " calls, and you pay for them. The extra calls run also when the member call fails."
)
_FAILURE = (
    "A failed extra call does not fail the Case: the value is the share of matches over the extra"
    " calls that answered, and when every extra call fails, the value is missing."
)
_SEED = (
    "The extra calls use fixed seeds that the recipe sets, so a replay returns the same samples;"
    " they do not change with the run seed."
)
_PREFLIGHT = (
    "The free preflight checks that each member's model takes `seed` and `temperature` before any"
    " call."
)
_WEIGHT = (
    '`sf.Vote(weights="cons")` weights each member by its value; a member with the'
    " value 0 has no weight and does not vote."
)
_REPORT = (
    "The Case pane, the run summary and the export show the value and the failed extra calls (see"
    ' "Combine steps in the report").'
)
_CHIP = "`samples · cons · 4 per member · failed 6 of 12`"
_SUMMARY = "`samples · cons · failed 12 of 24`"
_PART_5_HEAD = "**screamingface:** gate a majority vote (E4b part 5)."
_BULLET_HEAD = "**screamingface:** measure how often a member repeats its answer (E4b part 7)."
_BULLET_TAIL = "**Requires an SF Engine with the E4b part 7 consistency source.**"


def _raw_section(heading: str) -> str:
    """The README text under ``heading``, up to the next ``##`` or ``###`` heading, as written."""

    text = _README.read_text(encoding="utf-8")
    assert heading in text, f"README.md has no {heading!r} section"
    rest = text[text.index(heading) + len(heading) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _part_7_bullets() -> list[str]:
    return [entry for entry in _unreleased().split("\n* ") if _PART_7 in entry]


def _bullet_index(bullets: list[str], head: str) -> int:
    """The index of the one bullet that starts with ``head``."""

    found = [index for index, bullet in enumerate(bullets) if bullet.startswith(head)]
    assert len(found) == 1, f"{len(found)} Features bullets start with {head!r}"
    return found[0]


def test_readme_keeps_the_fusion_install_and_report_anchors() -> None:
    # DC#1 CHAR (README.md:1048, :1135, :1172, :1450, :1490 on 633fec3a1): the neighbours of the
    # new text, each once, in this order.
    text = _README.read_text(encoding="utf-8")
    headings = (_GATE, _FUSION, _INSTALL, _COMBINE, _ACCOUNTING)
    for heading in headings:
        assert text.count(f"\n{heading}\n") == 1, heading
    places = [text.index(f"\n{heading}\n") for heading in headings]
    assert places == sorted(places)


def test_readme_consistency_section_sits_before_install_and_states_the_rules() -> None:
    # DC#2 (DC-1, ans:Q3, ans:Q4, P2-P4, P10-P12, P17-P19): the code has the names, and the
    # section is after Fusion as a named recipe and before Install, with the rules. WHY no fixed
    # list for Fusion..Install: part 6 adds its own section in the same range (contracts C8).
    assert hasattr(sf, "Consistency")
    assert hasattr(sf_report, "CombineSampleCount")
    assert sf.Consistency(n=5).temperature == 1.0
    between = _headings_between(_FUSION, _INSTALL)
    assert between[0] == _FUSION
    assert between.count(_CONSISTENCY) == 1
    assert _headings_between(_SIGNALS, _FUSION) == [_SIGNALS, _GATE]
    section = _section(_CONSISTENCY)
    for phrase in (
        "sf.Consistency(n=",
        '`signals={"cons": sf.Consistency(n=5)}`',
        "distinct seeds",
        "`temperature`",
        "its other params do not change",
        "the step's own extract and normalize",
        '`sf.ArgMax("cons")`',
        "the `text` normalizer",
        "never vote",
        "one `sf.Consistency` per `sf.Fanout`",
        "one `sf.Model`",
        "1 to 32",
        "1024",
        "corrective loop",
        "a successful extra call that does not match",
        "no answer to compare",
        _COST,
        _FAILURE,
        _SEED,
        _PREFLIGHT,
        _WEIGHT,
        _REPORT,
    ):
        assert phrase in section, phrase


@requires_engine_app
def test_readme_consistency_recipes_compile_to_the_fixtures() -> None:
    # DC#3 (DC-1, CA-2, CA-3): the README code block assigns the two recipes, and each compiles
    # to its SDK builder and its url4 fixture byte for byte (CA#6 keeps the two equal).
    assert ENGINE_APP.exists()
    blocks = _CODE.findall(_raw_section(_CONSISTENCY))
    assert len(blocks) == 1, "the Consistency samples section has one python code block"
    namespace: dict[str, Any] = {}
    exec(blocks[0], namespace)  # the README code is ours, and this is what an author runs
    for readme_name, fixture_name in _RECIPES.items():
        assert readme_name in namespace, f"the README code does not assign {readme_name}"
        written = namespace[readme_name]
        assert isinstance(written, sf.Recipe), readme_name
        url4 = compile_candidate(written, operators=engine_operators()).url4
        assert url4 == BUILDERS[fixture_name](), readme_name
        fixture = COMBINE_CONTRACT / fixture_name
        assert fixture.exists(), f"combine_contract/{fixture_name} is missing"
        # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
        assert url4 == fixture.read_text(encoding="utf-8").removesuffix("\n"), readme_name


def test_combine_report_section_names_consistency() -> None:
    # DC#4 (DC-D1, consistency-display CD-1 to CD-4): one new paragraph, no new heading between
    # Browse and Accounting.
    assert _headings_between(_BROWSE, _ACCOUNTING) == [_BROWSE, _COMBINE]
    section = _section(_COMBINE)
    for phrase in (
        "**Consistency.**",
        _CHIP,
        "`2 failed`",
        "`every sample failed`",
        "`no answer to compare`",
        _SUMMARY,
        "`operations[].combine.consistency`",
    ):
        assert phrase in section, phrase


def test_changelog_has_one_part_7_bullet_after_part_5_without_counted_tokens() -> None:
    # DC#5 (DC-2, DC-D2): one part 7 bullet in the first Features list, after the part 5 bullet;
    # only a part 6 bullet may sit between them (contracts C8). It holds none of the tokens that
    # other docs tests count, and no other part's name.
    assert len(_part_7_bullets()) == 1
    features = _first_features_bullets()
    part_5 = _bullet_index(features, _PART_5_HEAD)
    part_7 = _bullet_index(features, _BULLET_HEAD)
    assert part_5 < part_7
    for between in features[part_5 + 1 : part_7]:
        assert "(E4b part 6)" in between, between[:80]
    bullet = features[part_7]
    assert bullet.endswith(_BULLET_TAIL)
    assert 'the README section "Consistency samples"' in bullet
    for token in (*_COUNTED_TOKENS, "E4b part 3", "E4b part 4", "E4b part 5", "E4b part 6"):
        assert token not in bullet, token
