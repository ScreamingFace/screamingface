"""CV-28: an operator prune of orphan prompts keeps every prompt that a capture row still names.

FEATURE: OME-1307 (E14) - the freeze reads a prompt long after the call. A manual cleanup must not
delete a prompt that a capture row (the run index) or a live cache row still references (CV-D13).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aigateway.core.cache_versions.maintenance import (
    PRUNE_ORPHAN_PROMPTS_SQL,
    prune_orphan_prompts,
)
from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.request_cache.models.request_cache_entry import RequestCacheEntry

_P1, _P2, _P3 = "1" * 64, "2" * 64, "3" * 64
_DEPLOYMENT_DOC = Path(__file__).resolve().parents[3] / "DEPLOYMENT.md"


def test_operator_prune_keeps_prompts_referenced_by_run_index(client: TestClient) -> None:
    async def _arrange_and_prune() -> tuple[int, set[str]]:
        for key_hash in (_P1, _P2, _P3):
            await RequestCachePrompt.create(key_hash=key_hash, request_json="{}")
        # P1: named by a capture row and by no live row.
        await CacheCaptureEntry.create(
            account_id="acct", trace_id="e5" * 16, key_hash=_P1, outcome="stored"
        )
        # P3: named by a live cache row and by no capture row.
        await RequestCacheEntry.create(
            key_hash=_P3,
            prompt_hash=_P3,
            provider="anthropic",
            model="claude-haiku-4-5",
            response_json="{}",
            response_size_bytes=2,
        )
        deleted = await prune_orphan_prompts()
        remaining = {prompt.key_hash for prompt in await RequestCachePrompt.all()}
        return deleted, remaining

    portal: Any = client.portal
    deleted, remaining = portal.call(_arrange_and_prune)

    assert remaining == {_P1, _P3}, "P2 has no reference and goes; P1 and P3 stay"
    assert deleted == 1


def test_deployment_doc_shows_the_prune_statement_verbatim() -> None:
    assert PRUNE_ORPHAN_PROMPTS_SQL in _DEPLOYMENT_DOC.read_text(encoding="utf-8")
