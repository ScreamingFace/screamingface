"""The README and the CHANGELOG describe E4b part 6, signal sums and the abstain band (unit 7).

FEATURE: a benchmark author reads the SDK README to learn how to declare a sum of signals, how a
rule or a gate reads it, how the abstain band works, and how the report shows both (ans:Q1,
ans:Q2). The rows are DC#1 to DC#5 of docs/spec/2026-10-16-e4b-signal-sums/prd/docs.md. The README
code block must compile to the two url4 fixtures that the Engine runs offline; the drift guard
``test_sum_contract_fixtures.py`` keeps each fixture byte-equal to its SDK builder, so the README
code is the code that the Engine proves. ``_section`` flattens the whitespace, so a re-wrap of the
README prose does not break a test.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from typing import Any

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app
from test_evidence_completeness_docs import _section
from test_show_signals_docs import (
    _COUNTED_TOKENS,
    _first_features_bullets,
    _headings_between,
    _unreleased,
)
from test_sum_contract_fixtures import BUILDERS

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.answer import ANSWER_REASONS

_README = Path(__file__).resolve().parents[1] / "README.md"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
_SIGNALS = "### Signal sources"
_GATE = "### Gate the majority"
_FUSION = "### Fusion as a named recipe"
_SUM = "### Sum signals and the abstain band"
_CONSISTENCY = "### Consistency samples"  # E4b part 7, after the restack on part 6
_INSTALL = "## Install"
_BROWSE = "### Browse completed Case results"
_COMBINE = "### Combine steps in the report"
_ACCOUNTING = "### Completed accounting breakdown"
_PART_6 = "E4b part 6"
# The README name of each recipe -> the url4 fixture that the Engine runs (sum-api SA-5, band-api
# BA-4).
_FIXTURES = {
    "s1_sum_pick": "sum_pick_candidate.url4",
    "s2_band_gate": "gate_band_vote_candidate.url4",
}
# The largest usable vote weight: the Engine MAX_WEIGHT (E/combine/spec.py) and the SDK
# _MAX_WEIGHT (S/reducer.py), both the largest float divided by 256.
_MAX_WEIGHT_TEXT = "7.022238808055921e+305"
# Verbatim sentences of PRD docs §2.1.
_MISSING = (
    "When a component is missing, the sum is missing, not zero. A rule leaves the member out, as"
    " for any declared signal."
)
_EXACT = (
    "The Engine adds the exact products and rounds once, so the order of the components does not"
    " change the value."
)
_READS = (
    "A rule or a gate reads the sum by its name: `sf.Pick`, `sf.Rank`, `sf.Filter`, a vote weight,"
    ' and a gate on `"chosen:risk"` or `"mean:risk"`.'
)
_WEIGHT = (
    'A sum that adds `sf.Logprob("mean")`, `sf.Logprob("sum")` or `sf.Entropy(...)` cannot be a'
    " vote weight: `sf.Fusion` raises `ValueError` before any call. A member whose sum is zero or"
    f" less, or larger than `{_MAX_WEIGHT_TEXT}` (the largest float divided by 256), gets no"
    " weight, and the vote leaves it out with `no_weight`."
)
_COST = (
    "A judge or writer fallback still runs on every Case, also when the number is in the band; its"
    " reply is not read."
)
_SCOPE = 'A sum adds the signals of one member. To compare the panel, gate on `"mean:<name>"`.'
_REPORT = (
    "The Case pane, the run summary and the export show the sum and the band (see"
    ' "Combine steps in the report").'
)
_HEADER = "`source: sum of 0.5 × sev_a + 0.3 × sev_b`"
_CHIP = "`gate · agreement >= 0.7 · band [0.6, 0.7] · observed 0.6667 · in band · abstain`"
_SUMMARY = "`gate · majority 1 of 3 · fallback 1 of 3 · in band 1 of 3`"
_BULLET_HEAD = "**screamingface:** sum declared signals and abstain in a band (E4b part 6)."
_BULLET_TAIL = "**Requires an SF Engine with the E4b part 6 signal sums and abstain band.**"


def _raw_section(heading: str) -> str:
    """The README text under ``heading``, up to the next ``##`` or ``###`` heading, as written."""

    text = _README.read_text(encoding="utf-8")
    assert heading in text, f"README.md has no {heading!r} section"
    rest = text[text.index(heading) + len(heading) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _part_6_bullets() -> list[str]:
    return [entry for entry in _unreleased().split("\n* ") if _PART_6 in entry]


def test_readme_keeps_its_anchors() -> None:
    # DC#1 CHAR (README.md:930, :1048, :1135, :1172, :1421, :1450, :1490 on 633fec3a1): the
    # neighbours of the new text, each once, in this order.
    text = _README.read_text(encoding="utf-8")
    headings = (_SIGNALS, _GATE, _FUSION, _INSTALL, _BROWSE, _COMBINE, _ACCOUNTING)
    for heading in headings:
        assert text.count(f"\n{heading}\n") == 1, heading
    places = [text.index(f"\n{heading}\n") for heading in headings]
    assert places == sorted(places)


def test_readme_sum_section_sits_after_fusion_and_states_the_rules() -> None:
    # DC#2 (DC-1, ans:Q1, ans:Q2, P3-P5, P7-P13, N1-N3): the code has the names, and the section
    # is directly after Fusion as a named recipe, directly before Install, with the rules.
    assert hasattr(sf, "Sum")
    assert "in_band" in ANSWER_REASONS
    assert "abstain_band" in inspect.signature(sf.Gate).parameters
    assert repr(sys.float_info.max / 256) == _MAX_WEIGHT_TEXT
    # Restack on part 6 (2026-10-16): part 7 adds its section directly after this one.
    assert _headings_between(_FUSION, _INSTALL) == [_FUSION, _SUM, _CONSISTENCY]
    assert _headings_between(_SIGNALS, _FUSION) == [_SIGNALS, _GATE]
    section = _section(_SUM)
    for phrase in (
        '`signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}), ...}`',
        "`risk = 0.5 × sev_a + 0.3 × sev_b`",
        "never an E4a key",
        "never another `sf.Sum`",
        "1 to 7 components",
        "a finite number that is not zero",
        "counts toward the 8 names",
        _MISSING,
        _EXACT,
        _READS,
        _WEIGHT,
        "`sf.Gate(..., abstain_band=(lo, hi))`",
        "The band is closed (both ends are in it).",
        "The Engine checks the band before the comparison.",
        "the Case abstains with the reason `in_band` for every `otherwise`",
        "When the number is outside the band, the gate compares as before.",
        "A missing number skips the band",
        '`"branch": "band"`',
        "Coverage counts the Case with the other abstains.",
        _COST,
        _SCOPE,
        _REPORT,
    ):
        assert phrase in section, phrase


@requires_engine_app
def test_readme_sum_recipes_compile_to_the_fixtures() -> None:
    # DC#3 (DC-1, SA-5, BA-4): the README code block assigns the two recipes, and each compiles to
    # its SDK builder and its url4 fixture byte for byte (SA#12, BA#7 keep the two equal).
    assert ENGINE_APP.exists()
    blocks = _CODE.findall(_raw_section(_SUM))
    assert len(blocks) == 1, "the Sum signals section has one python code block"
    namespace: dict[str, Any] = {}
    exec(blocks[0], namespace)  # the README code is ours, and this is what an author runs
    for readme_name, fixture_name in _FIXTURES.items():
        assert readme_name in namespace, f"the README code does not assign {readme_name}"
        written = namespace[readme_name]
        assert isinstance(written, sf.Recipe), readme_name
        url4 = compile_candidate(written, operators=engine_operators()).url4
        assert url4 == BUILDERS[fixture_name](), readme_name
        fixture = COMBINE_CONTRACT / fixture_name
        assert fixture.exists(), f"combine_contract/{fixture_name} is missing"
        # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
        assert url4 == fixture.read_text(encoding="utf-8").removesuffix("\n"), readme_name


def test_combine_report_section_names_sums_and_the_band() -> None:
    # DC#4 (DC-D1, sum-band-display SD-1 to SD-5): one new paragraph, no new heading between
    # Browse and Accounting.
    assert _headings_between(_BROWSE, _ACCOUNTING) == [_BROWSE, _COMBINE]
    section = _section(_COMBINE)
    for phrase in (
        "**Sums and the band.**",
        _HEADER,
        _CHIP,
        "`abstain · in_band`",
        _SUMMARY,
        "`operations[].combine.gate.abstain_band`",
    ):
        assert phrase in section, phrase


def test_changelog_has_one_part_6_bullet_at_position_3_without_counted_tokens() -> None:
    # DC#5 (DC-2, DC-D2): one part 6 bullet, the fourth under the first Features list (after the
    # part 4, part 3 and part 5 bullets), with none of the tokens that other docs tests count.
    assert len(_part_6_bullets()) == 1
    features = _first_features_bullets()
    assert "E4b part 4" in features[0]
    assert "(E4b part 3)" in features[1]
    assert "(E4b part 5)" in features[2]
    assert features[3].startswith(_BULLET_HEAD)
    assert features[3].endswith(_BULLET_TAIL)
    assert 'the README section "Sum signals and the abstain band"' in features[3]
    for token in (*_COUNTED_TOKENS, "E4b part 3", "E4b part 4", "E4b part 5"):
        assert token not in features[3], token
