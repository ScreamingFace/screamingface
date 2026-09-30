"""SC-14a — the pure replay-access rule (RP-H4, RP-E2, RP-E3).

FEATURE: OME-1307 (E14). INVARIANT under test: `not_found` is checked before `withdrawn`, so a
private or gated result never reveals that it exists (OME-894).
"""

from __future__ import annotations

from typing import Any

import pytest

from scoreboard.core.replay_access import Access, is_owner, replay_access

_OWNER = "Ana@X.org"


def _access(
    *,
    board_visibility: str = "public",
    redistributable: bool = True,
    reporter: str | None = _OWNER,
    publication_state: str | None = "private",
    caller: str | None = "bruno@y.org",
    identity_verified: bool = True,
) -> Access:
    return replay_access(
        board_visibility=board_visibility,
        redistributable=redistributable,
        reporter=reporter,
        publication_state=publication_state,
        caller=caller,
        identity_verified=identity_verified,
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"caller": "ana@x.org", "board_visibility": "private", "redistributable": False},
            "allow",
            id="owner-on-private",
        ),
        pytest.param({"board_visibility": "private"}, "not_found", id="non-owner-private"),
        pytest.param({"redistributable": False}, "not_found", id="non-owner-not-redistributable"),
        pytest.param({"publication_state": "withdrawn"}, "withdrawn", id="non-owner-withdrawn"),
        pytest.param(
            {"board_visibility": "private", "publication_state": "withdrawn"},
            "not_found",
            id="private-and-withdrawn",
        ),
        pytest.param(
            {"caller": "ana@x.org", "board_visibility": "private", "identity_verified": False},
            "not_found",
            id="unverified-identity-equal-to-reporter",
        ),
        pytest.param({}, "allow", id="public-redistributable-private-state"),
        pytest.param({"publication_state": "published"}, "allow", id="published"),
        pytest.param({"publication_state": None}, "allow", id="no-publication-row"),
    ],
)
def test_replay_access_order_owner_private_gated_withdrawn(
    overrides: dict[str, Any], expected: str
) -> None:
    assert _access(**overrides) == expected


def test_the_owner_may_replay_a_withdrawn_result() -> None:
    assert _access(caller="ANA@x.org ", publication_state="withdrawn") == "allow"


@pytest.mark.parametrize(
    ("caller", "reporter", "verified", "expected"),
    [
        ("ana@x.org", "ANA@x.org", True, True),
        (" ana@x.org ", "ana@x.org", True, True),
        ("ana@x.org", "ana@x.org", False, False),
        (None, "ana@x.org", True, False),
        ("ana@x.org", None, True, False),
        ("bruno@y.org", "ana@x.org", True, False),
    ],
)
def test_is_owner_needs_a_verified_identity_and_both_names(
    caller: str | None, reporter: str | None, verified: bool, expected: bool
) -> None:
    assert is_owner(caller, reporter, identity_verified=verified) is expected
