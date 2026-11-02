"""The Profile-index conflict renderings are gone with their last emitter (Stage E cleanup, E5a).

# FEATURE: OME-1138 E5 — since OME-1209 E4b no request path writes a Profile document, so
# `CredentialBlobMutationConflict` (CAS retries on the index blob run out) cannot reach a request,
# and no `WriteConflict` is raised as `retry_exhausted` or with a Profile subject.
# INVARIANT: no module calls `ORMStore.mutate` since its last caller, the offline
# `ProfileIndexStore`, went with E5c; if a request path ever calls it again, this guard fails before
# an unrendered conflict ships.
# INVARIANT: such a conflict reaching a request is a plain unhandled error (the sanitized 500),
# and a captured chat call replays the same.

Retired at OME-1138 Stage E, E5c: `test_only_the_offline_profile_index_calls_mutate` — the offline
index is deleted, so no module is left to call `mutate`; successor:
`test_no_module_calls_the_blob_store_mutate`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, get_args

import aigateway
from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.core.provider_access.types import WriteConflictKind, WriteSubject
from aigateway.routes.chat import _error_view

_SRC = Path(inspect.getfile(aigateway)).resolve().parent


def _mutate_callers() -> set[str]:
    callers: set[str] = set()
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mutate"
            ):
                callers.add(path.relative_to(_SRC).as_posix())
    return callers


def test_no_module_calls_the_blob_store_mutate() -> None:
    assert _mutate_callers() == set()


def test_the_app_registers_no_profile_index_conflict_handler(client: Any) -> None:
    assert CredentialBlobMutationConflict not in client.app.exception_handlers


def test_a_captured_call_replays_a_mutation_conflict_as_the_generic_500() -> None:
    status, detail = _error_view(CredentialBlobMutationConflict("forced contention"))

    assert status == 500
    assert "profile_index_conflict" not in str(detail)


def test_a_write_conflict_is_only_ever_a_superseded_connection() -> None:
    assert get_args(WriteConflictKind) == ("superseded",)
    assert get_args(WriteSubject) == ("connection",)
