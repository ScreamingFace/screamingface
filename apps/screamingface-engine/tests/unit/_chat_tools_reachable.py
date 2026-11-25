"""Reach the tool code of the chat route in a test.

WHY: tool calls are turned off at the boundary of POST /v1/chat/completions
(rest/chat_body.py::_tool_use; prd/tool-calls.md section 0, owner decision of 2026-11-24). The
tool code behind that check stays. The tests of that code keep it correct for the time when tool
calls are on again, so they run with the boundary check removed.

A test module gets this with one import:

    from _chat_tools_reachable import tools_reachable  # noqa: F401

AIDEV-NOTE: this is a test seam only. No setting removes the check in a deployment
(tests/unit/test_chat_completions_tools_off.py pins that). Do not import it in a test of the
refusal.
"""

from __future__ import annotations

import pytest

from screamingface_engine.rest import chat_body


@pytest.fixture(autouse=True)
def tools_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the fixed tool refusal for each test of the importing module."""
    monkeypatch.setattr(chat_body, "_tool_use", lambda request: None)
