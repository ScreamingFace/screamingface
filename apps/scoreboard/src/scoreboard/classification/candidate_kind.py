"""Composition-type classification for leaderboard rows (OME-1852).

The public Pareto chart draws a single model as a circle and a fusion as a square (owner
decision, Option A). That shape channel must never guess: a row's verdict is read only from
the Client's own declaration in `metadata.candidate_kind`, never inferred from `spec_id` or
`ran_with_providers` length — both already rejected as unreliable fusion/solo tests (see the
`spec_id`/`ran_with_providers` column comments in `apps/scoreboard/portal/main.js`,
OME-772/OME-769). Anything this module cannot positively confirm is "model" or "fusion" reads
as "unknown" — never silently promoted to either shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

# WHY only these two are classified here: the Client's compiler
# (`packages/screamingface/src/screamingface/_evaluation/candidate.py`'s `_CandidateKind`) also
# emits "pipeline", "corrective_loop" and "self_corrective", but the chart draws exactly two
# shapes. A pipeline is not a fusion, so it — and any future kind the compiler adds — reads as
# "unknown" rather than being guessed into either bucket.
CandidateKindVerdict = Literal["model", "fusion", "unknown"]


def classify_candidate_kind(metadata: Mapping[str, Any] | None) -> CandidateKindVerdict:
    """The verdict for one row's `metadata.candidate_kind`.

    Set by the Client at submission time
    (`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`'s `_submission`) —
    the only place this signal exists. `metadata` is free-form and client-supplied, so a
    non-string value, an absent key, or any string besides the two known kinds is untrustworthy
    or unrecognised input, not an error: it resolves to "unknown", never a guess.
    """
    candidate = (metadata or {}).get("candidate_kind")
    if candidate == "model":
        return "model"
    if candidate == "fusion":
        return "fusion"
    return "unknown"
