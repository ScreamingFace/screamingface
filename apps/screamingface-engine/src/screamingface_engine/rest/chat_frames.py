"""What the route reads from the topic of one chat run.

The route scans the topic for three frames: the terminal frame, the last result frame, and the
root cost frame (contracts C9). A wait that ends before a terminal frame is a ``WaitEnd``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from url4.streaming.protocol import ResultEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData


@dataclass(frozen=True)
class RunFrames:
    """The frames of one finished chat run: terminal frame, last result frame, root cost frame."""

    terminated: TerminatedEvent
    result: ResultEvent | None
    root_cost: CostUsageData | None


class WaitEnd(enum.Enum):
    """Why a wait ended with no terminal frame."""

    TIMEOUT = "timeout"
    GONE = "gone"
    DRAINED = "drained"


__all__ = ["RunFrames", "WaitEnd"]
