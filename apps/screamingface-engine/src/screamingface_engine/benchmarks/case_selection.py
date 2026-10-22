"""Serve the public cases as a URL4 data reference (spec R3).

The case set is data, not a computation: the expression reads it as ``/…/cases*(…)`` and
selects with ``;iteration.slice``. URL4 parses the JSON array into rows (spec §5.3.7) and owns
slicing and indexing.
"""

import json
from collections.abc import Callable

from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node

CASES_MEDIA_TYPE = "application/json"


def install_cases(node: Url4Node, route: str, provider: Callable[[], str]) -> None:
    """Register the cases route as a validated data route; a second install is a no-op.

    WHY idempotent: local mode installs one node for many runs.
    """

    if not node.has_data(route):
        node.data(route, validated_cases(provider), media_type=CASES_MEDIA_TYPE)


def validated_cases(provider: Callable[[], str]) -> Callable[[], str]:
    """The provider, refusing a booklet whose rows are not objects before any inference.

    INVARIANT: validation finishes before inference — a malformed booklet fails the run here,
    with no paid call. AIDEV-NOTE: a data route cannot see the run's selection, so the
    retired "at least N rows" check now lives in the aggregate, which refuses evaluations that
    do not match the selection. A prepared bundle holds exactly its declared Cases (its Case
    Digest is checked at image build), so a short booklet means a corrupt bundle.
    """

    def cases() -> str:
        raw = provider()
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("case rows must be one JSON array of objects")
        except (TypeError, ValueError) as exc:
            raise ResolutionError(
                "Invalid benchmark case selection", code="benchmark_contract_error", permanent=True
            ) from exc
        return raw

    return cases
