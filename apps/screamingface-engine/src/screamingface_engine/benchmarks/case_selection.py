"""Serve the public cases as a URL4 data reference (spec R3).

The case set is data, not a computation: the expression reads it as ``/…/cases*(…)`` and
selects with ``;iteration.slice``. URL4 parses the JSON array into rows (spec §5.3.7) and owns
slicing and indexing.
"""

from collections.abc import Callable

from url4.peer.server import Url4Node

CASES_MEDIA_TYPE = "application/json"


def install_cases(node: Url4Node, route: str, provider: Callable[[], str]) -> None:
    """Register the cases route as a data route; a second install of the same route is a no-op.

    WHY idempotent: local mode installs one node for many runs.
    """

    if not node.has_data(route):
        node.data(route, provider, media_type=CASES_MEDIA_TYPE)
