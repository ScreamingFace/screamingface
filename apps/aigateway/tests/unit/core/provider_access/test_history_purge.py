"""The purge of the retired Profile storage on SQLite: what goes, what stays, what skips (E5b).

# FEATURE: OME-1138 Stage E history cleanup, spec C1-C5 —
# `python -m aigateway.purge_profile_history` deletes every Profile index row and every
# provider-credential blob no Connection row addresses, one account at a time, and skips an account
# whole when it cannot prove what is addressed.
# INVARIANT (C2): a blob any Connection row of any status addresses stays, at the physical address
# its strategy resolves; so do `aigateway:jwt-secret` and every row outside a loaded provider's
# credential namespace.
# INVARIANT (C5): a dry run writes nothing; apply deletes exactly what the dry run reported; a
# second apply reports zero; the report and the journal carry account ids, kinds and counts only.
# WHY SQLite here: classification does not depend on the engine; the C3 fence is the PostgreSQL
# suite's (`tests/integration/test_history_purge_postgres.py`).
"""

from __future__ import annotations

import base64
import io
import json
import os
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from history_purge_probes import (
    ANTHROPIC,
    LEGACY_INDEX_ROW,
    PurgeHarness,
    address,
    index_row,
    leaks_in,
    profile,
    zero_counts,
)

from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.profile_models import ProfileIndex
from aigateway.core.provider_access.connection_locator import locator_credential_name
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

DELETION_KINDS = ("index_rows", "name_shaped_blobs", "uuid_shaped_blobs", "deleted_account_blobs")
RETIRED = "retired-provider"


@pytest.fixture
def h(client: Any, credential_blobs: Any) -> PurgeHarness:
    return PurgeHarness(client, credential_blobs)


def only(report: Any, account_id: str) -> Any:
    (result,) = [result for result in report.accounts if result.account_id == account_id]
    return result


def account_rows(**nonzero: int) -> dict[str, int]:
    rows = {"index_rows": 0, "name_shaped_blobs": 0, "uuid_shaped_blobs": 0}
    rows.update(nonzero)
    return rows


# --- C1 / C2: what goes and what stays ------------------------------------------------------------


def test_index_rows_and_unaddressed_blobs_go_and_every_addressed_blob_stays(
    h: PurgeHarness,
) -> None:
    account = h.new_account()
    kept = {h.blob(address(account, h.connection(account)))}
    # INVARIANT (C2, Q3): an `error`, a `pending` (its callback has not written yet) and a `revoked`
    # row address their blobs exactly like an active one.
    for status in ("error", "pending", "revoked"):
        kept.add(h.blob(address(account, h.connection(account, status=status))))
    # The Q4 fixture: a migrated Connection reads its Profile's blob at the legacy name address.
    migrated = h.connection(account, locator=credential_locator_for(ANTHROPIC, account, "default"))
    h.mark(account, "migrated", effective=migrated)
    h.document(account, name="default")
    h.document(account, name="work")
    kept.add(h.blob(address(account, "default")))
    orphans = {h.blob(address(account, "work")), h.blob(address(account, uuid4()))}
    before = h.rows()
    assert index_row(account) in before

    report = h.purge(accounts=(account,))

    assert h.rows() == before - orphans - {index_row(account)}
    assert kept <= h.rows()
    assert only(report, account).skipped is None
    assert only(report, account).rows == account_rows(
        index_rows=1, name_shaped_blobs=1, uuid_shaped_blobs=1
    )
    assert report.counts() == zero_counts(index_rows=1, name_shaped_blobs=1, uuid_shaped_blobs=1)
    assert report.legacy_index is None


def test_a_configured_physical_account_is_resolved_through_the_strategy(h: PurgeHarness) -> None:
    providers = ProviderRegistry()
    providers.register(
        AnthropicProviderPlugin(settings=AnthropicPluginSettings(keychain_account="account-custom"))
    )
    account = h.new_account()
    service = address(account, h.connection(account, auth_type="api_key"))
    custom = h.blob(service, "account-custom")
    sibling = h.blob(service, "default")

    report = h.purge(accounts=(account,), providers=providers)

    # INVARIANT (C1): the kept address is the strategy's, never the locator's literal `default`.
    assert custom in h.rows()
    assert sibling not in h.rows()
    assert only(report, account).rows == account_rows(uuid_shaped_blobs=1)


def test_a_document_skips_nothing_when_no_blob_it_names_would_go(h: PurgeHarness) -> None:
    account = h.new_account()
    h.connection(account, locator=credential_locator_for(ANTHROPIC, account, "default"))
    kept = h.blob(address(account, "default"))
    h.document(account, name="default")
    # WHY not a refusal: C4 protects a blob a backfill could adopt, and this document names none.
    h.document(account, name="never-stored")

    report = h.purge(accounts=(account,))

    assert only(report, account).skipped is None
    assert kept in h.rows()
    assert index_row(account) not in h.rows()


def test_all_sweeps_deleted_accounts_and_keeps_every_row_it_does_not_recognise(
    h: PurgeHarness,
) -> None:
    startup = h.rows()
    gone = str(uuid4())
    swept = {
        h.blob(address(gone, "default")),
        h.blob(address(gone, uuid4())),
        h.blob(address(gone, "work"), "account-custom"),
    }
    h.blobs.write(*index_row(gone), ProfileIndex().model_dump_json())
    foreign = {
        # WHY seeded: the fixture app takes its JWT secret from the environment, not this row.
        h.blob("aigateway:jwt-secret"),
        h.blob(address(h.new_account(), "default", cp=RETIRED)),
        h.blob(f"aigateway:{ANTHROPIC}:not-an-account:default"),
        h.blob("unrelated-service"),
    }
    # INVARIANT (C2): a deleted account's blob that ANY Connection row names stays — here a live
    # account's row that points across accounts.
    shared = h.blob(address(gone, "shared"))
    h.connection(h.new_account(), locator={"service": shared[0], "account": "default"})

    report = h.purge()

    assert h.rows() == startup | foreign | {shared}
    assert not swept & h.rows()
    assert report.counts() == zero_counts(
        index_rows=1,
        deleted_account_blobs=len(swept),
        kept_unrecognised_rows=len(startup) + len(foreign),
    )
    assert report.legacy_index == "absent"


# --- C4: fail closed ----------------------------------------------------------------------------


def _quarantined(h: PurgeHarness) -> str:
    account = h.new_account()
    h.mark(account, "quarantined")
    return account


def _unreadable_marker(h: PurgeHarness) -> str:
    account = h.new_account()
    h.mark(account, "none")
    h.sql(
        "update provider_credential_slots set migration_state = 'bogus' where account_id = ?",
        account,
    )
    return account


def _unloaded_provider(h: PurgeHarness) -> str:
    account = h.new_account()
    h.connection(account, provider=RETIRED)
    return account


def _unmigrated_document(h: PurgeHarness) -> str:
    account = h.new_account()
    h.document(account)
    h.blob(address(account, "default"))
    return account


def _unmigrated_document_on_a_none_marker(h: PurgeHarness) -> str:
    # WHY: `none` is a marker the pair has, not yet `migrated`; the document still names the blob.
    account = h.new_account()
    h.mark(account, "none")
    h.document(account)
    h.blob(address(account, "default"))
    return account


def _unmigrated_legacy_document(h: PurgeHarness) -> str:
    account = h.new_account()
    h.legacy_documents(profile(account))
    h.blob(address(account, "default"))
    return account


def _unparseable_index(h: PurgeHarness) -> str:
    account = h.new_account()
    h.blobs.write(*index_row(account), "not a document")
    return account


def _undecryptable_index(h: PurgeHarness) -> str:
    account = h.new_account()
    nonce, payload = (base64.b64encode(os.urandom(n)).decode() for n in (12, 32))
    h.blobs.write_raw(*index_row(account), f"v1:{nonce}:{payload}", ciphertext_version="v1")
    return account


SKIPS: dict[str, tuple[Callable[[PurgeHarness], str], str]] = {
    "quarantined-marker": (_quarantined, "quarantined_marker"),
    "unreadable-marker": (_unreadable_marker, "marker_unreadable"),
    "unloaded-provider": (_unloaded_provider, "connection_unresolvable"),
    "unmigrated-document": (_unmigrated_document, "unmigrated_document"),
    "unmigrated-document-none-marker": (
        _unmigrated_document_on_a_none_marker,
        "unmigrated_document",
    ),
    "unmigrated-legacy-document": (_unmigrated_legacy_document, "unmigrated_document"),
    "unparseable-index": (_unparseable_index, "index_unreadable"),
    "undecryptable-index": (_undecryptable_index, "index_unreadable"),
}


@pytest.mark.parametrize("case", sorted(SKIPS))
def test_an_account_that_cannot_be_proven_is_skipped_whole(h: PurgeHarness, case: str) -> None:
    seed, reason = SKIPS[case]
    account = seed(h)
    h.connection(account, status="revoked")
    h.blob(address(account, uuid4()))
    before = h.rows()

    report = h.purge(accounts=(account,))

    assert h.rows() == before
    assert (only(report, account).skipped, only(report, account).rows) == (reason, account_rows())
    assert report.counts() == zero_counts(skipped_accounts=1)


MALFORMED_LOCATORS: dict[str, Any] = {
    "not-a-mapping": [f"aigateway:{ANTHROPIC}:a:b", "default"],
    "no-service": {"account": "default"},
    "service-not-text": {"service": 7, "account": "default"},
    "other-namespace": {"service": "aigateway:openai:a:b", "account": "default"},
    "empty-name": {"service": f"aigateway:{ANTHROPIC}:", "account": "default"},
    "physical-account": {"service": f"aigateway:{ANTHROPIC}:a:b", "account": "account-custom"},
}


@pytest.mark.parametrize("case", sorted(MALFORMED_LOCATORS))
def test_a_malformed_locator_skips_its_account_instead_of_falling_back(
    h: PurgeHarness, case: str
) -> None:
    account = h.new_account()
    connection = h.connection(account, locator=MALFORMED_LOCATORS[case])
    # WHY this blob: the runtime falls back to the row's own uuid address; the purge must not.
    h.blob(address(account, connection))
    h.blob(address(account, uuid4()))
    before = h.rows()

    report = h.purge(accounts=(account,))

    assert h.rows() == before
    assert only(report, account).skipped == "connection_unresolvable"


@pytest.mark.parametrize(
    ("locator", "name"),
    [
        ({"service": f"aigateway:{ANTHROPIC}:a:b", "account": "default"}, "a:b"),
        ({"service": f"aigateway:{ANTHROPIC}:a:b"}, "a:b"),
        *((locator, None) for locator in MALFORMED_LOCATORS.values()),
    ],
)
def test_a_locator_names_a_credential_only_when_well_formed(locator: Any, name: str | None) -> None:
    assert locator_credential_name(locator, credential_provider=ANTHROPIC) == name


def test_an_account_that_does_not_exist_is_skipped_and_its_rows_wait_for_the_sweep(
    h: PurgeHarness,
) -> None:
    gone = str(uuid4())
    h.blob(address(gone, uuid4()))
    before = h.rows()

    report = h.purge(accounts=(gone,))

    assert h.rows() == before
    assert only(report, gone).skipped == "account_missing"


# --- the legacy global index row ---------------------------------------------------------------


def test_the_legacy_global_row_goes_last_once_every_account_it_lists_is_done(
    h: PurgeHarness,
) -> None:
    listed = h.new_account()
    h.legacy_documents(profile(listed, name="old"), profile(str(uuid4())))

    report = h.purge()

    assert LEGACY_INDEX_ROW not in h.rows()
    assert only(report, listed).skipped is None
    assert report.legacy_index == "purged"
    assert report.counts()["index_rows"] == 1


def test_the_legacy_global_row_stays_while_an_account_it_lists_is_skipped(h: PurgeHarness) -> None:
    held = _quarantined(h)
    h.legacy_documents(profile(held))

    report = h.purge()

    assert LEGACY_INDEX_ROW in h.rows()
    assert report.legacy_index == "kept_listed_account_skipped"


def test_an_unreadable_legacy_global_row_stays(h: PurgeHarness) -> None:
    h.blobs.write(*LEGACY_INDEX_ROW, "not a document")

    report = h.purge()

    assert LEGACY_INDEX_ROW in h.rows()
    assert report.legacy_index == "kept_unreadable"


def test_one_account_never_touches_the_legacy_global_row(h: PurgeHarness) -> None:
    account = h.new_account()
    h.legacy_documents(profile(account, name="old"))

    report = h.purge(accounts=(account,))

    assert LEGACY_INDEX_ROW in h.rows()
    assert only(report, account).skipped is None
    assert report.legacy_index is None


# --- C5: dry run, exact apply, idempotence, no service string -------------------------------------


def _seed_world(h: PurgeHarness) -> str:
    account = h.new_account()
    h.blob(address(account, h.connection(account)))
    h.document(account, name="work")
    h.mark(account, "migrated", effective=h.connection(account, status="revoked"))
    h.blob(address(account, "work"))
    h.blob(address(account, uuid4()))
    gone = str(uuid4())
    h.blob(address(gone, "default"))
    h.legacy_documents(profile(gone))
    return account


def test_dry_run_writes_nothing_and_apply_deletes_exactly_what_it_reported(
    h: PurgeHarness,
) -> None:
    _seed_world(h)
    before, rows_before = h.dump(), h.rows()

    dry = h.purge("dry-run")

    assert h.dump() == before
    applied = h.purge("apply")
    assert {**dry.to_dict(), "mode": "apply"} == applied.to_dict()
    counts = applied.counts()
    assert len(rows_before - h.rows()) == sum(counts[kind] for kind in DELETION_KINDS) > 0
    again = h.purge("apply")
    assert again.counts() == zero_counts(kept_unrecognised_rows=counts["kept_unrecognised_rows"])


def test_report_and_journal_carry_account_ids_and_counts_only(h: PurgeHarness) -> None:
    account = _seed_world(h)
    skipped = _unmigrated_document(h)
    journal = io.StringIO()

    report = h.purge("dry-run", journal=journal)

    text = json.dumps(report.to_dict()) + journal.getvalue()
    assert leaks_in(text) == []
    assert f"{account}:" not in text and f"{skipped}:" not in text
    lines = [json.loads(line) for line in journal.getvalue().splitlines()]
    assert len(lines) == len(report.accounts) + 1
    assert [line["account_id"] for line in lines[:-1]] == [r.account_id for r in report.accounts]
    assert lines[-1] == {
        "mode": "dry-run",
        "summary": report.counts(),
        "legacy_index": report.legacy_index,
    }
    assert report.to_dict()["counts"]["skipped_accounts"] == 1
    assert only(report, skipped).to_dict() == {
        "account_id": skipped,
        "rows": account_rows(),
        "skipped": "unmigrated_document",
    }


class _FlushLog(io.StringIO):
    """A journal that records what it held each time it was flushed."""

    def __init__(self) -> None:
        super().__init__()
        self.flushed: list[str] = []

    def flush(self) -> None:
        self.flushed.append(self.getvalue())
        super().flush()


def test_every_journal_line_is_flushed_as_it_is_written(h: PurgeHarness) -> None:
    first, second = h.new_account(), h.new_account()
    journal = _FlushLog()

    h.purge(accounts=(first, second), journal=journal)

    # INVARIANT: an apply that dies part-way leaves on disk every account it committed.
    assert [text.count("\n") for text in journal.flushed] == [1, 2, 3]


def test_an_unknown_mode_is_refused(h: PurgeHarness) -> None:
    with pytest.raises(ValueError, match="mode"):
        h.purge("rollback")
