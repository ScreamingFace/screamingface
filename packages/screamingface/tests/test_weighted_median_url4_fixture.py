"""The weighted median url4 fixture matches what the SDK compiles today (E4b, S-3).

FEATURE: the Engine test WM#15 runs a url4 file that the SDK wrote; this guard fails when the SDK
compiler drifts from that file.
STORY: as the maintainer, I regenerate the fixture with write_fixture() when the compiler changes on
purpose, and the drift guard keeps the two in step.
INVARIANT: the file equals the compiled url4 of the builder, with the end-of-file newline removed.
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "weighted_median_confidence_candidate.url4"


def weighted_median_confidence_url4() -> str:
    fusion = sx.Fanout(["prov/alpha", "prov/beta", "prov/gamma", "prov/delta"]) >> sx.Median(
        over="field:answer", weights=sf.signal("field:confidence")
    )
    return compile_candidate(fusion, operators=flow_operators()).url4


@requires_engine_app
def test_weighted_median_url4_fixture_matches_the_sdk_compiler() -> None:
    assert ENGINE_APP.exists()
    assert _FIXTURE.exists(), "the url4 fixture is missing: run write_fixture() in this module"
    assert _FIXTURE.read_text("utf-8").removesuffix("\n") == weighted_median_confidence_url4()


def write_fixture() -> None:
    """Write the builder output to the Engine's contract folder (run by hand, then commit it)."""
    _FIXTURE.write_text(weighted_median_confidence_url4(), encoding="utf-8")
