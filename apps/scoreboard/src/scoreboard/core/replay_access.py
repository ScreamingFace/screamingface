"""Who may read or replay a reported result (RP-H4, RP-E2, RP-E3).

FEATURE: OME-1307 (E14). SB-submit uses it for rule R of a replay claim; SB-grants reuses it.
INVARIANT: pure. Standard library only.
"""

from __future__ import annotations

from typing import Literal

Access = Literal["allow", "not_found", "withdrawn"]


def is_owner(caller: str | None, reporter: str | None, *, identity_verified: bool) -> bool:
    """Both names set, the identity verified, and the names equal (strip, casefold)."""
    if not identity_verified or caller is None or reporter is None:
        return False
    return caller.strip().casefold() == reporter.strip().casefold()


def replay_access(
    *,
    board_visibility: str | None,
    redistributable: bool,
    reporter: str | None,
    publication_state: str | None,
    caller: str | None,
    identity_verified: bool,
) -> Access:
    """RP-H4, RP-E2, RP-E3, in this order: owner -> allow; private board or not redistributable
    -> not_found; withdrawn -> withdrawn; else allow.

    INVARIANT: not_found is checked before withdrawn, so a private or gated result never reveals
    that it exists (OME-894, routes/scores.py).
    """
    if is_owner(caller, reporter, identity_verified=identity_verified):
        return "allow"
    if board_visibility != "public" or not redistributable:
        return "not_found"
    return "withdrawn" if publication_state == "withdrawn" else "allow"
