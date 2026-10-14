"""Spec builders for the rank and concat tests (OME-1289 E4a, unit 10).

Test-only. Both builders return a spec over the built-in operators, shaped like the SDK's
``sf.Rank`` and ``sf.Concat`` (spec 1.2): rank scores by a judge reply or by a numeric field, and
concat joins every member text.
"""

from __future__ import annotations

from typing import Any, Literal

from combine_support import vote_spec

DEFAULT_SEPARATOR = "\n\n---\n\n"


def rank_spec(member_count: int, k: int, by: Literal["judge", "field"] = "judge") -> dict[str, Any]:
    """A rank spec: top ``k`` by a judge's scores, or by the numeric ``score`` field."""
    if by == "judge":
        return vote_spec(
            member_count,
            reducer="rank",
            extract=None,
            normalize=None,
            reduce={"op": "scores@1", "args": {"source": "judge"}},
            select={"op": "top_k@1", "args": {"k": k}},
        )
    return vote_spec(
        member_count,
        reducer="rank",
        extract={"op": "json_field@1", "args": {"path": "score"}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "scores@1", "args": {"source": "values"}},
        select={"op": "top_k@1", "args": {"k": k}},
    )


def concat_spec(
    member_count: int, *, separator: str = DEFAULT_SEPARATOR, label: bool = True
) -> dict[str, Any]:
    """A concat spec: every member text joined in author order."""
    return vote_spec(
        member_count,
        reducer="concat",
        extract=None,
        normalize=None,
        reduce={"op": "join@1", "args": {"separator": separator, "label": label}},
        select={"op": "all@1", "args": {}},
    )


__all__ = ["DEFAULT_SEPARATOR", "concat_spec", "rank_spec"]
