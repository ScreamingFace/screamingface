"""Drift guard for the engine-side combine contract fixture (OME-1289).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/two_reducers_candidate.url4`` verbatim
(its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate with ``python -c`` calling ``two_reducers_url4()`` and writing the result to the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _reducer_fixtures import FixtureVote

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import decode_operator_catalog

# parents[3] = the monorepo root (tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[3] / "apps" / "screamingface-engine"
_FIXTURE = (
    _ENGINE_APP / "tests" / "unit" / "data" / "combine_contract" / "two_reducers_candidate.url4"
)

# The real unit-2 ids only: no `last_number@2`, so the fixture pins what the Engine serves.
_ENGINE_OPERATORS = {
    "extract": ("last_number", "last_line"),
    "normalize": ("numeric", "text"),
    "reduce": ("mode",),
    "select": ("first_holder",),
}


def two_reducers_url4() -> str:
    catalog = decode_operator_catalog(
        {
            "object": "list",
            "data": [
                {
                    "id": f"{name}@1",
                    "name": name,
                    "version": 1,
                    "stage": stage,
                    "args_schema": {},
                    "summary": f"{name}.",
                }
                for stage, names in _ENGINE_OPERATORS.items()
                for name in names
            ],
        }
    )
    recipe = sf.Pipeline(
        [
            sf.Fusion(
                ["provider/alpha", "provider/beta", "provider/gamma"], synthesizer=FixtureVote()
            ),
            sf.Fusion(
                ["provider/delta", "provider/epsilon"],
                synthesizer=FixtureVote(extract="last_line", normalize="text"),
            ),
        ]
    )
    return compile_candidate(recipe, operators=catalog).url4


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_engine_combine_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert _FIXTURE.exists(), "combine_contract/two_reducers_candidate.url4 moved — update the bind"
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == two_reducers_url4()
