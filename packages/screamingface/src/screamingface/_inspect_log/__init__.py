"""One-way export of a completed Report into inspect's `.eval` log format.

FEATURE (OME-1117): researchers in the inspect ecosystem open our runs in the
tooling they already use. The mapping (`payload`) is pure and dependency-free;
only the writer (`write`) touches `inspect_ai`, behind the `inspect` extra.
"""

from screamingface._inspect_log.write import write_inspect_log

__all__ = ["write_inspect_log"]
