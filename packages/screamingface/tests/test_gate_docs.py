"""The README and the CHANGELOG describe E4b part 5, the gate of a majority vote (unit 6, docs).

FEATURE: a benchmark author reads the SDK README to learn how to gate a majority vote, what each
fallback does, what it costs today, and how the report shows the gate (ans:Q1 to ans:Q4). The rows
are DC#1 to DC#5 of docs/spec/2026-10-16-e4b-gate-record/prd/docs.md. The README code block must
compile to the four gate url4 fixtures that the Engine runs offline; the drift guard
``test_gate_contract_fixtures.py`` keeps each fixture byte-equal to its SDK builder, so the README
code is the code that the Engine proves. ``_section`` flattens the whitespace, so a re-wrap of the
README prose does not break a test.
"""

from __future__ import annotations

import re
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

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.answer import ANSWER_REASONS

_README = Path(__file__).resolve().parents[1] / "README.md"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
_SIGNALS = "### Signal sources"
_GATE = "### Gate the majority"
_FUSION = "### Fusion as a named recipe"
_BROWSE = "### Browse completed Case results"
_COMBINE = "### Combine steps in the report"
_ACCOUNTING = "### Completed accounting breakdown"
_PART_5 = "E4b part 5"
# The README name of each recipe -> the url4 fixture that the Engine runs (gate-api GA-D6).
_FIXTURES = {
    "g1_agreement_abstain": "gate_abstain_vote_candidate.url4",
    "g2_agreement_judge": "gate_judge_vote_candidate.url4",
    "g3_agreement_writer": "gate_writer_vote_candidate.url4",
    "g4_confidence_gate": "gate_verbalized_vote_candidate.url4",
}
# Verbatim sentences of PRD docs §2.1 (the cost sentence; the failure sentence of contracts C2).
_COST = (
    "In this version the fallback call runs on every Case, also when the gate keeps the majority,"
    " and you pay for it. The gate chooses and records; a cascade that skips the call comes with"
    " E4c."
)
_FAILURE = "If the fallback call fails, the Case fails, also when the gate keeps the majority."
_VERIFIER = (
    "`sf.Vote(verify=None)` is a reserved place for a later verifier; any other value raises"
    " `ValueError`."
)
_NAME = "This gate is not the per-round gate of a corrective loop."
_REPORT = (
    'The Case pane, the run summary and the export show the gate (see "Combine steps in the'
    ' report").'
)
_CHIP = "`gate · agreement >= 0.7 · observed 0.6667 · fallback · judge`"
_SUMMARY = "`gate · majority 2 of 3 · fallback 1 of 3`"
_BULLET_HEAD = "**screamingface:** gate a majority vote (E4b part 5)."
_BULLET_TAIL = "**Requires an SF Engine with the E4b part 5 combine gate.**"


def _raw_section(heading: str) -> str:
    """The README text under ``heading``, up to the next ``##`` or ``###`` heading, as written."""

    text = _README.read_text(encoding="utf-8")
    assert heading in text, f"README.md has no {heading!r} section"
    rest = text[text.index(heading) + len(heading) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _part_5_bullets() -> list[str]:
    return [entry for entry in _unreleased().split("\n* ") if _PART_5 in entry]


def test_readme_keeps_the_signal_sources_and_report_anchors() -> None:
    # DC#1 CHAR (README.md:930, :1048, :1334, :1363, :1393 on 4e622af75): the five neighbours of
    # the new text, each once, in this order.
    text = _README.read_text(encoding="utf-8")
    headings = (_SIGNALS, _FUSION, _BROWSE, _COMBINE, _ACCOUNTING)
    for heading in headings:
        assert text.count(f"\n{heading}\n") == 1, heading
    places = [text.index(f"\n{heading}\n") for heading in headings]
    assert places == sorted(places)


def test_readme_gate_section_sits_after_signal_sources_and_states_the_rules() -> None:
    # DC#2 (DC-1, ans:Q1 to ans:Q4, P2, P4, P10, C2): the code has the names, and the section is
    # directly after Signal sources, directly before Fusion as a named recipe, with the rules.
    assert hasattr(sf, "Gate")
    assert "gate_not_met" in ANSWER_REASONS
    assert _headings_between(_SIGNALS, _FUSION) == [_SIGNALS, _GATE]
    section = _section(_GATE)
    for phrase in (
        "`gate_not_met`",
        "`sf.agreement()`",
        "`sf.signal(name).chosen()`",
        "`sf.signal(name).mean()`",
        "`>=` keeps the majority at equality",
        "a threshold from 0 to 1",
        "the winner's share of the weight",
        '`otherwise="abstain"`',
        "`otherwise=sf.JudgePick(...)`",
        "`otherwise=sf.Synthesize(...)`",
        "coverage counts it with the other abstains",
        _COST,
        _FAILURE,
        "the gate takes the fallback",
        "`no_votes`",
        '`signals={"lp": sf.Logprob("prob")}`',
        '`sf.signal("lp").chosen()`',
        _VERIFIER,
        _NAME,
        _REPORT,
    ):
        assert phrase in section, phrase


@requires_engine_app
def test_readme_gate_recipes_compile_to_the_gate_fixtures() -> None:
    # DC#3 (DC-1, GA-D6): the README code block assigns the four recipes, and each compiles to
    # its url4 fixture byte for byte (the fixture is the SDK builder output, GA#17a, GA#17b).
    assert ENGINE_APP.exists()
    blocks = _CODE.findall(_raw_section(_GATE))
    assert len(blocks) == 1, "the Gate the majority section has one python code block"
    namespace: dict[str, Any] = {}
    exec(blocks[0], namespace)  # the README code is ours, and this is what an author runs
    for readme_name, fixture_name in _FIXTURES.items():
        assert readme_name in namespace, f"the README code does not assign {readme_name}"
        written = namespace[readme_name]
        assert isinstance(written, sf.Recipe), readme_name
        fixture = COMBINE_CONTRACT / fixture_name
        assert fixture.exists(), f"combine_contract/{fixture_name} is missing"
        url4 = compile_candidate(written, operators=engine_operators()).url4
        # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
        assert url4 == fixture.read_text(encoding="utf-8").removesuffix("\n"), readme_name


def test_combine_report_section_names_the_gate() -> None:
    # DC#4 (DC-D1, gate-display GS-1, GS-5, GS-D4): one new paragraph, no new heading between
    # Browse and Accounting.
    assert _headings_between(_BROWSE, _ACCOUNTING) == [_BROWSE, _COMBINE]
    section = _section(_COMBINE)
    for phrase in ("**The gate.**", _CHIP, _SUMMARY, "`operations[].combine.gate`"):
        assert phrase in section, phrase


def test_changelog_has_one_part_5_bullet_at_position_2_without_counted_tokens() -> None:
    # DC#5 (DC-2, DC-D2): one part 5 bullet, the third under the first Features list (after the
    # part 4 and the part 3 bullets), with none of the tokens that other docs tests count.
    bullets = _part_5_bullets()
    assert len(bullets) == 1
    features = _first_features_bullets()
    assert "E4b part 4" in features[0]
    assert "(E4b part 3)" in features[1]
    assert features[2].startswith(_BULLET_HEAD)
    assert features[2].endswith(_BULLET_TAIL)
    assert 'the README section "Gate the majority"' in features[2]
    for token in (*_COUNTED_TOKENS, "E4b part 4"):
        assert token not in features[2], token
