"""The iteration directive types the AST embeds (``;iteration.*``, spec §5.3.6).

Split out of :mod:`url4.core.nodes` (module-size cap, ``OME-1539``) and re-exported
there unchanged: import them from ``url4.core.nodes``. Standard library only, so the
node module stays a leaf apart from this one import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The closed set of per-row failure policies (§5.3.6). The surface validator
# (core._annotations) derives its accepted set from this Literal, so the wire
# grammar, the Python builders, and MapNode's dispatch cannot drift apart — and
# an unknown policy is unrepresentable on the dataclass rather than caught (or
# missed) by an == chain at resolve time.
OnErrorPolicy = Literal["skip", "fail", "collect"]


@dataclass(frozen=True)
class IterationDirectives:
    """Execution annotations for collection iteration (``;iteration.*``, §5.3.6).

    Pure data, so it lives with the AST rather than in the parser — an
    :class:`~url4.core.nodes.Iteration` embeds it, and the parser imports it back.
    ``slice`` is the half-open ``[start, end)`` element range.
    """

    concurrency: int | None = None
    on_error: OnErrorPolicy = "collect"
    slice: tuple[int, int] | None = None
    fmt_result: str | None = None


# The pre-0.2 directive name; importable for one more minor version.
ForeachDirectives = IterationDirectives

__all__ = ["ForeachDirectives", "IterationDirectives", "OnErrorPolicy"]
