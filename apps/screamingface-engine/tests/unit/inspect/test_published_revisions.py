# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The published boards' EXACT revisions — frozen as literals.

A board's revision is its exam identity: members' published scores hang off it, and
the snapshot store treats a revision's baked assets as immutable. Every revision
input so far (pins, protocol constants, the OME-1240 judge pins) is code an innocent
refactor can touch, and the uniqueness/moves tests cannot see a WHOLESALE shift —
a review probe moved all 17 revisions with a one-line change while 3575 tests
stayed green (2026-09-24). These literals make that failure loud.

When a revision here changes on purpose (a pin bump, a protocol revision bump),
updating the literal IS the review act — the diff line is the declaration that the
published exam moved.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.boards import imported_board  # noqa: E402

#: key → the exact published revision, as served on main (verified 2026-09-24).
_PUBLISHED_REVISIONS: dict[str, str] = {
    "gsm8k": "df52a7b257fe8701",
    "mmlu": "49ee9af05fb6e15f",
    "arc_easy": "b65db0c432a718aa",
    "arc_challenge": "a08708c1ab765cff",
    "commonsense_qa": "4a4e8e12ff7a112d",
    "paws": "82d6b39c271cbdd1",
    "boolq": "e1d1ca4f97ea32f0",
    "mmlu_pro": "41ebb1f731886df8",
    "winogrande": "22fd4c35111f2d7d",
    "race_h": "619493b3ea10bbb0",
    "aime24": "fe26f860bc661efe",
    "aime25": "94a6b9ead168a622",
    "musr": "6cfb64a1c68595cb",
    "wmdp_bio": "d2c264d42b33ce58",
    "wmdp_chem": "c1052f7956dd9bb6",
    "wmdp_cyber": "dbb68d47d68f4e09",
    "hellaswag": "b3f504a886222b6a",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_PUBLISHED_REVISIONS.items()))
def test_published_board_revision_is_byte_identical(key: str, revision: str) -> None:
    assert imported_board(key).benchmark.revision == revision
