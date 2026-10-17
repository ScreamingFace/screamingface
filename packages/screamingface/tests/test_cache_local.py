"""The local gateway as the destination of a pull (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: a pull without the runtime extra, or without a local gateway database, is refused
before any request with an actionable hint; the local revisions are the gateway's own, with its
provider plugins loaded so the adapter revisions are compared too; and each refusal of the
gateway's loader reaches the caller as a `CachePullError` naming what to do.

The SDK test job installs no runtime extra, so the gateway modules are stood in for here, the way
`test_runtime_artifacts_dir.py` does it.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from screamingface._cache import local as local_module
from screamingface._cache.local import LocalGateway, gateway_database
from screamingface.cache import CachePullError, PullResult

_EMPTY = PullResult(0, 0, 0, False, False)


class _Rejected(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _check_database(state: SimpleNamespace) -> Callable[[Path], None]:
    """The loader's `check_database`: a missing file is refused, as the real one refuses it."""

    def check_database(database: Path) -> None:
        if not database.is_file():
            raise _Rejected("not_a_gateway_database", f"{database} cannot be opened")
        if state.database_reject:
            raise state.database_reject

    return check_database


@pytest.fixture
def gateway_modules(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Stand-ins for the four gateway modules a pull imports, recording what they were asked."""
    state = SimpleNamespace(
        loaded=[],
        plugins_loaded=False,
        revisions={"parameter_contract": "p1"},
        reject=None,
        check_reject=None,
        database_reject=None,
    )

    loader = ModuleType("aigateway.core.request_cache.sqlite_loader")
    loader.PageRejected = _Rejected  # type: ignore[attr-defined]

    def load_page(rows: Any, database: Path) -> SimpleNamespace:
        if state.reject:
            raise _Rejected(state.reject, "detail")
        state.loaded.append((list(rows), database))
        return SimpleNamespace(rows=len(rows), inserted=len(rows) - 1)

    def check_revisions(remote: Any, local: Any) -> None:
        if state.check_reject:
            raise _Rejected("revision_mismatch", "differs for openrouter_adapter")
        state.checked = (dict(remote), dict(local))

    loader.load_page = load_page  # type: ignore[attr-defined]
    loader.check_database = _check_database(state)  # type: ignore[attr-defined]
    loader.check_revisions = check_revisions  # type: ignore[attr-defined]

    plugin_loader = ModuleType("aigateway.core.loader")

    def load_plugins(_registry: object) -> None:
        state.plugins_loaded = True
        state.revisions = {**state.revisions, "openrouter_adapter": "o1"}

    plugin_loader.load_plugins = load_plugins  # type: ignore[attr-defined]
    registry = ModuleType("aigateway.core.registry")
    registry.ProviderRegistry = object  # type: ignore[attr-defined]
    revisions = ModuleType("aigateway.core.request_cache.revisions")
    revisions.active_cache_revisions = lambda: dict(state.revisions)  # type: ignore[attr-defined]

    for name, module in {
        "aigateway.core.request_cache.sqlite_loader": loader,
        "aigateway.core.loader": plugin_loader,
        "aigateway.core.registry": registry,
        "aigateway.core.request_cache.revisions": revisions,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(local_module, "missing_runtime_modules", lambda: ())
    return state


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = gateway_database(tmp_path)
    path.write_bytes(b"")
    return path


def test_the_database_is_the_gateway_file_in_the_data_dir(tmp_path: Path) -> None:
    assert gateway_database(tmp_path) == tmp_path / "aigateway.sqlite3"


def test_without_the_runtime_extra_the_pull_is_refused_with_an_install_hint(
    monkeypatch: pytest.MonkeyPatch, database: Path
) -> None:
    monkeypatch.setattr(local_module, "missing_runtime_modules", lambda: ("tortoise",))

    with pytest.raises(CachePullError) as raised:
        LocalGateway(database, empty=_EMPTY).prepare()

    assert raised.value.code == "runtime_missing"
    assert "screamingface[runtime]" in (raised.value.hint or "")
    assert raised.value.result == _EMPTY


def test_without_a_local_gateway_database_the_pull_says_to_run_up(
    gateway_modules: SimpleNamespace, tmp_path: Path
) -> None:
    with pytest.raises(CachePullError) as raised:
        LocalGateway(gateway_database(tmp_path), empty=_EMPTY).prepare()

    assert raised.value.code == "local_gateway_missing"
    assert "screamingface up" in (raised.value.hint or "")


def test_the_local_revisions_include_the_loaded_plugins_adapter_revisions(
    gateway_modules: SimpleNamespace, database: Path
) -> None:
    gateway = LocalGateway(database, empty=_EMPTY)

    gateway.prepare()
    gateway.check({"parameter_contract": "p1", "openrouter_adapter": "o1"}, _EMPTY)

    assert gateway_modules.plugins_loaded
    assert gateway_modules.checked[1] == {"parameter_contract": "p1", "openrouter_adapter": "o1"}


def test_a_check_before_prepare_is_a_programming_error(
    gateway_modules: SimpleNamespace, database: Path
) -> None:
    with pytest.raises(RuntimeError, match="prepare"):
        LocalGateway(database, empty=_EMPTY).check({}, _EMPTY)


def test_a_revision_mismatch_names_what_to_do(
    gateway_modules: SimpleNamespace, database: Path
) -> None:
    gateway_modules.check_reject = True
    gateway = LocalGateway(database, empty=_EMPTY)
    gateway.prepare()
    halfway = PullResult(10, 5, 1, False, False)

    with pytest.raises(CachePullError) as raised:
        gateway.check({"parameter_contract": "p1"}, halfway)

    assert raised.value.code == "revision_mismatch"
    assert "openrouter_adapter" in raised.value.message
    assert raised.value.result == halfway


def test_a_batch_is_loaded_into_the_gateway_database(
    gateway_modules: SimpleNamespace, database: Path
) -> None:
    added = LocalGateway(database, empty=_EMPTY).load(
        [{"key_hash": "a"}, {"key_hash": "b"}], _EMPTY
    )

    assert added == 1
    assert gateway_modules.loaded == [([{"key_hash": "a"}, {"key_hash": "b"}], database)]


@pytest.mark.parametrize(
    ("reason", "code", "hint"),
    [
        ("not_a_gateway_database", "local_gateway_missing", "screamingface up"),
        ("outdated_gateway_database", "local_gateway_outdated", "migrate"),
        ("malformed_row", "malformed_page", None),
        ("something_new", "local_load_refused", None),
    ],
)
def test_each_loader_refusal_names_what_to_do(
    gateway_modules: SimpleNamespace, database: Path, reason: str, code: str, hint: str | None
) -> None:
    gateway_modules.reject = reason

    with pytest.raises(CachePullError) as raised:
        LocalGateway(database, empty=_EMPTY).load([{"key_hash": "a"}], _EMPTY)

    assert raised.value.code == code
    if hint is not None:
        assert hint in (raised.value.hint or "")


def test_missing_runtime_modules_probes_without_importing(monkeypatch: pytest.MonkeyPatch) -> None:
    from screamingface._runtime import server

    monkeypatch.setattr(server, "_RUNTIME_ONLY_MODULES", ("json", "no_such_module_xyz"))

    assert local_module.missing_runtime_modules() == ("no_such_module_xyz",)
    assert "no_such_module_xyz" not in sys.modules


def test_a_database_failure_mid_load_says_to_call_again_with_the_counts_so_far(
    gateway_modules: SimpleNamespace, database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(_rows: Any, _database: Path) -> None:
        raise sqlite3.OperationalError("database is locked")

    loader = sys.modules["aigateway.core.request_cache.sqlite_loader"]
    monkeypatch.setattr(loader, "load_page", locked)
    halfway = PullResult(10, 5, 1, False, False)

    with pytest.raises(CachePullError) as raised:
        LocalGateway(database, empty=_EMPTY).load([{"key_hash": "a"}], halfway)

    assert raised.value.code == "local_load_failed"
    assert "database is locked" in raised.value.message
    assert "again" in (raised.value.hint or "")
    assert raised.value.result == halfway
    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)


@pytest.mark.parametrize(
    ("failure", "code", "hint"),
    [
        (
            _Rejected("outdated_gateway_database", "lacks metadata_json"),
            "local_gateway_outdated",
            "migrate",
        ),
        (
            _Rejected("not_a_gateway_database", "has no table"),
            "local_gateway_missing",
            "screamingface up",
        ),
        (sqlite3.OperationalError("database is locked"), "local_load_failed", "again"),
    ],
    ids=["outdated", "not-a-gateway", "locked"],
)
def test_a_database_the_pull_cannot_load_into_is_refused_before_any_request(
    gateway_modules: SimpleNamespace, database: Path, failure: Exception, code: str, hint: str
) -> None:
    gateway_modules.database_reject = failure

    with pytest.raises(CachePullError) as raised:
        LocalGateway(database, empty=_EMPTY).prepare()

    assert raised.value.code == code
    assert hint in (raised.value.hint or "")
    assert raised.value.result == _EMPTY


def test_a_pull_writes_to_the_database_the_runtime_starts_the_gateway_on(tmp_path: Path) -> None:
    from screamingface._runtime.config import RuntimeConfig

    started_on = RuntimeConfig(data_dir=tmp_path).gateway_database_url

    assert started_on == f"sqlite://{gateway_database(tmp_path.resolve())}"
