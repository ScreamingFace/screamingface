"""Codex states image/file input tokens as unknown (OME-1546).

FEATURE: image/file token accounting, gateway half.
WHY unknown: the Responses `usage.input_tokens_details` carries only `cached_tokens` and
`cache_write_tokens` (observed live 2026-10-20 on gpt-6-astra) — no per-modality breakdown.
INVARIANT: unknown is ``None``, never ``0``; totals are unchanged.
"""

from __future__ import annotations

import json

from aigateway.plugins.codex_provider.chat_handler import _model_response_from_sse


def _sse(usage: dict) -> str:
    event = {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "model": "gpt-6-astra",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "4827"}]}],
            "usage": usage,
        },
    }
    return f"event: response.completed\ndata: {json.dumps(event)}\n\n"


def test_image_and_file_tokens_are_an_explicit_unknown_and_totals_hold() -> None:
    # The live raw usage shape of a Codex image call (prompt 81 = text 8 + image 73).
    response = _model_response_from_sse(
        _sse(
            {
                "input_tokens": 81,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": 5,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 86,
            }
        ),
        "gpt-6-astra",
    )
    usage = response.model_dump()["usage"]
    assert usage["prompt_tokens_details"]["image_and_file_tokens"] is None
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == (
        81,
        5,
        86,
    )
