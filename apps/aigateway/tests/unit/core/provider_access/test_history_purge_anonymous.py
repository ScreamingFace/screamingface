"""The anonymous account in `--all`: live without an `accounts` row (OME-1138 Stage E, E5b).

# FEATURE: Stage E history cleanup, spec C1/C4 — in `auth_mode=disabled` the caller is the
# anonymous account, an unsaved account whose row appears only when a Connection or a pair marker is
# first written. A Profile-only install therefore holds documents and blobs under its id with no
# row, and `--all` (which lists accounts from their rows) must not read them as a deleted account's.
# INVARIANT (C4): such an account is reported skipped (`anonymous_account_unmaterialised`), so the
# run is refused, nothing of it is swept, and the legacy global row that lists it stays.
"""

from __future__ import annotations

from typing import Any

import pytest
from history_purge_probes import (
    LEGACY_INDEX_ROW,
    PurgeHarness,
    address,
    index_row,
    profile,
)

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID

ANONYMOUS = str(ANONYMOUS_ACCOUNT_ID)
REASON = "anonymous_account_unmaterialised"


@pytest.fixture
def h(client: Any, credential_blobs: Any) -> PurgeHarness:
    return PurgeHarness(client, credential_blobs)


def skips(report: Any) -> dict[str, str]:
    # WHY skips only: the fixture app holds an account of its own, which the run also reports.
    return {result.account_id: result.skipped for result in report.accounts if result.skipped}


def test_its_own_index_row_and_blobs_are_kept_and_the_run_refused(h: PurgeHarness) -> None:
    h.document(ANONYMOUS)
    blob = h.blob(address(ANONYMOUS, "default"))
    before = h.rows()
    assert index_row(ANONYMOUS) in before

    report = h.purge()

    assert h.rows() == before
    assert skips(report) == {ANONYMOUS: REASON}
    assert report.counts()["deleted_account_blobs"] == 0
    assert report.refused()
    assert blob in h.rows()


def test_a_document_in_the_legacy_global_row_keeps_that_row(h: PurgeHarness) -> None:
    h.legacy_documents(profile(ANONYMOUS))
    h.blob(address(ANONYMOUS, "default"))
    before = h.rows()

    report = h.purge()

    assert h.rows() == before
    assert LEGACY_INDEX_ROW in h.rows()
    assert skips(report) == {ANONYMOUS: REASON}
    assert report.legacy_index == "kept_listed_account_skipped"


def test_a_dry_run_reports_it_the_same_way(h: PurgeHarness) -> None:
    h.blob(address(ANONYMOUS, "default"))

    report = h.purge("dry-run")

    assert skips(report) == {ANONYMOUS: REASON}
    assert report.counts()["deleted_account_blobs"] == 0


def test_without_any_of_its_rows_it_is_not_reported(h: PurgeHarness) -> None:
    h.new_account()

    report = h.purge()

    assert ANONYMOUS not in {result.account_id for result in report.accounts}
    assert skips(report) == {}
    assert not report.refused()
