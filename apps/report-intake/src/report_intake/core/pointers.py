"""RFC 6901 JSON pointers, in one place.

Three modules build pointers into a client-supplied document — the truncator, the schema
violation reporter, and the classifier — and each of them names a node a client chose the key
for. Escaping is the whole reason this is shared: without it a key spelled `a/b` produces a
pointer that reads as two segments, so the pointer a client is shown (or a log records) is not
the node that was actually found.
"""

from __future__ import annotations


def escape_pointer(segment: str) -> str:
    """One pointer segment, with RFC 6901's two reserved characters escaped."""
    return segment.replace("~", "~0").replace("/", "~1")
