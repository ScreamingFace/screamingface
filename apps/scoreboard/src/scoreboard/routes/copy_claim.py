"""The claim of the frozen copy of a Score at submit (OME-1947, contracts.md K5).

The submit route calls `ensure_copy_is_claimed` after the benchmark check and before the store.
The call is outside each database transaction. A result that is not in KEPT refuses the submit,
and nothing is stored.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import HTTPException, Request

from scoreboard.core.copy_claims import KEPT, ClaimResult, CopyClaims

logger = logging.getLogger(__name__)

# INVARIANT: the three messages are the exact text of contracts.md K5. The SDK shows them.
EXPIRED_MESSAGE = (
    "the pinned cache of this run expired: no score used it in its retention period. Run the "
    "evaluation again with capture=True to submit a reproducible score."
)
UNAVAILABLE_MESSAGE = (
    "the pinned cache of this run is not available: the run did not seal it, or this gateway "
    "does not hold it. Run the evaluation again and submit the new result."
)
CHECK_UNAVAILABLE_MESSAGE = "the pinned cache of this run could not be checked. Try again."
_RETRY_AFTER = {"Retry-After": "5"}

# WHY a table: one refusal for each result outside KEPT keeps the guard inside the lint limits.
_REFUSALS: dict[ClaimResult, tuple[int, str, str]] = {
    ClaimResult.EXPIRED: (422, "frozen_copy_expired", EXPIRED_MESSAGE),
    ClaimResult.NOT_SEALED: (422, "frozen_copy_unavailable", UNAVAILABLE_MESSAGE),
    ClaimResult.ABANDONED: (422, "frozen_copy_unavailable", UNAVAILABLE_MESSAGE),
    ClaimResult.NOT_FOUND: (422, "frozen_copy_unavailable", UNAVAILABLE_MESSAGE),
    ClaimResult.UNAVAILABLE: (503, "frozen_copy_check_unavailable", CHECK_UNAVAILABLE_MESSAGE),
}


def _claim_refusal(result: ClaimResult) -> HTTPException:
    status_code, code, message = _REFUSALS[result]
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers=_RETRY_AFTER if status_code == 503 else None,
    )


async def ensure_copy_is_claimed(request: Request, frozen_copy_id: str | None) -> None:
    """Claim the frozen copy of a submit, or refuse the submit.

    With no frozen copy, do nothing. With no claim client, log one WARNING record and accept.
    """
    if frozen_copy_id is None:
        return
    claims = cast("CopyClaims | None", request.app.state.copy_claims)
    if claims is None:
        # WHY accept: with no gateway URL the scoreboard works as before this release (C9).
        logger.warning("no gateway URL: no claim for frozen copy %s", frozen_copy_id)
        return
    result = await claims.claim(frozen_copy_id)
    if result not in KEPT:
        # INVARIANT: the record has the result and the copy id only, never the submitter email.
        logger.warning(
            "frozen copy claim refused: result=%s frozen_copy_id=%s", result.value, frozen_copy_id
        )
        raise _claim_refusal(result)
