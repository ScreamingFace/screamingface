"""Drift guard for the engine-side weighted vote contract data (OME-1289, unit 7).

The Engine's tests read ``weighted_vote_specs.json`` from
``apps/screamingface-engine/tests/unit/data/combine_contract/`` and run each spec verbatim (they
never build a spec by hand). This test keeps the file equal to what the SDK compiles today.

Regenerate, from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_weighted_vote_contract_fixture as m; m.write_fixture()"
"""

from __future__ import annotations

import json
import sys

from _combine_contract import COMBINE_CONTRACT, engine_operators, read_contract, requires_engine_app
from _nodes import ReduceNode, VoteNode

import screamingface as sf
from screamingface._evaluation.combine_spec import combine_spec_text

_FIXTURE = "weighted_vote_specs.json"

# name -> weights (one per member, author order)
_WEIGHTS: dict[str, tuple[float, ...]] = {
    "weighted_5": (3, 3, 1, 1, 1),
    "weighted_2": (1, 2),
    "weighted_tie_3": (2, 1, 1),
    "weighted_holders_3": (1, 2, 2),
    "weighted_decimal_4": (0.1, 0.2, 0.3, 0.6),
    "weighted_decimal_reversed_4": (0.3, 0.2, 0.1, 0.6),
    "weighted_empty_4": (5, 1, 1, 1),
    # The largest weight the Engine accepts: sys.float_info.max / 256 (D-7).
    "weighted_cap_2": (sys.float_info.max / 256, sys.float_info.max / 256),
}


# name -> (reducer, member count): weights read from a named number on each Answer (unit 7, SR-1)
_SIGNAL_SPECS: dict[str, tuple[ReduceNode, int]] = {
    "weighted_signal_field_3": (
        ReduceNode(
            "weighted",
            extract=sf.Extract("field", path="answer", normalize="text"),
            weights=sf.signal("field:confidence"),
        ),
        3,
    ),
}


def weighted_vote_specs() -> dict[str, str]:
    operators = engine_operators()
    constant = {
        name: combine_spec_text(
            VoteNode(extract="last_number", normalize="numeric", weights=weights),
            member_count=len(weights),
            operators=operators,
        )
        for name, weights in _WEIGHTS.items()
    }
    signal = {
        name: combine_spec_text(reducer, member_count=count, operators=operators)
        for name, (reducer, count) in _SIGNAL_SPECS.items()
    }
    return {**constant, **signal}


def write_fixture() -> None:
    (COMBINE_CONTRACT / _FIXTURE).write_text(
        json.dumps(weighted_vote_specs(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@requires_engine_app
def test_engine_weighted_vote_fixture_matches_the_sdk_compiler() -> None:
    # WHY the file must exist: a present engine app with a missing fixture FAILS, not skips.
    assert (COMBINE_CONTRACT / _FIXTURE).exists(), f"combine_contract/{_FIXTURE} is missing"
    assert json.loads(read_contract(_FIXTURE)) == weighted_vote_specs()
