"""Nonblocking setup disclosure; never invoked by import, constructors or evaluate."""

import sys

from screamingface._analytics.wiring import origin

NOTICE = (
    "Optional ScreamingFace analytics is off. Share evaluation/submission starts and outcomes, "
    "coarse timing, SDK version and local/hosted mode using random installation/session IDs. "
    "No prompts, responses, scores, credentials or email. Raw events are retained up to 90 days. "
    "Allow: sf.analytics.enable() · Decline: sf.analytics.disable(). "
    "Your choice is remembered; continuing without choosing leaves analytics off. "
    "Opting out or resetting your ID does not delete past events."
)
_shown = False


def offer() -> None:
    global _shown
    from screamingface import analytics

    if _shown or analytics._disabled() or origin() == "colab":
        return
    if not sys.stdin.isatty() and origin() != "local_jupyter":
        return
    if analytics.status()["choice"] == "unknown":
        _shown = True
        # WHY: no input() or kernel wait. An explicit subsequent choice applies only
        # to future operations, and a dismissed notice remains off for this process.
        print(NOTICE)
