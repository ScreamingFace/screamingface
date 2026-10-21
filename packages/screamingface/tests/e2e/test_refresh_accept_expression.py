"""A golden refresh frees the expression hash only when the owner declares it (OME-1692).

STORY: as a dev whose protocol change re-rendered every board's expression without moving a
model-call byte, I refresh the goldens from the committed snapshots with
``--accept-expression``; the refresh still refuses if any status, counter, revision or score
moved, and without the flag it refuses the moved hash as before.
"""

from __future__ import annotations

import argparse

import pytest
from fixtures.slice_snapshot import _REFRESH_PINNED_KEYS, _refuse_pinned_drift

_COMMITTED = {
    "revision": "r1",
    "expression_sha": "old",
    "case_statuses": {"1": "scored"},
    "case_count": 1,
    "gradeable_count": 1,
    "final_score": "0.5",
}


def _args(*, accept_expression: bool) -> argparse.Namespace:
    return argparse.Namespace(board="toy", accept_expression=accept_expression)


def test_without_the_flag_a_moved_expression_is_refused() -> None:
    replayed = {**_COMMITTED, "expression_sha": "new"}

    with pytest.raises(SystemExit, match="replayed expression_sha differs"):
        _refuse_pinned_drift(_args(accept_expression=False), _COMMITTED, replayed)


def test_the_flag_frees_the_expression_hash_alone() -> None:
    replayed = {**_COMMITTED, "expression_sha": "new"}

    _refuse_pinned_drift(_args(accept_expression=True), _COMMITTED, replayed)


@pytest.mark.parametrize("key", [key for key in _REFRESH_PINNED_KEYS if key != "expression_sha"])
def test_the_flag_never_frees_an_outcome_fact(key: str) -> None:
    # INVARIANT: an intended expression change may not smuggle in a drifted outcome.
    replayed = {**_COMMITTED, "expression_sha": "new", key: "drifted"}

    with pytest.raises(SystemExit, match=f"replayed {key} differs"):
        _refuse_pinned_drift(_args(accept_expression=True), _COMMITTED, replayed)
