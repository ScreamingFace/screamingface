"""The Profile vocabulary is gone (OME-1138 Stage E, E5c; offline-only since OME-1209 E4b).

# FEATURE: Stage E plan §3 E4b made the index offline-only: the app neither wires nor imports
# `ProfileIndexStore`, and the opt-in Claude Code import at startup is retired — a set
# `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` only logs a warning. Plan §3 E5c then deletes the index,
# the Profile model, the backfill (`migrate_profiles`) and the history purge
# (`purge_profile_history`, spec Q5), once E5b's purge had run in every environment.
# INVARIANT: no module under `src/aigateway` imports `profile_index` or `profile_models`, and none
# of the retired modules can be imported.
# INVARIANT: importing `aigateway.main` loads neither `profile_index` nor a backfill module.
# WHY a fresh interpreter: the test session has long since imported both, so `sys.modules` here
# proves nothing about what the app pulls in.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import aigateway
from aigateway.core import credential_names, errors, provider_access
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.provider_access import (
    PairAuthorityStore,
    connection_admin,
    writer_floor,
)
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import _prepare_sqlite_db

_SRC = Path(inspect.getfile(aigateway)).resolve().parent
_RETIRED_MODULES = (
    "aigateway.core.profile_index",
    "aigateway.core.profile_models",
    "aigateway.core.provider_access.backfill_apply",
    "aigateway.core.provider_access.backfill_classify",
    "aigateway.core.provider_access.history_purge",
    "aigateway.core.provider_access.history_references",
    "aigateway.migrate_profiles",
    "aigateway.purge_profile_history",
)
_RETIRED_LEAVES = frozenset({"profile_index", "profile_models"})


def _imports_a_retired_leaf(path: Path) -> bool:
    """True when this module imports `profile_index` or `profile_models`, however it spells it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] in _RETIRED_LEAVES or any(
                alias.name in _RETIRED_LEAVES for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import) and any(
            alias.name.split(".")[-1] in _RETIRED_LEAVES for alias in node.names
        ):
            return True
    return False


def test_no_module_imports_the_profile_index_or_the_profile_models() -> None:
    importers = {
        str(path.relative_to(_SRC)) for path in _SRC.rglob("*.py") if _imports_a_retired_leaf(path)
    }

    assert importers == set()


@pytest.mark.parametrize("module", _RETIRED_MODULES)
def test_the_profile_vocabulary_and_its_offline_tools_are_gone(module: str) -> None:
    assert importlib.util.find_spec(module) is None


def test_only_the_neutral_credential_name_remains() -> None:
    # WHY: `profile_id_for` spelled the Profile document's id; with no document it names nothing.
    assert not hasattr(credential_names, "profile_id_for")
    assert credential_names.credential_name_for("acct", "default") == "acct:default"


def test_importing_the_app_loads_no_profile_index_and_no_backfill_module() -> None:
    probe = (
        "import sys, aigateway.main\n"
        "print(sorted(m for m in sys.modules if m.rsplit('.', 1)[-1] in "
        "('profile_index', 'backfill_classify', 'backfill_apply')))"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=120
    )

    assert result.stdout.strip() == "[]"


def test_the_app_wires_no_profile_index() -> None:
    from aigateway.main import create_app

    app = create_app()

    assert hasattr(app.state, "credential_store")
    assert not hasattr(app.state, "profile_index")


def test_the_profile_writers_and_the_startup_import_are_gone() -> None:
    assert importlib.util.find_spec("aigateway.plugins.anthropic_provider.bootstrap") is None
    assert not hasattr(ProviderPluginBase, "bootstrap_profiles")
    assert not hasattr(writer_floor, "bootstrap_under_the_floor")
    assert not hasattr(provider_access, "bootstrap_under_the_floor")
    assert not hasattr(errors, "BootstrapError")
    assert importlib.util.find_spec("aigateway.core.provider_access.profile_admin") is None
    assert not hasattr(connection_admin, "api_key_mirror")
    assert not hasattr(connection_admin.ConnectionBackedCredentialAdmin, "_mirror_siblings")
    assert {"claude_code_keychain_service", "bootstrap_user"}.isdisjoint(
        AnthropicPluginSettings.model_fields
    )


@pytest.mark.parametrize(
    "name", ["BackfillContext", "BackfillReport", "PairPlan", "all_account_ids", "classify_account"]
)
def test_the_provider_access_package_no_longer_re_exports_the_backfill(name: str) -> None:
    assert not hasattr(provider_access, name)
    assert name not in provider_access.__all__


class _ImportingPlugin(ProviderPluginBase):
    """A provider that would import a Profile at startup if anything still asked it to."""

    custom_llm_provider = "spy"

    def __init__(self) -> None:
        self.calls = 0

    def register_models(self) -> list[ModelEntry]:
        return []

    async def bootstrap_profiles(self, **kwargs: Any) -> None:
        self.calls += 1


def test_a_set_bootstrap_flag_only_warns_that_the_import_is_retired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    monkeypatch.setenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE", "1")
    _prepare_sqlite_db(database_url)
    from aigateway import main as main_module

    plugin = _ImportingPlugin()
    monkeypatch.setattr(main_module, "load_plugins", lambda registry: registry.register(plugin))

    app = main_module.create_app()
    # WHY on the app logger: `logs.configure` stops it propagating to the root, where caplog sits.
    app_logger = logging.getLogger("aigateway")
    app_logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            token = client.post(
                "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
            ).json()["token"]
            me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
            portal = client.portal
            assert portal is not None
            pair = portal.call(PairAuthorityStore().read, me["id"], "spy")
    finally:
        app_logger.removeHandler(caplog.handler)

    assert plugin.calls == 0
    assert (pair.migration_state, pair.generation) == ("none", 0)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE" in m and "retired" in m for m in warnings)
