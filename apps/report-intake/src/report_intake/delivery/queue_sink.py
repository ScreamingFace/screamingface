"""`QueueSink` — v1's adapter, and the reason this service needs no tracker credential yet.

**The `reports` table is the queue.** Marking the row `queued` and letting an agent file it
through MCP during triage is not a placeholder for `LinearSink`; it is the shape spec §9 settled
on for v1, and it is what keeps a Linear API token out of this service's environment, out of its
pod, and out of the threat model entirely.

`LinearSink` now exists beside this adapter (`linear_sink.py`), and this one is still the
default and still the one every deployment runs: selecting the other costs an operator a
credential and a decision CLAUDE.md rule 9 governs, which `OME-976` has not yet amended. Nothing
about that file changes what this one is for.

No ticket id comes back, which spec §2.2's success shape already models: `state` is `queued` and
`ticket` is null. A caller that needed an id to exist synchronously would be asking for
persist-after-deliver, which is prohibited.
"""

from __future__ import annotations

import logging

from .ports import Queued, SinkResult, TicketContent

logger = logging.getLogger(__name__)


class QueueSink:
    async def deliver(self, content: TicketContent) -> SinkResult:
        """Record that the report is ready to file, and answer `queued`.

        Never raises. There is no remote call to fail, so a `QueueSink` outage is not a thing that
        exists — which is exactly why v1 ships it: every report reaches a terminal delivery state
        on its first attempt, and the retry machinery `OME-1010` adds is there for the sink that
        comes after this one.

        The log line carries `title`, not the body: it is one line by construction (the renderer
        collapses whitespace into it), so it cannot break the log record apart, and it is the
        envelope material a triager greps for.
        """
        logger.info("report %s is queued for triage: %s", content.ref, content.title)
        return Queued()
