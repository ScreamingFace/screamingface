"""Drift guard for the verbalized engine fixture (E4b part 3, unit 2; E7).

FEATURE: the Engine runs ``combine_contract/verbalized_vote_candidate.url4`` verbatim (VB#8). This
file keeps that data file byte-identical to what the SDK compiles today.
STORY: as a maintainer, a change to the SDK compile of a verbalized vote fails here, not in a
silent engine run.
INVARIANT defended: the fixture is the SDK compile of one three-member vote weighted by a
verbalized confidence (VB-3). It is not a README recipe (E7; recipes are unit 5).

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_verbalized_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

FIXTURE = "verbalized_vote_candidate.url4"


def verbalized_vote_url4() -> str:
    """Three members state a confidence; the vote weights each answer by it (VB-3)."""
    recipe = sf.Fanout(
        ["prov/alpha", "prov/beta", "prov/gamma"],
        signals={"conf": sf.Verbalized("Confidence: ([0-9]+)")},
    ) >> sf.Vote(weights=sf.signal("conf"))
    return compile_candidate(recipe, operators=engine_operators()).url4


def write_fixture() -> None:
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (COMBINE_CONTRACT / FIXTURE).write_text(verbalized_vote_url4() + "\n", encoding="utf-8")


@requires_engine_app
def test_verbalized_vote_fixture_matches_the_sdk_compile() -> None:
    fixture = COMBINE_CONTRACT / FIXTURE
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{FIXTURE} is missing - run write_fixture()"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == verbalized_vote_url4()
