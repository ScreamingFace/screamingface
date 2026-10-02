"""Drift guard for the engine-side judge-weighted vote fixture (OME-1289, unit 8S, SR#11).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/judge_vote_candidate.url4`` verbatim
(its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_judge_vote_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "judge_vote_candidate.url4"


def judge_vote_url4() -> str:
    """Three members voting on a number, each answer weighed by the judge's score for its member."""

    recipe = sf.Fusion(
        ["prov/alpha", "prov/beta", "prov/gamma"],
        synthesizer=sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=sf.Judge("prov/judge", returns="scores", rubric="Score each answer."),
        ),
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(judge_vote_url4(), encoding="utf-8")


@requires_engine_app
def test_engine_judge_vote_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert ENGINE_APP.exists()
    assert _FIXTURE.exists(), "combine_contract/judge_vote_candidate.url4 is missing"
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == judge_vote_url4()
