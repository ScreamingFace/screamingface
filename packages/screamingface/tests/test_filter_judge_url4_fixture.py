"""Drift guard for the engine fixture of a judge Filter Pipeline (E4b unit 6, FJ#12).

The Engine test ``test_sdk_filter_judge_contract.py`` runs
``apps/screamingface-engine/tests/unit/data/combine_contract/filter_judge_candidate.url4``
verbatim. This file keeps that data file byte-equal to what the SDK compiles today.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_filter_judge_url4_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

FIXTURE = "filter_judge_candidate.url4"


def filter_judge_url4() -> str:
    """Three members, a judge Filter at >= 7, then a writer that sees only the kept members."""

    recipe = (
        sx.Fanout(["prov/alpha", "prov/beta", "prov/gamma"])
        >> sx.Judge("prov/judge", rubric="Score each draft from 0 to 10.")
        >> sx.Filter(where=sf.signal("score:judge") >= 7)
        >> sx.Synthesize("prov/writer")
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def write_fixture() -> None:
    # WHY no trailing newline: the end-of-file-fixer hook appends one; both readers strip one.
    (COMBINE_CONTRACT / FIXTURE).write_text(filter_judge_url4(), encoding="utf-8")


@requires_engine_app
def test_filter_judge_fixture_matches_the_sdk_compiler() -> None:
    fixture = COMBINE_CONTRACT / FIXTURE
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{FIXTURE} is missing - run write_fixture()"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == filter_judge_url4()
