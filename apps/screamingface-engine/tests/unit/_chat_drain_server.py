"""The App of the stop-signal test (CC-39): no run ends, and each scheduled run prints one line.

Test-only. It is in tests/unit, next to `_chat_app`, so the server process needs only this one
directory on its path. The subprocess of tests/integration/test_chat_drain_signal.py imports
this module through PYTHONPATH and gives `create` to `cli._run_server` as the App factory.
"""

from __future__ import annotations

from typing import Any

from _chat_app import chat_app

SCHEDULED_MARK = "CHAT-RUN-SCHEDULED"


def create() -> Any:
    """A chat App whose runs never end, so each request waits until the drain or the time limit."""
    ca = chat_app(None, chat_max_wait_s=120.0, chat_keepalive_s=0.2)
    schedule = ca.runner.schedule

    async def _marked(*args: Any, **kwargs: Any) -> str:
        scheduled = await schedule(*args, **kwargs)
        # WHY: the test sends the stop signal only after it reads this line, so the request is
        # past the schedule step and waits for its run.
        print(SCHEDULED_MARK, flush=True)
        return scheduled

    setattr(ca.runner, "schedule", _marked)  # noqa: B010 (an instance override of a test fake)
    return ca.app
