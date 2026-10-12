"""The case digest of one run: the fingerprint a board compares on a replay (E14 B5, Q29, §7).

FEATURE: OME-1307 — the SDK digests a run's graded Cases. The board stores the digest at submit,
and an exact replay must carry the same one, so the same headline score over other Cases is not an
exact replay.
INVARIANT: the same Cases always give the same digest, in any order. The entry format must not
change between SDK versions: a score's stored digest must match a replay made by a later SDK.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from screamingface.case_result import CaseResult


def case_digest(cases: Sequence[CaseResult]) -> str:
    """The sha256 hex (64 lower-case characters) of the sorted `[case_id, status, score]` entries.

    WHY an explicit None check and not `or`: a score of 0.0 is a real grade and must not read as
    "no grade", which would make it the same entry as a Case that was never graded.
    """
    entries = sorted(
        json.dumps(
            [case.case_id, case.status, None if case.grade is None else case.grade.score],
            separators=(",", ":"),
        )
        for case in cases
    )
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()
