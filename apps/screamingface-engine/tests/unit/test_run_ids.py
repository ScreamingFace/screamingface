"""E5 P1 spec D5: `run_` + a random UUID in hex.

FEATURE: first-class Runs (OME-1785).
"""

from __future__ import annotations

from screamingface_engine.runs.ids import RUN_ID_PATTERN, new_run_id


def test_the_id_is_run_and_32_hex_digits() -> None:
    assert RUN_ID_PATTERN.fullmatch(new_run_id())


def test_ids_are_distinct() -> None:
    assert len({new_run_id() for _ in range(1000)}) == 1000


def test_the_pattern_refuses_anything_else() -> None:
    valid = "run_" + "a" * 32

    for wrong in ["run_" + "A" * 32, "run_" + "a" * 31, "a" * 32, valid + "\n"]:
        assert not RUN_ID_PATTERN.fullmatch(wrong), wrong


def test_the_id_pattern_is_anchored_for_every_matching_mode() -> None:
    """WHY: a route may use it with `match`, `search` or as a Pydantic `pattern` (a search)."""
    valid = "run_" + "a" * 32

    assert RUN_ID_PATTERN.search("x" + valid) is None
    assert RUN_ID_PATTERN.match(valid + "x") is None
    assert RUN_ID_PATTERN.search(valid + "/../x") is None
