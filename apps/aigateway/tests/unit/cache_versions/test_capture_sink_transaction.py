"""The capture sink writes the prompt row and the capture row in ONE transaction (OME-1307).

FEATURE: OME-1307 (E14) - one traced call is one commit, so it waits for one fsync, not two.

INVARIANT: the pair is all-or-nothing. A prompt row without its capture row is useless to a
freeze, so when the capture insert fails, no prompt row for the key remains.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.capture_store import TortoiseCaptureSink
from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.cache_versions.ports import CaptureRecord

_KEY_HASH = "d" * 64


def _record() -> CaptureRecord:
    return CaptureRecord(
        account_id="acct",
        trace_id="b8" * 16,
        outcome="stored",
        key_hash=_KEY_HASH,
        request_material='{"prompt":"one transaction"}',
        response_json=None,
    )


def test_failed_capture_insert_leaves_no_prompt_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("capture insert failed")

    monkeypatch.setattr(CacheCaptureEntry, "create", _boom)

    async def _record_and_count() -> tuple[bool, int]:
        raised = False
        try:
            await TortoiseCaptureSink().record(_record())
        except RuntimeError:
            raised = True
        return raised, await RequestCachePrompt.filter(key_hash=_KEY_HASH).count()

    portal: Any = client.portal
    raised, prompt_rows = portal.call(_record_and_count)

    assert raised, "the sink may raise; the route helper owns the never-raise rule"
    assert prompt_rows == 0, "the pair is all-or-nothing: no prompt row without its capture row"


def test_successful_record_writes_both_rows(client: TestClient) -> None:
    async def _record_and_count() -> tuple[int, int]:
        await TortoiseCaptureSink().record(_record())
        return (
            await RequestCachePrompt.filter(key_hash=_KEY_HASH).count(),
            await CacheCaptureEntry.filter(key_hash=_KEY_HASH).count(),
        )

    portal: Any = client.portal
    prompt_rows, capture_rows = portal.call(_record_and_count)

    assert (prompt_rows, capture_rows) == (1, 1)
