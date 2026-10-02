"""Drift guard for the engine-side signal-weighted vote fixture (OME-1289, unit 7, SR#10).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/signal_vote_candidate.url4`` verbatim
(its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_signal_vote_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "signal_vote_candidate.url4"


def signal_vote_url4() -> str:
    """Three members, the first with a param, voting with weights = each member's own cost."""

    recipe = sf.Fusion(
        [sf.Model("prov/alpha", params={"temperature": 0.5}), "prov/beta", "prov/gamma"],
        synthesizer=sf.Vote(extract="last_line", normalize="text", weights=sf.signal("cost_usd")),
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(signal_vote_url4(), encoding="utf-8")


@requires_engine_app
def test_engine_signal_vote_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert ENGINE_APP.exists()
    assert _FIXTURE.exists(), "combine_contract/signal_vote_candidate.url4 is missing"
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == signal_vote_url4()
