"""`ORMStore`: the encrypted round trip, its decryption refusals, and delete.

Retired at OME-1138 close-out, L4b: `test_orm_store_mutate_can_delete_existing_blob` and
`test_orm_store_mutate_delete_missing_blob_is_noop` — `ORMStore.mutate` is removed with its last
caller, the offline Profile index; successors: `test_orm_store_round_trip` (deleting a stored
blob), `test_orm_store_delete_is_idempotent` (deleting a missing one), and the retired-arms guard
`test_the_blob_store_has_no_mutation_path`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.credential_blob.store import ORMStore
from aigateway.core.secrets.local import LocalSecretStore
from aigateway.core.secrets.mixin import SecretDecryptionError
from aigateway.db import build_tortoise_config

_TEST_KEY = bytes(range(32))


@pytest_asyncio.fixture
async def orm_store(credential_blobs):
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{credential_blobs.db_path}"),
        _enable_global_fallback=True,
    )
    try:
        # Inject the secret store directly (the process-wide active store is only
        # installed by the app lifespan, which this unit fixture does not run).
        yield ORMStore(secret_store=LocalSecretStore(_TEST_KEY))
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_orm_store_round_trip(credential_blobs, orm_store) -> None:
    assert await orm_store.read("service", "account") is None
    await orm_store.write("service", "account", "secret")
    assert await orm_store.read("service", "account") == "secret"

    await orm_store.write("service", "account", "updated")
    assert await orm_store.read("service", "account") == "updated"

    # The value is stored encrypted, not as plaintext.
    raw = credential_blobs.read_raw("service", "account")
    assert raw is not None
    assert raw.startswith("v1:")
    assert "updated" not in raw

    await orm_store.delete("service", "account")
    assert await orm_store.read("service", "account") is None


@pytest.mark.asyncio
async def test_orm_store_persists_ciphertext_version(credential_blobs, orm_store) -> None:
    await orm_store.write("svc", "acc", "value")
    assert credential_blobs.read_ciphertext_version("svc", "acc") == "v1"


@pytest.mark.asyncio
async def test_orm_store_reads_legacy_plaintext(credential_blobs, orm_store) -> None:
    # A row written before SF-221 holds plaintext JSON (no v1: prefix).
    legacy = '{"access_token":"legacy-plaintext"}'
    credential_blobs.write_raw("legacy", "account", legacy)
    assert await orm_store.read("legacy", "account") == legacy

    # Next write upgrades it to ciphertext.
    await orm_store.write("legacy", "account", legacy)
    raw = credential_blobs.read_raw("legacy", "account")
    assert raw.startswith("v1:")
    assert await orm_store.read("legacy", "account") == legacy


@pytest.mark.asyncio
async def test_orm_store_rejects_versioned_row_with_missing_ciphertext_prefix(
    credential_blobs,
    orm_store,
) -> None:
    credential_blobs.write_raw(
        "svc",
        "acct",
        "prefix-damaged-ciphertext",
        ciphertext_version="v1",
    )

    with pytest.raises(SecretDecryptionError) as exc_info:
        await orm_store.read("svc", "acct")

    message = str(exc_info.value)
    assert "svc" in message
    assert "acct" in message
    assert "v1" in message
    assert "AIGATEWAY_SECRET_KEY" in message


@pytest.mark.asyncio
async def test_orm_store_rejects_versioned_row_from_different_secret_provider(
    credential_blobs,
    orm_store,
) -> None:
    credential_blobs.write_raw(
        "svc",
        "acct",
        "kms-v1:opaque-provider-payload",
        ciphertext_version="kms-v1",
    )

    with pytest.raises(SecretDecryptionError) as exc_info:
        await orm_store.read("svc", "acct")

    message = str(exc_info.value)
    assert "svc" in message
    assert "acct" in message
    assert "kms-v1" in message
    assert "AIGATEWAY_SECRET_PROVIDER" in message
    assert "different secret provider version" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_orm_store_wrong_key_error_names_affected_credential(
    credential_blobs,
    orm_store,
) -> None:
    await orm_store.write("svc", "acct", "super-secret-value")
    wrong_key_store = ORMStore(secret_store=LocalSecretStore(b"z" * 32))

    with pytest.raises(SecretDecryptionError) as exc_info:
        await wrong_key_store.read("svc", "acct")

    message = str(exc_info.value)
    assert "svc" in message
    assert "acct" in message
    assert "AIGATEWAY_SECRET_KEY" in message
    # Non-leakage. The outer _credential_decryption_error is built only from
    # service/account/version and structurally cannot carry the plaintext; the
    # wrapped cause (LocalSecretStore) is the layer that could regress, so assert
    # the plaintext is absent from the whole exception chain, not just the outer
    # message (SF-327 R2/F6).
    assert "super-secret-value" not in message
    assert "super-secret-value" not in str(exc_info.value.__cause__ or "")


@pytest.mark.asyncio
async def test_orm_store_delete_is_idempotent(credential_blobs, orm_store) -> None:
    await orm_store.delete("missing", "account")
    assert credential_blobs.read("missing", "account") is None
