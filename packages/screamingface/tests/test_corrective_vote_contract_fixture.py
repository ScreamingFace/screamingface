"""Drift guard for the engine-side corrective vote fixture (OME-1289, EV-10 engine half).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/corrective_vote_candidate.url4``
verbatim (its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

The check route comes from the committed ``corrective_loop_candidate.url4`` (the IFEval offer the
Engine already pins), so this fixture links to the same IFEval check surface.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_corrective_vote_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

import re

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "corrective_vote_candidate.url4"
_ROUTE_SOURCE = ENGINE_APP / "tests" / "unit" / "data" / "corrective_loop_candidate.url4"
_ROUTE = re.compile(r"/benchmarks/ifeval/[A-Za-z0-9]+/check-surface")


def corrective_vote_url4() -> str:
    match = _ROUTE.search(_ROUTE_SOURCE.read_text(encoding="utf-8"))
    assert match is not None, "corrective_loop_candidate.url4 lost the IFEval check route"
    recipe = sf.CorrectiveLoop(
        [
            sf.Fusion(["prov/member-a", "prov/member-b", "prov/member-c"], synthesizer=sf.Vote()),
            "prov/member-d",
        ],
        judge="prov/judge",
        max_rounds=2,
    )
    surface = _CheckSurface(
        check_route=match.group(0), feedback_intent="feedback", expected_check_cost="free"
    )
    return compile_candidate(recipe, operators=engine_operators(), check_surface=surface).url4


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(corrective_vote_url4(), encoding="utf-8")


@requires_engine_app
def test_engine_corrective_vote_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert _FIXTURE.exists(), (
        "combine_contract/corrective_vote_candidate.url4 is missing — run write_fixture()"
    )
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == corrective_vote_url4()
