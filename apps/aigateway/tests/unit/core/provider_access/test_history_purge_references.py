"""The purge against references it does not own: other accounts' rows, whole addresses (E5b).

# FEATURE: OME-1138 Stage E history cleanup, spec C1/C2/C4 — a blob stays when ANY Connection row
# addresses it, not only a row of the account being purged, and "addresses" means the whole
# physical `(service, account)` pair the row's strategy resolves.
# INVARIANT (C2): a live account's purge keeps a blob another account's Connection resolves to; a
# Connection whose address does not resolve but whose locator text names the account skips it.
# INVARIANT (C1): a deleted account's blob goes unless a Connection resolves to that exact pair; a
# sibling row under the same service at another physical account is not protected by it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from history_purge_probes import ANTHROPIC, PurgeHarness, address, zero_counts

from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

RETIRED = "retired-provider"
CUSTOM = "account-custom"


@pytest.fixture
def h(client: Any, credential_blobs: Any) -> PurgeHarness:
    return PurgeHarness(client, credential_blobs)


def only(report: Any, account_id: str) -> Any:
    (result,) = [result for result in report.accounts if result.account_id == account_id]
    return result


def custom_account_registry() -> ProviderRegistry:
    providers = ProviderRegistry()
    providers.register(
        AnthropicProviderPlugin(settings=AnthropicPluginSettings(keychain_account=CUSTOM))
    )
    return providers


# --- C2: another account's Connection -----------------------------------------------------------


def test_a_live_accounts_purge_keeps_a_blob_another_accounts_connection_addresses(
    h: PurgeHarness,
) -> None:
    owner, borrower = h.new_account(), h.new_account()
    shared = h.blob(address(owner, "shared"))
    h.connection(borrower, locator={"service": shared[0], "account": "default"})
    orphan = h.blob(address(owner, uuid4()))

    report = h.purge(accounts=(owner,))

    assert shared in h.rows()
    assert orphan not in h.rows()
    assert only(report, owner).skipped is None
    assert report.counts() == zero_counts(uuid_shaped_blobs=1)


UNRESOLVABLE_FOREIGN: dict[str, dict[str, Any]] = {
    # The locator names a physical account, so it resolves to no address the purge may trust.
    "physical-account-locator": {"locator_account": CUSTOM},
    # No loaded plugin serves the row, so no strategy resolves it.
    "unloaded-provider": {"provider": RETIRED},
}


@pytest.mark.parametrize("case", sorted(UNRESOLVABLE_FOREIGN))
def test_an_unresolvable_connection_that_names_this_account_skips_it(
    h: PurgeHarness, case: str
) -> None:
    seed = UNRESOLVABLE_FOREIGN[case]
    owner, borrower = h.new_account(), h.new_account()
    shared = h.blob(address(owner, "shared"))
    h.connection(
        borrower,
        provider=seed.get("provider", ANTHROPIC),
        locator={"service": shared[0], "account": seed.get("locator_account", "default")},
    )
    h.blob(address(owner, uuid4()))
    before = h.rows()

    report = h.purge(accounts=(owner,))

    # INVARIANT (C4): the purge cannot prove which blob that row means, so it touches none.
    assert h.rows() == before
    assert only(report, owner).skipped == "connection_unresolvable"


def test_an_unresolvable_connection_of_another_account_naming_nothing_here_skips_nothing(
    h: PurgeHarness,
) -> None:
    owner, borrower = h.new_account(), h.new_account()
    h.connection(borrower, provider=RETIRED)
    orphan = h.blob(address(owner, uuid4()))

    report = h.purge(accounts=(owner,))

    assert orphan not in h.rows()
    assert only(report, owner).skipped is None


# --- C1: the whole physical address ---------------------------------------------------------------


def test_the_sweep_keeps_only_the_exact_address_a_connection_resolves_to(h: PurgeHarness) -> None:
    gone = str(uuid4())
    addressed = h.blob(address(gone, "shared"))
    sibling = h.blob(addressed[0], CUSTOM)
    h.connection(h.new_account(), locator={"service": addressed[0], "account": "default"})

    report = h.purge()

    assert addressed in h.rows()
    assert sibling not in h.rows()
    assert report.counts()["deleted_account_blobs"] == 1


def test_an_unresolvable_connection_keeps_every_deleted_account_row_under_its_service(
    h: PurgeHarness,
) -> None:
    gone = str(uuid4())
    named = {h.blob(address(gone, "shared")), h.blob(address(gone, "shared"), CUSTOM)}
    borrower = h.new_account()
    h.connection(borrower, locator={"service": address(gone, "shared"), "account": CUSTOM})

    report = h.purge()

    # WHY by service: the row resolves to no address, so no physical account can be ruled out; its
    # own account is skipped, which makes the whole run report a refusal.
    assert named <= h.rows()
    assert only(report, borrower).skipped == "connection_unresolvable"
    assert report.refused()


def test_an_unresolvable_connection_naming_no_service_keeps_no_deleted_account_row(
    h: PurgeHarness,
) -> None:
    gone = str(uuid4())
    orphan = h.blob(address(gone, "shared"))
    borrower = h.new_account()
    # WHY: the runtime reads such a row at its own `<account>:<row id>` name, which only its own
    # account's pass can lose, and that pass skips it.
    h.connection(borrower, locator={"account": "default"})

    report = h.purge()

    assert orphan not in h.rows()
    assert only(report, borrower).skipped == "connection_unresolvable"
    assert report.counts()["deleted_account_blobs"] == 1


# --- the address is proven by its row -------------------------------------------------------------


def test_a_resolved_address_with_no_row_beside_a_sibling_skips_the_account(
    h: PurgeHarness,
) -> None:
    # The gateway runs with a configured physical account; this run resolves `default`.
    account = h.new_account()
    service = address(account, h.connection(account, auth_type="api_key"))
    live = h.blob(service, CUSTOM)
    h.blob(address(account, uuid4()))
    before = h.rows()

    report = h.purge(accounts=(account,))

    # INVARIANT (C4): the row the run resolved does not exist and another does under that service,
    # so the run's configuration may not be the gateway's; it deletes nothing.
    assert h.rows() == before
    assert live in h.rows()
    assert only(report, account).skipped == "address_unproven"


def test_a_resolved_address_with_no_row_and_no_sibling_skips_nothing(h: PurgeHarness) -> None:
    account = h.new_account()
    # WHY: a `pending` row names its blob before its callback writes it.
    h.connection(account, status="pending")
    orphan = h.blob(address(account, uuid4()))

    report = h.purge(accounts=(account,))

    assert orphan not in h.rows()
    assert only(report, account).skipped is None


def test_the_sweep_keeps_a_deleted_accounts_rows_under_an_unproven_address(
    h: PurgeHarness,
) -> None:
    gone = str(uuid4())
    service = address(gone, "shared")
    live = h.blob(service, CUSTOM)
    h.connection(h.new_account(), locator={"service": service, "account": "default"})

    report = h.purge()

    assert live in h.rows()
    assert report.counts()["deleted_account_blobs"] == 0


def test_an_unmigrated_document_protects_its_physical_address(h: PurgeHarness) -> None:
    account = h.new_account()
    h.document(account, name="default")
    # The Connection a backfill would create on this document reads the strategy's physical
    # account, not the locator's logical `default`.
    physical = h.blob(address(account, "default"), CUSTOM)

    report = h.purge(accounts=(account,), providers=custom_account_registry())

    assert physical in h.rows()
    assert only(report, account).skipped == "unmigrated_document"
