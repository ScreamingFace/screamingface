"""The runtime half of the ``expand.at_most_one=true`` mark (contract C19).

FEATURE: a named ``;expand`` source that may hold at most one element. The form half (the
key, its placement and the refusals) is :mod:`url4.core.at_most_one`; this module turns the
parsed elements of a marked source into its payload. :class:`~url4.dag.nodes.ExpandNode`
calls it when its ``at_most_one`` flag is set.
"""

from __future__ import annotations

from url4.core.errors import CollectionError, ErrorCode
from url4.dag.node import NoElement, Payload


def at_most_one_payload(elements: list[str]) -> Payload:
    """Zero elements give :class:`NoElement`, one gives that element, two or more fail.

    WHY a plain ``str`` for one element: every consumer (the text gather, the broadcast
    merge, a code group's record) then treats it as a plain named source — ``name: value``,
    ``source_name: name``, the declared weight — with no per-consumer special case.
    """
    if len(elements) > 1:
        raise CollectionError(
            f"an at-most-one expansion resolved to {len(elements)} elements",
            code=ErrorCode.EXPANSION_TOO_MANY,
        )
    return elements[0] if elements else NoElement()
