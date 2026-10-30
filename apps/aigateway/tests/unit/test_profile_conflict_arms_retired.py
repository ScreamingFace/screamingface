"""The Profile-index conflict arms are gone with their last emitter (Stage E cleanup, E5a; L4b).

# FEATURE: OME-1138 E5 — since OME-1209 E4b no request path writes a Profile document, and since
# the close-out (L4b) the blob store has no optimistic `mutate` at all, so the CAS conflict it
# raised (`CredentialBlobMutationConflict`) no longer exists to reach a request; no `WriteConflict`
# is raised as `retry_exhausted` or with a Profile subject.
# INVARIANT: the credential blob store has no read-modify-write `mutate` and no conflict class of
# its own; the last `mutate` caller, the offline `ProfileIndexStore`, went with E5c. If that path
# returns, this guard fails before an unrendered conflict ships.

Retired at OME-1138 Stage E, E5c: `test_only_the_offline_profile_index_calls_mutate` — the offline
index is deleted, so no module is left to call `mutate`; successor:
`test_no_module_calls_the_blob_store_mutate`.

Retired at OME-1138 close-out, L4b: `test_no_module_calls_the_blob_store_mutate` — `mutate` itself
is removed, so the call scan is re-expressed on the store; successor:
`test_the_blob_store_has_no_mutation_path`.

Retired at OME-1138 close-out, L4b: `test_the_app_registers_no_profile_index_conflict_handler` and
`test_a_captured_call_replays_a_mutation_conflict_as_the_generic_500` — the conflict class is
deleted with `mutate`, so there is nothing to register or replay; successors:
`test_the_blob_store_has_no_mutation_path`, and for any unexpected exception
`test_frozen_copy_capture.py::test_an_unexpected_exception_is_captured_as_a_generic_500_and_not_swallowed`.
"""

from __future__ import annotations

from typing import get_args

from aigateway.core.credential_blob import store as store_module
from aigateway.core.credential_blob.store import CredentialBlobStore, ORMStore
from aigateway.core.provider_access.types import WriteConflictKind, WriteSubject


def _public(cls: type) -> set[str]:
    return {name for name in vars(cls) if not name.startswith("_")}


def test_the_blob_store_has_no_mutation_path() -> None:
    assert not hasattr(ORMStore, "mutate")
    assert not hasattr(CredentialBlobStore, "mutate")
    assert not hasattr(store_module, "CredentialBlobMutationConflict")
    # WHY the exact sets: a renamed read-modify-write path would pass the name checks above.
    assert _public(CredentialBlobStore) == {"read", "write", "delete"}
    assert _public(ORMStore) == {
        "read",
        "write",
        "delete",
        "begin_dispatch",
        "record_dispatch_outcome",
        "operational_state",
    }


def test_a_write_conflict_is_only_ever_a_superseded_connection() -> None:
    assert get_args(WriteConflictKind) == ("superseded",)
    assert get_args(WriteSubject) == ("connection",)
