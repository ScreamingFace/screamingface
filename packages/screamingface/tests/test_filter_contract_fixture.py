"""Drift guard for the engine-side filter-then-model fixture (OME-1289, unit 10S, FL#8).

The Engine's tests run the SDK-compiled Candidate in
``apps/screamingface-engine/tests/unit/data/combine_contract/filter_pipeline_candidate.url4``
verbatim (its own tests need no SDK). This test keeps that data file byte-identical to what the SDK
compiles today, so a compiler change that is not mirrored in the fixture fails HERE.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_filter_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_FIXTURE = COMBINE_CONTRACT / "filter_pipeline_candidate.url4"


def filter_pipeline_url4() -> str:
    """Four members, a confidence filter, then a writer that sees only the members that pass."""

    recipe = sf.Pipeline(
        [
            sf.Fusion(
                ["prov/alpha", "prov/beta", "prov/gamma", "prov/delta"],
                synthesizer=sf.Filter(where=sf.signal("field:confidence") >= 0.6),
            ),
            "prov/writer",
        ]
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def write_fixture() -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    _FIXTURE.write_text(filter_pipeline_url4(), encoding="utf-8")


@requires_engine_app
def test_engine_filter_pipeline_fixture_matches_the_sdk_compiler() -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert ENGINE_APP.exists()
    assert _FIXTURE.exists(), "combine_contract/filter_pipeline_candidate.url4 is missing"
    assert _FIXTURE.read_text(encoding="utf-8").removesuffix("\n") == filter_pipeline_url4()
