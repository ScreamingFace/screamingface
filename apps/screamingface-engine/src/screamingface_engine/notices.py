"""Advisory frames the control plane says to an attached client about its own run.

A notice is not a nack and not an error: the request it comments on was accepted and is being
honoured. It exists because something the caller stated was DROPPED — a re-attach's cache policy
that first-attach-wins ignored, a frame declaration that the request header overrode — and a
dropped declaration nobody is told about is indistinguishable from a bug in the gateway.

TWO EMITTERS, ONE VOICE. The WS bridge raises the first case and the REST route the second, and
they are asking the client to answer the same question — *what did I ask for, and what actually
applies?* — so the frame and its attribute names are built here rather than twice. A client that
had to learn two spellings of "cache.effective" depending on which carrier lost would be reading
the noise, not the signal.

WHY THIS IS A SHARED LEAF (`.claude/scripts/check_layering.py`): it names the wire protocol and
nothing else — no FastAPI, no broker, no engine — so it belongs to neither half of the
distribution and couples nothing to either. Its importers today are both control-plane modules;
that is a fact about who needs it, not about what it depends on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from url4.streaming.protocol import CachePolicy, LogData, LogEvent, source_for

Clock = Callable[[], datetime]

LogAttributes = dict[str, str | int | float | bool | None]

NOT_STATED = "not stated"
"""How an absent policy renders as a log attribute.

Its own token rather than an empty object, because "did not declare" and "declared an all-unset
policy" are different statements — and a notice that collapsed them could not answer why a
declaration was refused."""


def warn(topic: str, clock: Clock, message: str, attributes: LogAttributes) -> LogEvent:
    """Build a ``warn`` ``LogEvent`` for ``topic``'s attached client — advisory, never a nack.

    ``LogData.at`` derives the OTel SeverityNumber from the level, so the pair cannot disagree.
    """
    return LogEvent(
        id=uuid4().hex,
        source=source_for(topic),
        subject=topic,
        time=clock(),
        data=LogData.at("WARN", message, attributes),
    )


def rendered(policy: CachePolicy | None) -> str:
    """A cache intent as a log-attribute value; :data:`NOT_STATED` when there is none."""
    return NOT_STATED if policy is None else policy.model_dump_json(exclude_none=True)


__all__ = ["NOT_STATED", "Clock", "LogAttributes", "rendered", "warn"]
