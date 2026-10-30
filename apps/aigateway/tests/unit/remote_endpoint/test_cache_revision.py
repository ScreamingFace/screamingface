"""A configured endpoint's cache-key revision travels with every export of the shared cache.

# FEATURE: hosted BYOM Unit 1 — rows a configured endpoint fills leave the gateway through the
# community pages and the cache snapshots, and each export carries the map of revisions its keys
# were computed under.
# INVARIANT: the revision the projection puts into a key is the one the gateway reports, so a
# gateway keyed under another remote-endpoint revision refuses those rows rather than loading
# rows that never hit.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from aigateway.core.request_cache.revisions import active_cache_revisions
from aigateway.core.request_cache.snapshot_export import CacheSnapshotExporter
from aigateway.core.request_cache.sqlite_loader import PageRejected, check_revisions
from aigateway.plugins.remote_endpoint.global_cache import (
    GLOBAL_CACHE_ADAPTER_REVISION,
    project_global_cache_request,
)

from .conftest import Harness, chat, chat_body, put_key, tenant_headers
from .fixtures import ACCOUNT_A, ENDPOINT_A, two_endpoint_document

# WHY a literal: the name is written into every page header and manifest, so renaming it is a
# change of the export contract, not a refactor.
REVISION_NAME = "remote_endpoint_adapter"
OLDER = "remote-endpoint-global-cache-2026-09"


def test_the_gateway_reports_the_revision_its_keys_embed() -> None:
    projected = project_global_cache_request(chat_body(ENDPOINT_A))

    assert isinstance(projected, dict)
    assert active_cache_revisions()[REVISION_NAME] == projected["provider_adapter_revision"]


def test_a_page_holding_an_endpoint_row_names_the_endpoint_revision(byom: Harness) -> None:
    byom.monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, "sk-alice-on-a-revision-0001").status_code
        assert chat(client, ACCOUNT_A, ENDPOINT_A).status_code == 200
        page = client.get("/v1/cache/entries", headers=tenant_headers(ACCOUNT_A))

    assert page.status_code == 200, page.text
    header, *rows, _ = [json.loads(line) for line in page.text.splitlines()]
    assert [row["provider"] for row in rows] == [ENDPOINT_A]
    assert header["revisions"][REVISION_NAME] == GLOBAL_CACHE_ADAPTER_REVISION


class _NoRows:
    """The COPY connection of an empty table: the manifest is built all the same."""

    async def copy_from_query(
        self,
        query: str,
        *,
        output: Callable[[bytes], Awaitable[None]],
        timeout: float | None = None,
    ) -> str:
        del query, output, timeout
        return "COPY 0"

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_a_snapshot_manifest_names_the_endpoint_revision(tmp_path: Path) -> None:
    async def connect() -> _NoRows:
        return _NoRows()

    export = await CacheSnapshotExporter(connect, spool_dir=str(tmp_path)).export()

    manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
    assert manifest["revisions"][REVISION_NAME] == GLOBAL_CACHE_ADAPTER_REVISION


def test_a_page_keyed_under_another_endpoint_revision_is_refused() -> None:
    local = active_cache_revisions()
    hosted = {**local, REVISION_NAME: OLDER}

    with pytest.raises(PageRejected) as refused:
        check_revisions(hosted, local)

    assert refused.value.reason == "revision_mismatch"
    assert REVISION_NAME in str(refused.value)
