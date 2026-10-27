"""The purge journal across the `--all` phases (OME-1138 Stage E, E5b).

# FEATURE: Stage E history cleanup, spec C5 — `--apply` commits account by account, then the
# deleted-account sweep, then the legacy global index row; the journal is the record of a run that
# stops part-way, where no report reaches stdout.
# INVARIANT: every phase that committed has its line on disk before the next phase starts; the line
# carries kinds and counts only.
"""

from __future__ import annotations

import io
import json
from typing import Any
from uuid import uuid4

import pytest
from history_purge_probes import PurgeHarness, address, leaks_in

from aigateway.core.provider_access import history_purge


@pytest.fixture
def h(client: Any, credential_blobs: Any) -> PurgeHarness:
    return PurgeHarness(client, credential_blobs)


def test_a_committed_sweep_is_journaled_before_the_legacy_row_is_read(
    h: PurgeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    orphan = h.blob(address(str(uuid4()), uuid4()))
    journal = io.StringIO()

    async def fail(*_: Any, **__: Any) -> None:
        raise RuntimeError("the legacy phase failed")

    monkeypatch.setattr(history_purge, "purge_legacy_index", fail)

    with pytest.raises(RuntimeError):
        h.purge(journal=journal)

    assert orphan not in h.rows()
    lines = [json.loads(line) for line in journal.getvalue().splitlines()]
    assert lines[-1] == {
        "mode": "apply",
        "sweep": {
            "index_rows": 0,
            "deleted_account_blobs": 1,
            "kept_unrecognised_rows": 0,
            "kept_unproven_rows": 0,
        },
    }
    assert leaks_in(journal.getvalue()) == []
