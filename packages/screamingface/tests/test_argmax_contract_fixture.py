"""Drift guard for the engine-side argmax-by-cost fixture (OME-1289, unit 9S, SR-2).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/argmax_cost_candidate.url4`` verbatim
(its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_argmax_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "argmax_cost_candidate.url4"


def argmax_cost_url4() -> str:
    """Three members, the first with a param; the cheapest member's answer is the answer."""

    recipe = sf.Fusion(
        [sf.Model("prov/alpha", params={"temperature": 0.5}), "prov/beta", "prov/gamma"],
        synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min"),
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(argmax_cost_url4(), encoding="utf-8")


@requires_engine_app
def test_engine_argmax_cost_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert ENGINE_APP.exists()
    assert _FIXTURE.exists(), "combine_contract/argmax_cost_candidate.url4 is missing"
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == argmax_cost_url4()
