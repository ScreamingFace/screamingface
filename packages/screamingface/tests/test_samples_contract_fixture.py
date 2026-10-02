"""Drift guard for the engine-side samples fixture (OME-1289, SM-4 engine half).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/samples_vote_candidate.url4`` verbatim
(its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_samples_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _reducer_fixtures import FixtureVote, _entry

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog
from screamingface.reducer import Reducer

# parents[3] = the monorepo root (tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[3] / "apps" / "screamingface-engine"
_FIXTURE = (
    _ENGINE_APP / "tests" / "unit" / "data" / "combine_contract" / "samples_vote_candidate.url4"
)

# The Engine's real v1 ids, the four a FixtureVote pins.
_ENGINE_OPERATORS = {
    "extract": ("last_number",),
    "normalize": ("numeric",),
    "reduce": ("mode",),
    "select": ("first_holder",),
}


def _catalog() -> _OperatorCatalog:
    return decode_operator_catalog(
        {
            "object": "list",
            "data": [
                _entry(name, 1, stage)
                for stage, names in _ENGINE_OPERATORS.items()
                for name in names
            ],
        }
    )


def _samples_url4(synthesizer: Reducer) -> str:
    recipe = sf.Fusion(sf.samples("prov/member-a", 5, temperature=0.7), synthesizer=synthesizer)
    return compile_candidate(recipe, operators=_catalog()).url4


def samples_vote_url4() -> str:
    return _samples_url4(FixtureVote())


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(samples_vote_url4(), encoding="utf-8")


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_engine_samples_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert _FIXTURE.exists(), "combine_contract/samples_vote_candidate.url4 moved — update the bind"
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == samples_vote_url4()


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric")),
        sf.Vote(extract="last_number", normalize="numeric"),
    ],
    ids=["reduce-plurality", "vote"],
)
def test_block_form_samples_vote_compiles_to_the_engine_fixture(synthesizer: Reducer) -> None:
    """A block and a named vote compile to the engine fixture byte for byte,
    so the Engine's samples world tests run the block form too (BK#12 engine half).
    """

    url4 = _samples_url4(synthesizer)

    assert url4 == samples_vote_url4()
    if _ENGINE_APP.exists():
        assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == url4
