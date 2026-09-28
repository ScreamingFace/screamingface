"""The backfill's write half: apply, dry-run, rollback (OME-1208, S4).

# FEATURE: Stage B backfill — `python -m aigateway.migrate_profiles`: a Profile-only pair gets a
# Connection on the Profile's own blob address (no re-entry, no decrypt-for-transfer), a single
# active Connection-only pair is named effective, an unprovable pair is quarantined, and the pair
# marker publishes each disposition inside ONE transaction per account.
# INVARIANT (card): `--dry-run` writes no row, blob, key or nonce and leaks no secret; `--apply` is
# idempotent and survives a crash or retry without minting a new UUID or duplicating a secret; the
# R1 rollback resets the marker and keeps every blob; reports carry opaque identifiers only.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any
from uuid import UUID

import pytest
from backfill_probes import (
    CREDENTIAL_PROVIDER,
    SECRET_PROMPT,
    credential_provider_of,
    leaks_in,
    run,
    seed_profile_for,
    snapshot,
    token_of,
)
from connection_backed_admin_probes import (
    KEY,
    blob_at_profile_address,
    connections,
    document,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import status
from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.profile_models import ProfileDefaults
from aigateway.core.provider_access.backfill_apply import all_account_ids
from aigateway.core.provider_access.pair_authority import PairAuthorityConflict, PairAuthorityStore

OTHER = "openrouter"


@pytest.fixture
def h(authenticated_client: Any, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def only_record(report: Any, provider: str = PROVIDER) -> Any:
    records = [r for a in report.accounts for r in a.records if r.provider == provider]
    assert len(records) == 1, records
    return records[0]


def advance_that(monkeypatch: pytest.MonkeyPatch, *, fails_on_call: int, error: Exception) -> None:
    """Let the n-th marker advance of the run raise `error` (1-based); the others are real."""
    real = PairAuthorityStore.advance
    calls = {"n": 0}

    async def advance(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == fails_on_call:
            raise error
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(PairAuthorityStore, "advance", advance)


# --- apply ----------------------------------------------------------------------------------------


def test_apply_migrates_a_profile_only_oauth_pair_without_re_entry(h: Any) -> None:
    h.seed_document(credential="tok", defaults=ProfileDefaults(system_prompt=SECRET_PROMPT))
    blob_before, document_before = blob_at_profile_address(h), document(h)

    report = run(h, "apply")

    record = only_record(report)
    assert (record.disposition, record.category, record.applied, record.generation) == (
        "migrated",
        "profile_only",
        True,
        1,
    )
    rows = connections(h)
    assert len(rows) == 1
    row = rows[0]
    assert (row.label, row.status, row.auth_type) == ("default", "active", "oauth")
    assert row.credential_locator == credential_locator_for(
        CREDENTIAL_PROVIDER, h.account_id, "default"
    )
    assert record.connection_id == str(row.id)
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        row.id,
        1,
    )
    assert pair.migration_note == "profile_only"
    # INVARIANT: no re-entry and no transfer — the Profile's blob and document are byte-identical.
    assert blob_at_profile_address(h) == blob_before
    assert document(h) == document_before
    # The pair is now served THROUGH the Connection: the shell and the native token route agree.
    shown = status(h)
    assert shown.status_code == 200, shown.text
    assert (shown.json()["state"], shown.json()["auth_type"]) == ("authenticated", "oauth")
    token = token_of(h, row.id)
    assert token.status_code == 200, token.text
    assert token.json()["access_token"] == "tok"


def test_apply_migrates_a_profile_only_api_key_pair(h: Any) -> None:
    h.seed_document(auth_type="api_key", credential=KEY)
    run(h, "apply")
    row = connections(h)[0]
    assert (row.status, row.auth_type) == ("active", "api_key")
    shown = status(h)
    assert (shown.json()["state"], shown.json()["auth_type"]) == ("authenticated", "api_key")


def test_apply_names_a_single_active_connection_and_invents_no_profile(h: Any) -> None:
    connection_id = h.seed_connection(label="primary", credential="ctok")
    report = run(h, "apply")
    record = only_record(report)
    assert (record.category, record.applied, record.connection_id) == (
        "connection_only",
        True,
        connection_id,
    )
    pair = marker(h)
    assert (pair.migration_state, str(pair.effective_connection_id), pair.generation) == (
        "migrated",
        connection_id,
        1,
    )
    assert document(h) is None and len(connections(h)) == 1
    assert token_of(h, connection_id).json()["access_token"] == "ctok"


def test_apply_quarantines_a_differing_pair_and_keeps_legacy_behaviour(h: Any) -> None:
    h.seed_document(credential="tok")
    shadow = h.seed_connection(label="shadow", credential="other")
    blobs_before = snapshot(h)[0]
    report = run(h, "apply")
    record = only_record(report)
    assert (record.disposition, record.category, record.applied, record.connection_id) == (
        "quarantined",
        "credentials_differ",
        True,
        None,
    )
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "quarantined",
        None,
        1,
    )
    assert pair.migration_note == "credentials_differ"
    # INVARIANT (D3): legacy authority kept — the Profile answers, the Connection row is untouched,
    # neither secret is chosen or rewritten.
    assert status(h).json()["state"] == "authenticated"
    assert h.connection_status(shadow) == "active"
    assert snapshot(h)[0] == blobs_before


def test_apply_is_idempotent(h: Any) -> None:
    h.seed_document(credential="tok")
    run(h, "apply")
    after_first = snapshot(h)
    report = run(h, "apply")
    record = only_record(report)
    assert (record.category, record.applied, record.generation) == ("already_migrated", False, 1)
    assert snapshot(h) == after_first
    assert len(connections(h)) == 1


def test_a_crash_before_commit_leaves_no_trace_and_the_retry_completes(
    h: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.seed_document(credential="tok")
    advance_that(monkeypatch, fails_on_call=1, error=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        run(h, "apply")
    # INVARIANT: the Connection insert and the marker share one transaction — nothing survives.
    assert connections(h) == []
    assert (marker(h).migration_state, marker(h).generation) == ("none", 0)
    report = run(h, "apply")
    assert only_record(report).applied is True
    assert len(connections(h)) == 1


def test_a_racing_writer_rolls_the_whole_account_back(
    h: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.seed_document(credential="tok")
    seed_profile_for(
        h, OTHER, credential_provider=credential_provider_of(h, OTHER), credential="tok"
    )
    advance_that(monkeypatch, fails_on_call=2, error=PairAuthorityConflict(OTHER, 0))

    report = run(h, "apply")

    account = report.accounts[0]
    assert account.conflict is True
    assert all(record.applied is False for record in account.records)
    assert report.to_dict()["counts"]["conflicts"] == 1
    # INVARIANT: one transaction per account — the first pair's Connection and marker are gone too.
    assert connections(h) == []
    assert marker(h).generation == 0
    assert h.call(PairAuthorityStore().read, h.account_id, OTHER).generation == 0


def test_apply_visits_every_account_with_all(h: Any, provisioned_user_factory: Any) -> None:
    h.seed_document(credential="tok")
    bob = provisioned_user_factory("bob")["id"]
    seed_profile_for(h, PROVIDER, credential_provider=CREDENTIAL_PROVIDER, account_id=bob)
    everyone = h.call(all_account_ids)
    assert {h.account_id, bob} <= set(everyone)

    report = run(h, "apply", account_ids=everyone)

    applied = {a.account_id for a in report.accounts for r in a.records if r.applied}
    assert applied == {h.account_id, bob}
    assert h.call(PairAuthorityStore().read, bob, PROVIDER).migration_state == "migrated"
    assert marker(h).migration_state == "migrated"


# --- dry-run --------------------------------------------------------------------------------------


def test_dry_run_writes_nothing_and_leaks_nothing(h: Any, caplog: pytest.LogCaptureFixture) -> None:
    h.seed_document(credential="tok", defaults=ProfileDefaults(system_prompt=SECRET_PROMPT))
    h.seed_connection(label="shadow", credential="other")
    seed_profile_for(h, OTHER, credential_provider=credential_provider_of(h, OTHER), credential=KEY)
    before = snapshot(h)
    journal = io.StringIO()
    # WHY scoped: the ORM's own `tortoise.db_client` DEBUG channel echoes query parameters (blob
    # addresses, account ids) for EVERY app query — a deployment logging concern, not a tool write.
    # The tool itself logs nothing; the scan covers the app's loggers and everything the tool emits.
    caplog.set_level(logging.DEBUG, logger="aigateway")

    report = run(h, "dry-run", journal=journal)

    assert snapshot(h) == before
    by_provider = {r.provider: r for r in report.accounts[0].records}
    assert (by_provider[PROVIDER].disposition, by_provider[PROVIDER].category) == (
        "quarantined",
        "credentials_differ",
    )
    assert (by_provider[OTHER].disposition, by_provider[OTHER].category) == (
        "migrated",
        "profile_only",
    )
    assert all(record.applied is False for record in by_provider.values())
    assert marker(h).generation == 0 and len(connections(h)) == 1
    counts = report.to_dict()["counts"]
    assert (counts["migrated"], counts["quarantined"], counts["applied"]) == (1, 1, 0)
    # INVARIANT: opaque identifiers only — no token, key, prompt, ciphertext, credential name or
    # Profile name in the report, the journal or the log.
    app_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("aigateway"))
    for text in (json.dumps(report.to_dict()), journal.getvalue(), app_log):
        assert leaks_in(text) == [], text
    assert journal.getvalue().count("\n") == 3  # two pair lines + one summary line


# --- rollback (R1) --------------------------------------------------------------------------------


def test_rollback_returns_a_migrated_pair_to_legacy_authority_keeping_every_blob(h: Any) -> None:
    h.seed_profile(credential="tok")
    effective = h.migrated["default"]
    before = snapshot(h)

    report = run(h, "rollback")

    record = only_record(report)
    assert (record.category, record.applied, record.generation, record.connection_id) == (
        "rollback",
        True,
        2,
        effective,
    )
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "none",
        None,
        2,
    )
    assert pair.migration_note == "rollback"
    # INVARIANT (D5): every blob and row kept; only the marker moved.
    assert snapshot(h)[0] == before[0] and snapshot(h)[1] == before[1]
    assert h.connection_status(effective) == "active"
    shown = status(h)
    assert shown.status_code == 200 and shown.json()["state"] == "authenticated"
    # Idempotent: a second rollback finds nothing migrated.
    assert only_record(run(h, "rollback")).applied is False


def test_rollback_leaves_unmigrated_pairs_alone(h: Any) -> None:
    h.seed_document(credential="tok")
    report = run(h, "rollback")
    record = only_record(report)
    assert (record.disposition, record.category, record.applied) == (
        "migrated",
        "profile_only",
        False,
    )
    assert marker(h).generation == 0


def test_report_shape_is_opaque(h: Any) -> None:
    h.seed_document(credential="tok")
    report = run(h, "dry-run")
    payload = report.to_dict()
    assert set(payload) == {"mode", "counts", "accounts"}
    assert payload["mode"] == "dry-run"
    (account,) = payload["accounts"]
    assert set(account) == {"account_id", "conflict", "pairs"}
    UUID(account["account_id"])
    (pair,) = account["pairs"]
    assert set(pair) == {
        "provider",
        "disposition",
        "category",
        "action",
        "generation",
        "connection_id",
        "applied",
        "alias_documents",
    }
