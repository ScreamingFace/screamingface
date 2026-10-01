"""The binding-name pattern equals the one the SDK pins (OME-1289 E4a, unit 3).

INVARIANT defended: the engine attributes exactly the bindings the Client projects as operations.
Both packages read ``data/combine_contract/binding_names.json``; a drift in either pattern fails
here (or in the SDK twin) instead of silently dropping a ``judge_N`` or ``writer_N`` operation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks import operation_outputs

_FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "combine_contract" / "binding_names.json").read_text("utf-8")
)


def test_the_engine_pattern_is_the_fixture_pattern() -> None:
    assert operation_outputs._BINDING.pattern == _FIXTURE["pattern"]


@pytest.mark.parametrize("name", _FIXTURE["accept"])
def test_every_accepted_name_matches(name: str) -> None:
    assert operation_outputs._BINDING.match(name) is not None


@pytest.mark.parametrize("name", _FIXTURE["reject"])
def test_every_rejected_name_does_not_match(name: str) -> None:
    assert operation_outputs._BINDING.match(name) is None
