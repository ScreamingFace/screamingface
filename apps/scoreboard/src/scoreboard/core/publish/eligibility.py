"""Who may publish: the refusal rules of PB-E5 (erd 2.6, PRD publish-and-takedown).

FEATURE: OME-1307 (E14). INVARIANT: pure, standard library only. It takes values the caller read;
the caller owns the re-check of the board visibility before it acts on the answer.

Two callers ask this rule: the route, when it accepts the request (`publish_refusal`), and the
worker, when the job runs (`PublicationStore.revalidate_publishable`, which asks `board_refusal`
alone). The worker asks again because a request can wait for hours. A refusal by the worker makes
the row `failed` with `last_error` set to the code (`private_board` or `not_redistributable`). That
is not an integrity error, so the owner may publish again once the board qualifies.
"""

from __future__ import annotations

INTEGRITY_ERRORS = frozenset({"archive_mismatch", "archive_missing", "release_conflict"})


def board_refusal(*, public: bool, redistributable: bool) -> str | None:
    """The reason the BOARD forbids a public release, or None: private, then not redistributable.

    The worker asks only this: it has no version or row state to check (PB-E5).
    """
    checks = ((not public, "private_board"), (not redistributable, "not_redistributable"))
    return next((reason for refused, reason in checks if refused), None)


def publish_refusal(
    *,
    board_visibility: str | None,
    redistributable: bool,
    has_version: bool,
    state: str,
    last_error: str | None,
) -> str | None:
    """The reason a result may not be published, or None.

    In order: private board, not redistributable, no version, and a `failed` row whose last error
    is an integrity failure (PB-E5: the owner cannot retry it, OD-3).

    INVARIANT: an unknown visibility is refused like a private board (fail closed).
    """
    checks = (
        (not has_version, "no_cache_version"),
        (state == "failed" and last_error in INTEGRITY_ERRORS, "integrity_failure"),
    )
    return board_refusal(
        public=board_visibility == "public", redistributable=redistributable
    ) or next((reason for refused, reason in checks if refused), None)
