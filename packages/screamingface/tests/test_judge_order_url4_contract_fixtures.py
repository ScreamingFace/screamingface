"""Drift guard for the engine-side SDK-compiled judge-order fixture (E4b unit 5, JO#9/JO#12).

The Engine's ``test_sdk_judge_order_contracts.py`` runs this url4 file verbatim; this file keeps it
byte-identical to what the SDK compiles today, like ``test_quorum_url4_contract_fixtures.py``.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_judge_order_url4_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate


def judge_order_min_url4() -> str:
    """S11 min: three members; the judge scores the factual errors, and the lowest score wins."""

    recipe = (
        sx.Fanout(["prov/alpha", "prov/beta", "prov/gamma"])
        >> sx.Judge("prov/judge", rubric="Count the factual errors.")
        >> sx.ArgMin("score:judge")
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "judge_order_min_candidate.url4": judge_order_min_url4,
}


def write_fixture(name: str) -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name](), encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", BUILDERS)
def test_judge_order_fixture_matches_the_sdk_compiler(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
